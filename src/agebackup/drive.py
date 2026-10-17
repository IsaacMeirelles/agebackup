"""Cliente do Google Drive e download de arquivos.

Baseado em https://developers.google.com/workspace/drive/api/guides/manage-downloads
"""

from __future__ import annotations

import http.client
import json
import ssl
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest, MediaIoBaseDownload

DRIVE_API_NAME = "drive"
DRIVE_API_VERSION = "v3"
CHUNK_SIZE = 1024 * 1024 * 8

# Operações de longa duração: `files.download` monta o arquivo no servidor e
# devolve uma URL. Para documentos do Workspace volta pronta de imediato; o
# polling cobre os casos assíncronos.
DRIVE_OPERATIONS_URL = "https://www.googleapis.com/drive/v3/operations"
LRO_MAX_TENTATIVAS = 60
LRO_ESPERA = 2.0

# Erros que valem a pena repetir: a API do Drive é sensível a throttling.
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

# Erros de rede que podem acontecer no meio de um download e valem nova
# tentativa: conexão reiniciada/rompida/recusada, timeout e corpo incompleto.
# Um OSError genérico (disco cheio, permissão) fica de fora — repetir não ajuda.
RETRYABLE_NETWORK_ERRORS = (
    ConnectionError,
    TimeoutError,
    ssl.SSLError,
    http.client.IncompleteRead,
)


class DriveError(Exception):
    """Erro durante uma operação no Google Drive."""


class DownloadRestrictedError(DriveError):
    """O usuário não tem permissão de download para o arquivo."""


class FileNotFoundInDriveError(DriveError):
    """O ID informado não corresponde a nenhum arquivo acessível."""


class TransientDriveError(DriveError):
    """Falha temporária da API. Vale a pena tentar de novo."""


class ExportTooLargeError(DriveError):
    """O documento do Workspace excede o limite de 10 MB por exportação.

    O limite é do `files.export`, por requisição. Formatos mais leves (ex.: PDF)
    podem caber no limite mesmo quando o formato principal não cabe. O
    `files.download` (operação de longa duração) não tem esse limite.
    """


class AsyncDownloadError(DriveError):
    """A exportação assíncrona (`files.download`) falhou ou não concluiu."""


def get_service(credentials: object | None = None) -> Resource:
    """Cria o cliente da Drive API.

    Sem argumentos, monta as credenciais a partir da configuração do AgeBackup
    (Application Default Credentials ou Service Account). Também aceita um
    objeto de credenciais já pronto, útil para testes e para validar uma conta
    antes de salvá-la.

    Autentique antes com `gcloud auth application-default login` ou configure
    uma Service Account no `agebackup-setup`.
    """
    if credentials is None:
        try:
            from agebackup import config as config_mod

            credentials = config_mod.build_credentials()
        except DriveError:
            raise
        except Exception as error:
            raise DriveError(
                "Credenciais ausentes ou inválidas. Rode: agebackup-setup"
            ) from error

    try:
        return build(
            DRIVE_API_NAME,
            DRIVE_API_VERSION,
            credentials=credentials,
            cache_discovery=False,
        )
    except Exception as error:
        raise DriveError(f"Falha ao criar o cliente do Drive: {error}") from error


def _raise_for_status(error: HttpError) -> None:
    """Converte um HttpError na exceção de domínio correspondente."""
    status = error.resp.status
    details = error.error_details
    codes = {
        entry.get("reason")
        for entry in details
        if isinstance(details, list) and isinstance(entry, dict)
    }

    if status == 403:
        # O export de documentos do Workspace tem limite de 10 MB. É um 403 com
        # o motivo exportSizeLimitExceeded; tratamos à parte porque há saída:
        # exportar num formato mais leve (PDF).
        if "exportSizeLimitExceeded" in codes:
            raise ExportTooLargeError(
                "Documento do Workspace excede o limite de 10 MB do files.export"
            ) from error
        # Na API do Drive, 403 na prática significa permissão ou download
        # bloqueado. Rate limit é 429, então não há risco de confusão.
        detalhe = f": {codes}" if codes else ""
        raise DownloadRestrictedError(f"Sem permissão de leitura{detalhe}") from error
    if status == 404:
        raise FileNotFoundInDriveError(f"Arquivo não encontrado: {error}") from error
    if status in TRANSIENT_STATUSES:
        raise TransientDriveError(f"Falha temporária ({status}): {error}") from error

    raise DriveError(f"Erro da API do Drive ({status}): {error}") from error


def can_download(service: Resource, file_id: str) -> bool:
    """Verifica `capabilities.canDownload` antes de baixar.

    Pode ser False mesmo com acesso de leitura aos metadados.
    """
    meta = (
        service.files()
        .get(
            fileId=file_id,
            fields="id,name,capabilities(canDownload)",
            supportsAllDrives=True,
        )
        .execute()
    )
    return bool(meta.get("capabilities", {}).get("canDownload", False))


def file_name(service: Resource, file_id: str) -> str:
    """Retorna o nome do arquivo no Drive."""
    meta = (
        service.files()
        .get(fileId=file_id, fields="name", supportsAllDrives=True)
        .execute()
    )
    return meta["name"]


def _iter_chunks(downloader: MediaIoBaseDownload) -> Iterator[int]:
    """Itera os chunks de download, emitindo a porcentagem concluída."""
    done = False
    while not done:
        status, done = downloader.next_chunk()
        yield int(status.progress() * 100)


def _download(request: object, destination: Path) -> Path:
    """Baixa a requisição para destination de forma atômica.

    Escreve em `.tmp` e renomeia ao final, para que uma interrupção não deixe
    um arquivo truncado com aparência de completo.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.tmp")

    try:
        with partial.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request, chunksize=CHUNK_SIZE)
            for _ in _iter_chunks(downloader):
                pass
        partial.replace(destination)
    except HttpError as error:
        partial.unlink(missing_ok=True)
        _raise_for_status(error)
    except RETRYABLE_NETWORK_ERRORS as error:
        # Queda de rede no meio da transferência: trata como falha temporária
        # para o chamador repetir (licao09.mp3 caiu com "Connection reset by
        # peer", licao10.mp3 com "Broken pipe").
        partial.unlink(missing_ok=True)
        raise TransientDriveError(f"Falha de rede no download: {error}") from error
    except OSError:
        partial.unlink(missing_ok=True)
        raise

    return destination


def download_blob(
    service: Resource,
    file_id: str,
    destination: Path,
    check_permissions: bool = True,
) -> Path:
    """Baixa um arquivo binário (blob) do Drive.

    Use para imagens, vídeos e PDFs. Para documentos do Google Workspace
    (Docs, Sheets, Slides), use `export_document`.

    Args:
        service: cliente da Drive API.
        file_id: ID do arquivo no Drive.
        destination: caminho local de destino. Sobrescrito se existir.
        check_permissions: consultar `capabilities.canDownload` antes.

    Returns:
        Caminho do arquivo gravado.
    """
    if check_permissions and not can_download(service, file_id):
        raise DownloadRestrictedError(f"Download bloqueado para o arquivo {file_id}")

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    return _download(request, destination)


def export_document(
    service: Resource,
    file_id: str,
    destination: Path,
    mime_type: str = "application/pdf",
    shared_drive: bool = False,
) -> Path:
    """Exporta um documento do Google Workspace para outro formato.

    Use para Docs, Sheets e Slides. O limite da API é 10 MB por exportação.
    Para arquivos binários, use `download_blob`.

    Args:
        service: cliente da Drive API.
        file_id: ID do documento no Drive.
        destination: caminho local de destino. Sobrescrito se existir.
        mime_type: formato de destino.
        shared_drive: acrescentar `supportsAllDrives` à requisição.

    Returns:
        Caminho do arquivo gravado.

    Note:
        `export_media` da client library não aceita `supportsAllDrives`, embora
        a API o suporte. Em shared drives, o filtro `supportsAllDrives` é
        acrescentado à URL manualmente.
    """
    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    if shared_drive:
        request.uri += "&supportsAllDrives=true"
    return _download(request, destination)


def _consultar_operacao(http: object, nome: str) -> dict:
    """Consulta o estado de uma operação de longa duração (files.download)."""
    url = f"{DRIVE_OPERATIONS_URL}/{quote(nome, safe='')}"
    resposta, conteudo = http.request(
        url, method="GET", headers={"Accept": "application/json"}
    )
    if resposta.status >= 400:
        raise TransientDriveError(
            f"Falha ao consultar a operação de download ({resposta.status})"
        )
    return json.loads(conteudo)


def _aguardar_operacao(
    http: object, operacao: dict, max_tentativas: int, espera: float
) -> dict:
    """Aguarda a operação de longa duração terminar.

    Para documentos do Workspace ela volta pronta de imediato. O polling cobre os
    casos assíncronos (ex.: Google Vids), que demoram para montar o arquivo.
    """
    tentativas = 0
    while not operacao.get("done"):
        nome = operacao.get("name")
        if not nome:
            raise AsyncDownloadError("Operação de download sem nome para consultar")
        if tentativas >= max_tentativas:
            raise AsyncDownloadError("Operação de download demorou demais")
        time.sleep(espera)
        operacao = _consultar_operacao(http, nome)
        tentativas += 1

    erro = operacao.get("error")
    if erro:
        mensagem = erro.get("message", "") if isinstance(erro, dict) else str(erro)
        raise AsyncDownloadError(f"Operação de download falhou: {mensagem}")
    return operacao


def download_document_async(
    service: Resource,
    file_id: str,
    destination: Path,
    mime_type: str,
    shared_drive: bool = False,
    max_tentativas: int = LRO_MAX_TENTATIVAS,
    espera: float = LRO_ESPERA,
) -> Path:
    """Exporta um documento grande via `files.download` (operação longa).

    Diferente do `files.export` — limitado a 10 MB por requisição —, o
    `files.download` monta o arquivo no servidor e devolve uma URL de download,
    **sem esse limite**. Exige apenas o escopo `drive.readonly` e é o único
    caminho para formatos que o export não aceita (ex.: Google Vids).

    https://developers.google.com/workspace/drive/api/reference/rest/v3/files/download

    Args:
        service: cliente da Drive API.
        file_id: ID do documento no Drive.
        destination: caminho local de destino. Sobrescrito se existir.
        mime_type: formato de destino (ex.: o `.pptx` de uma apresentação).
        shared_drive: acrescentar `supportsAllDrives` à requisição.
        max_tentativas: consultas à operação antes de desistir.
        espera: segundos entre as consultas.

    Returns:
        Caminho do arquivo gravado.
    """
    try:
        requisicao = service.files().download(fileId=file_id, mimeType=mime_type)
    except AttributeError as error:
        raise AsyncDownloadError(
            "Cliente do Drive sem suporte a files.download"
        ) from error

    if shared_drive:
        requisicao.uri += "&supportsAllDrives=true"

    try:
        operacao = requisicao.execute()
    except HttpError as error:
        _raise_for_status(error)

    http = requisicao.http
    operacao = _aguardar_operacao(http, operacao, max_tentativas, espera)

    uri = (operacao.get("response") or {}).get("downloadUri")
    if not uri:
        raise AsyncDownloadError(f"files.download não devolveu URL para {file_id}")

    pedido = HttpRequest(
        http=http,
        postproc=lambda *args, **kwargs: None,
        uri=uri,
        method="GET",
        headers={},
        body=None,
    )
    return _download(pedido, destination)


def download_to(
    service: Resource,
    file_id: str,
    directory: Path,
    filename: str | None = None,
) -> Path:
    """Baixa um arquivo do Drive para dentro de um diretório.

    Mantém a extensão original e deforma o nome quando necessário para evitar
    sobrescrever arquivos existentes.
    """
    name = filename or file_name(service, file_id)
    return download_blob(service, file_id, _unique_path(directory / name))


def _unique_path(candidate: Path) -> Path:
    """Devolve um caminho livre, acrescentando sufixo se o candidato existir."""
    directory, name = candidate.parent, candidate.name
    if not candidate.exists():
        return candidate

    stem, dot, suffix = name.rpartition(".")
    counter = 1
    while True:
        alternative = (
            f"{stem} ({counter}){dot}{suffix}" if dot else f"{name} ({counter})"
        )
        candidate = directory / alternative
        if not candidate.exists():
            return candidate
        counter += 1


def resolve_destination(service: Resource, file_id: str, root: Path) -> Path:
    """Resolve o caminho de destino preservando a estrutura de pastas do Drive."""
    parts: list[str] = []
    current = file_id
    while True:
        meta = (
            service.files()
            .get(fileId=current, fields="id,name,parents", supportsAllDrives=True)
            .execute()
        )
        parts.append(meta["name"])
        parents = meta.get("parents") or []
        if not parents or parents[0] == "root":
            break
        current = parents[0]

    return _unique_path(root.joinpath(*reversed(parts)))
