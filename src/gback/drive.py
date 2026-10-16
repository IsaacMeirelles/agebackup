"""Cliente do Google Drive e download de arquivos.

Baseado em https://developers.google.com/workspace/drive/api/guides/manage-downloads
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

DRIVE_API_NAME = "drive"
DRIVE_API_VERSION = "v3"
CHUNK_SIZE = 1024 * 1024 * 8

# Erros que valem a pena repetir: a API do Drive é sensível a throttling.
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class DriveError(Exception):
    """Erro durante uma operação no Google Drive."""


class DownloadRestrictedError(DriveError):
    """O usuário não tem permissão de download para o arquivo."""


class FileNotFoundInDriveError(DriveError):
    """O ID informado não corresponde a nenhum arquivo acessível."""


class TransientDriveError(DriveError):
    """Falha temporária da API. Vale a pena tentar de novo."""


def get_service(credentials: object | None = None) -> Resource:
    """Cria o cliente da Drive API.

    Sem argumentos, monta as credenciais a partir da configuração do gback
    (Application Default Credentials ou Service Account). Também aceita um
    objeto de credenciais já pronto, útil para testes e para validar uma conta
    antes de salvá-la.

    Autentique antes com `gcloud auth application-default login` ou configure
    uma Service Account no `gback-setup`.
    """
    if credentials is None:
        try:
            from gback import config as config_mod

            credentials = config_mod.build_credentials()
        except DriveError:
            raise
        except Exception as error:
            raise DriveError(
                "Credenciais ausentes ou inválidas. Rode: gback-setup"
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
