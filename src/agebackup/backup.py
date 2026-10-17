"""Motor de backup do Google Drive."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from googleapiclient.errors import HttpError

from agebackup import falhas as falhas_mod
from agebackup import manifest as manifest_mod
from agebackup import reconstruir as reconstruir_mod
from agebackup import rotacao
from agebackup.config import Config, ConfigError, describe_error
from agebackup.drive import (
    DownloadRestrictedError,
    DriveError,
    ExportTooLargeError,
    TransientDriveError,
    _unique_path,
    download_blob,
    download_document_async,
    export_document,
    file_name,
)
from agebackup.falhas import Falha
from agebackup.manifest import detectar_removidos, registrar_removidos

# Documentos do Google não existem como blob; precisam de export.
GOOGLE_WORKSPACE_MIME_PREFIX = "application/vnd.google-apps."
EXPORTABLE = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.drawing": "application/pdf",
    "application/vnd.google-apps.script": "application/vnd.google-apps.script+json",
    # Google Vids: o files.export recusa (fileNotExportable); só o files.download
    # (LRO) entrega, como MP4. Ver LRO_SOMENTE.
    "application/vnd.google-apps.video": "video/mp4",
}

# Extensão local correspondente a cada formato exportado. Sem isso os documentos
# do Google eram gravados sem extensão (o nome no Drive não tem uma), o que
# deixava o arquivo inutilizável ao abrir por duplo clique.
EXTENSAO_EXPORT = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/pdf": ".pdf",
    "application/vnd.google-apps.script+json": ".json",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "video/mp4": ".mp4",
}

# Quando o formato principal estoura o limite de 10 MB do files.export, tenta-se
# este. O PDF costuma ser bem menor (comprime as mídias), então Slides grandes
# que falham como .pptx costumam caber como .pdf.
FORMATO_FALLBACK = "application/pdf"

# Um Google Docs também pode ser exportado como texto (Markdown), que é pequeno e
# editável. Serve de plano B quando o .docx estoura o limite e a Docs API nativa
# não está disponível: é um export do Drive, então basta a Drive API.
MIME_DOCUMENTO = "application/vnd.google-apps.document"
FORMATO_TEXTO = "text/markdown"
EXTENSAO_TEXTO = ".md"

# Policy now comes from config; keep default for backward compat reference
MAX_RETRIES_DEFAULT = 3
RETRY_DELAY = 2.0

# Motivo de um arquivo que saiu da listagem, apurado com um files.get por ID:
#   - 404: sem acesso (movido para fora da pasta compartilhada);
#   - trashed=true: excluído no Drive;
#   - senão: removido (deixou de ser listado, mas ainda acessível).
REMOCAO_SEM_ACESSO = "sem_acesso"
REMOCAO_EXCLUIDO = "excluido"
REMOCAO_REMOVIDO = "removido"

# Tipos nativos que **só** o `files.download` (operação de longa duração, LRO)
# entrega: o `files.export` devolve `fileNotExportable`. Não há export
# alternativo, então não se tenta o formato principal — vai direto para o LRO.
#
# O Google Vids é o caso documentado (baixado como MP4):
# https://developers.google.com/workspace/drive/api/guides/ref-export-formats
#
# Documentos do Workspace grandes também usam `files.download`, mas por outro
# caminho (`_baixar_nativo_grande`), que ainda tem o PDF como reserva.
LRO_SOMENTE = frozenset(
    {
        "application/vnd.google-apps.video",  # Google Vids
    }
)

# Motivos de erro que indicam que a operação de longa duração resolveria.
# Mantidos em falhas.py, que é quem faz a classificação.

PAGE_SIZE = 100


@dataclass
class FileEntry:
    """Um arquivo do Drive candidato ao backup."""

    file_id: str
    name: str
    mime_type: str
    size: int
    modified_time: str
    trashed: bool = False
    # Nomes das pastas ancestrais, da raiz para baixo. Viram o caminho local,
    # espelhando a árvore do Drive no disco.
    pastas: tuple[str, ...] = ()


@dataclass
class Stats:
    """Contadores de uma execução de backup."""

    total: int = 0
    baixados: int = 0
    ignorados: int = 0
    falhas: int = 0
    bytes_novos: int = 0
    removidos_na_origem: int = 0
    removidos_sem_acesso: int = 0
    # Baixados por operação de longa duração (LRO), tipos sem export (ex.: Vids).
    requer_lro: int = 0
    # Arquivos nativos grandes demais para exportar: ficaram em PDF (aparência
    # garantida), mas o original editável precisa ser baixado pela web.
    originais_pendentes: int = 0
    dry_run: bool = False
    falhas_registro: list[Falha] = field(default_factory=list)

    @property
    def erros(self) -> list[tuple[str, str]]:
        """Falhas no formato antigo: (nome, detalhe)."""
        return [(falha.nome, falha.detalhe) for falha in self.falhas_registro]

    def resumo(self) -> str:
        verbos = "a baixar" if self.dry_run else "baixados"
        partes = [
            f"{self.total} arquivos",
            f"{self.baixados} {verbos}",
            f"{self.ignorados} inalterados",
        ]
        if self.removidos_na_origem:
            partes.append(f"{self.removidos_na_origem} removidos na origem")
        if self.removidos_sem_acesso:
            partes.append(f"{self.removidos_sem_acesso} sem acesso (fora do escopo)")
        if self.requer_lro:
            partes.append(f"{self.requer_lro} por operação longa")
        if self.originais_pendentes:
            partes.append(f"{self.originais_pendentes} com original grande")
        if self.falhas:
            partes.append(f"{self.falhas} falhas")
        if self.bytes_novos:
            partes.append(f"{_formatar_bytes(self.bytes_novos)} novos")
        return ", ".join(partes)


def _formatar_bytes(valor: int) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024:
            return (
                f"{valor:.0f}{unidade}" if unidade == "B" else f"{valor:.1f}{unidade}"
            )
        valor /= 1024
    return f"{valor:.1f}TB"


def _entrada(item: dict, pastas: tuple[str, ...]) -> FileEntry:
    """Converte um item bruto da API em FileEntry."""
    return FileEntry(
        file_id=item["id"],
        name=item["name"],
        mime_type=item.get("mimeType", ""),
        size=int(item.get("size", 0) or 0),
        modified_time=item.get("modifiedTime", ""),
        trashed=bool(item.get("trashed", False)),
        pastas=pastas,
    )


def _paginar(service, parametros: dict, consulta: str) -> Iterator[dict]:
    """Percorre as páginas de files.list, rendendo cada item bruto."""
    parametros = {**parametros, "q": consulta}
    token = None
    while True:
        if token:
            parametros["pageToken"] = token

        resposta = service.files().list(**parametros).execute()
        yield from resposta.get("files", [])

        token = resposta.get("nextPageToken")
        if not token:
            break


def _nome_pasta(service, folder_id: str) -> str:
    """Nome de uma pasta, usado como primeiro nível do caminho local.

    É cosmético: se a consulta falhar, devolve vazio e o caminho passa a ser
    relativo à própria pasta.
    """
    try:
        return file_name(service, folder_id)
    except Exception:  # noqa: BLE001 - o nome serve só para organizar o disco
        return ""


def _caminhos_dos_pais(
    por_id: dict[str, dict], item_id: str, memo: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """Nomes das pastas ancestrais de um item, da raiz para baixo.

    Sobe pelos `parents` até chegar a uma pasta sem pai acessível (que passa a
    ser a raiz do que conseguimos enxergar). Resultados ficam em cache para não
    repetir o mesmo trecho da árvore.
    """
    if item_id in memo:
        return memo[item_id]

    cadeia: list[str] = []
    atual = item_id
    while atual not in memo:
        item = por_id.get(atual)
        if item is None:
            memo[atual] = ()
            break

        pais = item.get("parents") or []
        pai = pais[0] if pais else ""
        if not pai or pai == "root" or pai not in por_id or pai in cadeia:
            memo[atual] = ()
            break

        cadeia.append(atual)
        atual = pai

    # De baixo para cima: cada nó herda os ancestrais do pai e acrescenta o
    # nome do pai.
    for no in reversed(cadeia):
        pai = (por_id[no].get("parents") or [""])[0]
        memo[no] = memo[pai] + (por_id[pai]["name"],)

    return memo[item_id]


def _listar_pasta(service, parametros: dict, folder_id: str) -> Iterator[FileEntry]:
    """Desce na pasta informada, montando o caminho durante o percurso."""
    raiz = _nome_pasta(service, folder_id)
    fila: list[tuple[str, tuple[str, ...]]] = [(folder_id, (raiz,) if raiz else ())]
    visitadas: set[str] = set()

    while fila:
        pasta, prefixo = fila.pop(0)
        if pasta in visitadas:
            continue
        visitadas.add(pasta)

        consulta = f"'{pasta}' in parents and trashed = false"

        for item in _paginar(service, parametros, consulta):
            if item.get("trashed"):
                continue
            if _eh_pasta(item.get("mimeType", "")):
                fila.append((item["id"], prefixo + (item["name"],)))
            else:
                yield _entrada(item, prefixo)


def listar_arquivos(
    service, folder_id: str = "", include_shared: bool = False
) -> Iterator[FileEntry]:
    """Percorre os arquivos do Drive, descendo nas subpastas.

    Devolve apenas arquivos (nunca pastas). Cada um traz `pastas`, o caminho de
    diretórios relativo à raiz do backup, para espelhar a árvore no disco.

    Com `folder_id`, o percurso começa nessa pasta (o nome dela entra no
    caminho) e desce nas subpastas. Sem `folder_id`, percorre todo o Drive
    visível numa única listagem, reconstruindo os caminhos pelos `parents`.
    """
    parametros = {
        "fields": (
            "nextPageToken," "files(id,name,mimeType,size,modifiedTime,trashed,parents)"
        ),
        "pageSize": PAGE_SIZE,
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": include_shared,
        "corpora": "allDrives" if include_shared else "user",
        "orderBy": "folder,name",
    }

    if folder_id:
        yield from _listar_pasta(service, parametros, folder_id)
        return

    itens = list(_paginar(service, parametros, "trashed = false"))
    por_id = {item["id"]: item for item in itens}
    memo: dict[str, tuple[str, ...]] = {}

    for item in itens:
        if item.get("trashed") or _eh_pasta(item.get("mimeType", "")):
            continue
        yield _entrada(item, _caminhos_dos_pais(por_id, item["id"], memo))


def _eh_pasta(mime_type: str) -> bool:
    return mime_type == "application/vnd.google-apps.folder"


def _destino_existente(arquivo: Path, entrada: FileEntry) -> Path | None:
    """Devolve o caminho se o arquivo local já corresponder ao do Drive.

    Compara a data de modificação do Drive com a do arquivo local. Se a data do
    Drive não vier preenchida, não confia no arquivo local e devolve None,
    obrigando o download.
    """
    if not arquivo.is_file():
        return None
    if not entrada.modified_time:
        return None

    modificacao = datetime.fromisoformat(entrada.modified_time)
    epoch = int(modificacao.timestamp())
    # Tolerância de 2s evita refazer o arquivo por arredondamento de timestamp.
    if abs(int(arquivo.stat().st_mtime) - epoch) <= 2:
        return arquivo
    return None


def _destino_export(destino: Path, formato: str | None) -> Path:
    """Caminho local de um export, com a extensão do formato.

    O nome no Drive dos documentos do Workspace não traz extensão. Sem
    acrescentar, o arquivo exportado ficaria sem uma e o sistema não saberia
    com que programa abrir. É idempotente: se o nome já terminar na extensão,
    devolve o caminho como está.
    """
    extensao = EXTENSAO_EXPORT.get(formato)
    if not extensao or destino.name.lower().endswith(extensao):
        return destino
    return destino.with_name(destino.name + extensao)


def _sem_extensao_export(destino: Path, formato: str | None) -> Path:
    """Remove a extensão de um export, para trocá-la por outra."""
    extensao = EXTENSAO_EXPORT.get(formato)
    if extensao and destino.name.lower().endswith(extensao):
        return destino.with_name(destino.name[: -len(extensao)])
    return destino


# Extensões de um editável recuperável: os formatos de export e o `.md` dos Docs.
EXTENSOES_RECUPERADAS = tuple(
    extensao
    for extensao in (*EXTENSAO_EXPORT.values(), EXTENSAO_TEXTO)
    if extensao != EXTENSAO_EXPORT.get(FORMATO_FALLBACK)
)


def original_recuperado(pdf: Path) -> bool:
    """Diz se já há um original/editável ao lado do PDF.

    Reconhece o export fiel (``Nome.pptx``, vindo do ``files.download``) e as
    reconstruções (``Nome.reconstruido.pptx``, ``Nome.reconstruido.md``).
    """
    base = _sem_extensao_export(pdf, FORMATO_FALLBACK)
    sufixos = ("", reconstruir_mod.SUFIXO_RECONSTRUIDO)
    return any(
        base.with_name(f"{base.name}{sufixo}{extensao}").exists()
        for sufixo in sufixos
        for extensao in EXTENSOES_RECUPERADAS
    )


def pendentes_de_original(destino_raiz: Path, pasta_logs: Path) -> set[str]:
    """IDs dos nativos grandes que ainda **não** têm o original ao lado do PDF.

    Cruza o log (categoria ``grande_demais``) com o manifesto para achar o
    caminho do PDF e conferir se o original/editável já foi recuperado. Serve
    para ``--listar-grandes`` não listar o que já foi resolvido: o log é
    histórico e não é reescrito quando o arquivo é recuperado.
    """
    extensao_pdf = EXTENSAO_EXPORT.get(FORMATO_FALLBACK, ".pdf")
    pdf_por_id: dict[str, Path] = {}
    for caminho, registro in manifest_mod.carregar(destino_raiz).items():
        if caminho.lower().endswith(extensao_pdf):
            pdf_por_id.setdefault(registro.drive_id, destino_raiz / caminho)

    pendentes: set[str] = set()
    for linha in falhas_mod.ler(pasta_logs):
        if linha.get("categoria") != falhas_mod.CAT_GRANDE:
            continue
        drive_id = linha.get("drive_id", "")
        if not drive_id:
            continue
        pdf = pdf_por_id.get(drive_id)
        if pdf is None or not original_recuperado(pdf):
            pendentes.add(drive_id)
    return pendentes


def _excedeu_export(entrada: FileEntry, gravado: Path) -> bool:
    """Diz se o arquivo salvou no formato de fallback (PDF) em vez do principal.

    Compara a extensão esperada com a gravada. É como o motor descobre, depois
    do download, que aquele nativo era grande demais para exportar.
    """
    formato = EXPORTABLE.get(entrada.mime_type)
    if not formato:
        return False
    extensao = EXTENSAO_EXPORT.get(formato, "")
    if not extensao or extensao == EXTENSAO_EXPORT.get(FORMATO_FALLBACK, ""):
        return False
    return not gravado.name.lower().endswith(extensao)


def _destino_reconstruido(
    destino: Path, formato: str | None, mime_type: str
) -> Path | None:
    """Caminho do sidecar editável (``Nome.reconstruido.pptx``).

    Devolve None quando o tipo não tem reconstrutor ou o formato não tem
    extensão conhecida.
    """
    extensao = reconstruir_mod.extensao_de(mime_type)
    if not extensao:
        return None
    base = _sem_extensao_export(destino, formato)
    return base.with_name(base.name + reconstruir_mod.SUFIXO_RECONSTRUIDO + extensao)


def _exportar_texto(
    service, mime_type: str, file_id: str, destino: Path, formato: str | None
) -> Path | None:
    """Salva um Google Docs grande como ``.md`` (plano B pela Drive API).

    O ``text/markdown`` é um export do Drive, então funciona mesmo com a Docs API
    desabilitada. Devolve None quando não é um documento ou quando o export
    falha; nunca interrompe o backup.
    """
    if mime_type != MIME_DOCUMENTO:
        return None

    base = _sem_extensao_export(destino, formato)
    alvo = base.with_name(
        base.name + reconstruir_mod.SUFIXO_RECONSTRUIDO + EXTENSAO_TEXTO
    )
    try:
        return export_document(service, file_id, alvo, FORMATO_TEXTO)
    except (DriveError, OSError) as error:
        print(
            f"\n    texto (Markdown) indisponível ({describe_error(error)})",
            file=sys.stderr,
        )
        return None


def _reconstruir_se_possivel(
    service, entrada: FileEntry, destino: Path, formato: str | None
) -> Path | None:
    """Tenta salvar o original editável ao lado do PDF. Nunca interrompe.

    Primeiro tenta a API nativa (``.pptx``/``.docx``/``.xlsx``). Se ela estiver
    desabilitada ou falhar, um Google Docs ainda vira ``.md`` pelo export do
    Drive — que só exige a Drive API. É um extra: se nada der certo, o PDF
    permanece e o arquivo entra em ``--listar-grandes`` para baixar pela web.
    """
    alvo = _destino_reconstruido(destino, formato, entrada.mime_type)
    if alvo is None:
        return None

    try:
        caminho = reconstruir_mod.reconstruir(entrada.mime_type, entrada.file_id, alvo)
    except Exception as error:  # noqa: BLE001 - o PDF já garante o essencial
        caminho = _exportar_texto(
            service, entrada.mime_type, entrada.file_id, destino, formato
        )
        if caminho is not None:
            print(f"\r    texto salvo {caminho.name}  ", file=sys.stderr)
            return caminho
        print(
            f"\n    original editável indisponível "
            f"({describe_error(error)}); baixe pela web",
            file=sys.stderr,
        )
        return None

    print(f"\r    reconstruído {caminho.name}  ", file=sys.stderr)
    return caminho


def _baixar_uma_vez(service, entrada: FileEntry, destino: Path) -> Path:
    """Baixa (ou exporta) o arquivo uma vez, sem repetir por falha temporária.

    Documentos do Workspace vão no formato principal. Quando esse formato
    estoura o limite de 10 MB por requisição, a estratégia está em
    `_baixar_nativo_grande`. Tipos sem export (ex.: Google Vids) vão direto para
    o `files.download` (LRO), o único caminho que os entrega.
    """
    formato = EXPORTABLE.get(entrada.mime_type)
    if not formato:
        return download_blob(service, entrada.file_id, destino, check_permissions=False)

    alvo = _destino_export(destino, formato)
    if entrada.mime_type in LRO_SOMENTE:
        return download_document_async(service, entrada.file_id, alvo, formato)

    try:
        return export_document(service, entrada.file_id, alvo, formato)
    except ExportTooLargeError:
        return _baixar_nativo_grande(service, entrada, destino, formato)


def _baixar_nativo_grande(
    service, entrada: FileEntry, destino: Path, formato: str
) -> Path:
    """Resolve um nativo que estourou o limite de 10 MB do ``files.export``.

    Tenta, nesta ordem:

    1. o próprio **original editável**, via ``files.download`` (operação de longa
       duração), que **não tem** o limite de 10 MB nem exige a API nativa;
    2. o **PDF**, que comprime as mídias e costuma caber — guardado como o
       arquivo principal, com o editável reconstruído ao lado (``.reconstruido``);
    3. se nem o PDF couber, a **reconstrução** (ou o ``.md`` de um Doc) vira o
       próprio arquivo, para o backup não ficar sem nada.

    Uma falha temporária na etapa 1 sobe para ``_baixar_com_retry`` repetir; as
    demais caem para o PDF.
    """
    # 1) O melhor resultado: o próprio original editável, sem o limite de 10 MB.
    try:
        gravado = download_document_async(
            service, entrada.file_id, _destino_export(destino, formato), formato
        )
    except TransientDriveError:
        # Deixa o retry decidir: pode ser só throttling, e o original vale a pena.
        raise
    except (DriveError, OSError) as error:
        print(
            f"\n    download direto indisponível ({describe_error(error)})",
            file=sys.stderr,
        )
    else:
        print(f"\r    original salvo {gravado.name}  ", file=sys.stderr)
        return gravado

    # 2) PDF, que comprime as mídias e costuma caber no limite.
    base = _sem_extensao_export(destino, formato)
    alvo = _destino_export(base, FORMATO_FALLBACK)
    print(f"    export grande demais, repetindo em {alvo.name}", file=sys.stderr)
    try:
        gravado = export_document(service, entrada.file_id, alvo, FORMATO_FALLBACK)
    except ExportTooLargeError:
        # Nem o PDF coube. Antes de desistir, tenta o editável (API nativa, ou o
        # .md de um Doc), que não passam pelo limite do export.
        print("    PDF também grande demais; tentando o editável", file=sys.stderr)
        editavel = _reconstruir_se_possivel(service, entrada, destino, formato)
        if editavel is None:
            raise
        return editavel
    _reconstruir_se_possivel(service, entrada, destino, formato)
    return gravado


def _baixar_com_retry(
    service, entrada: FileEntry, destino: Path, max_retries: int = MAX_RETRIES_DEFAULT
) -> Path:
    """Baixa um arquivo, repetindo em falhas temporárias.

    Ao final ajusta o mtime do arquivo para a data de modificação informada pelo
    Drive. Sem isso, o backup seguinte não reconheceria o arquivo como
    inalterado e baixaria tudo de novo a cada execução.
    """
    tentativa = 0
    while True:
        try:
            gravado = _baixar_uma_vez(service, entrada, destino)
            _ajustar_mtime(gravado, entrada.modified_time)
            return gravado
        except TransientDriveError:
            tentativa += 1
            if tentativa > max_retries:
                raise
            espera = RETRY_DELAY * tentativa
            print(
                f"    falha temporária, repetindo em {espera:.0f}s "
                f"({tentativa}/{max_retries})",
                file=sys.stderr,
            )
            time.sleep(espera)


def _ajustar_mtime(arquivo: Path, modified_time: str) -> None:
    """Define o mtime do arquivo local para a data informada pelo Drive."""
    if not modified_time:
        return

    try:
        epoch = datetime.fromisoformat(modified_time).timestamp()
        os.utime(arquivo, (epoch, epoch))
    except OSError, ValueError:
        pass


def _rotacionar_logs(config: Config, destino: Path) -> None:
    """Aplica a política de rotação aos logs, avisando o que mudou."""
    politica = config.logs

    if not politica.enabled:
        return

    pasta_logs = politica.pasta(destino)

    try:
        pasta_logs.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"\n  aviso: não foi possível criar {pasta_logs}: {error}")
        return

    for alvo in (
        falhas_mod.caminho_log(pasta_logs),
        manifest_mod.caminho_removidos(pasta_logs),
    ):
        resultado = rotacao.rotacionar(
            alvo,
            meses=politica.keep_months,
            comprimir=politica.compress,
        )

        if resultado.erro:
            print(f"\n  aviso na rotação de {alvo.name}: {resultado.erro}")

        for arquivo in resultado.comprimidos:
            print(f"  log comprimido {arquivo.name}")

        for arquivo in resultado.removidos:
            print(f"  log removido   {arquivo.name} (fora da retenção)")


def classificar_remocao(service, drive_id: str) -> str:
    """Diz por que um arquivo do manifesto deixou de ser listado.

    Consulta o arquivo por ID e devolve um dos motivos:

    - ``REMOCAO_SEM_ACESSO``: a API respondeu 403/404. Normalmente o arquivo
      foi movido para uma pasta que não está compartilhada com a conta, então
      ele saiu do escopo do backup (não foi excluído).
    - ``REMOCAO_EXCLUIDO``: o arquivo ainda existe, mas está na lixeira.
    - ``REMOCAO_REMOVIDO``: o arquivo ainda existe e não está na lixeira, mas
      não apareceu na listagem (situação rara). Também é o padrão quando a
      consulta falha por outro motivo, para não esconder uma remoção real.
    """
    try:
        meta = (
            service.files()
            .get(fileId=drive_id, fields="id,trashed", supportsAllDrives=True)
            .execute()
        )
    except HttpError as error:
        if error.resp.status in (403, 404):
            return REMOCAO_SEM_ACESSO
        return REMOCAO_REMOVIDO
    except OSError:
        return REMOCAO_REMOVIDO

    if not meta or not meta.get("id"):
        return REMOCAO_REMOVIDO
    if meta.get("trashed"):
        return REMOCAO_EXCLUIDO
    return REMOCAO_REMOVIDO


def _mime_do_drive(service, drive_id: str) -> str:
    """Consulta o mimeType de um arquivo no Drive pelo ID."""
    meta = (
        service.files()
        .get(fileId=drive_id, fields="id,mimeType", supportsAllDrives=True)
        .execute()
    )
    return meta.get("mimeType", "")


def _candidatos_a_reconstruir(
    destino_raiz: Path, pasta_logs: Path
) -> dict[str, tuple[str, Path]]:
    """Descobre os PDFs que vieram de nativos e podem virar ``.reconstruido``.

    Duas fontes, unidas por ``drive_id``:

    1. o log de falhas (categoria ``grande_demais``) — o registro explícito do
       estouro do export;
    2. o manifesto — para pegar os arquivos baixados **antes** desta função
       existir. Como os uploads guardam a extensão no nome do Drive e os nativos
       não, um arquivo local ``.pdf`` cujo ``nome`` no Drive não termina em
       ``.pdf`` é um nativo exportado, não um PDF enviado. Isso evita uma
       consulta de tipo para cada PDF da conta.

    Devolve ``drive_id -> (nome, caminho_do_pdf)``.
    """
    extensao_pdf = EXTENSAO_EXPORT.get(FORMATO_FALLBACK, ".pdf")

    do_log: set[str] = set()
    for linha in falhas_mod.ler(pasta_logs):
        if linha.get("categoria") == falhas_mod.CAT_GRANDE and linha.get("drive_id"):
            do_log.add(linha["drive_id"])

    candidatos: dict[str, tuple[str, Path]] = {}
    for caminho, registro in manifest_mod.carregar(destino_raiz).items():
        if not caminho.lower().endswith(extensao_pdf):
            continue
        nome = registro.nome or ""
        veio_de_nativo = not nome.lower().endswith(extensao_pdf)
        if registro.drive_id in do_log or veio_de_nativo:
            candidatos[registro.drive_id] = (nome, destino_raiz / caminho)
    return candidatos


def reconstruir_pendentes(
    service, config: Config, destino_raiz: Path
) -> tuple[int, int]:
    """Recupera os originais grandes já baixados como PDF.

    Os arquivos já baixados ficam "inalterados" nas execuções seguintes, então a
    recuperação automática (que só roda no download) não os alcança. Este comando
    varre o manifesto e o log em busca dos PDFs que vieram de nativos e, para
    cada um, tenta nesta ordem:

    1. o **original verdadeiro** via ``files.download`` (operação longa, sem o
       limite de 10 MB e sem precisar das APIs nativas) — gravado com o nome
       normal (ex.: ``Proposta de consultoria.pptx``);
    2. a **reconstrução** editável pela API nativa (``.reconstruido``), útil
       antes desta função existir;
    3. o ``.md`` de um Google Docs, pela Drive API.

    Devolve ``(recuperados, falhas)``.
    """
    pasta_logs = config.logs.pasta(destino_raiz)
    candidatos = _candidatos_a_reconstruir(destino_raiz, pasta_logs)

    reconstruidos = 0
    falhas = 0
    for drive_id, (nome, pdf) in candidatos.items():
        try:
            mime = _mime_do_drive(service, drive_id)
        except (DriveError, OSError) as error:
            falhas += 1
            print(f"  {nome}: tipo indisponível ({describe_error(error)})")
            continue

        # 1) O ideal: o próprio original editável, sem o limite de 10 MB.
        formato = EXPORTABLE.get(mime)
        if formato:
            base = _sem_extensao_export(pdf, FORMATO_FALLBACK)
            alvo = _destino_export(base, formato)
            if alvo.exists():
                continue
            try:
                caminho = download_document_async(service, drive_id, alvo, formato)
            except (DriveError, OSError) as error:
                print(
                    f"  {nome}: original direto indisponível "
                    f"({describe_error(error)})"
                )
            else:
                reconstruidos += 1
                print(f"  original salvo {caminho.name}")
                continue

        if not reconstruir_mod.tem_reconstrutor(mime):
            continue

        alvo = _destino_reconstruido(pdf, FORMATO_FALLBACK, mime)
        if alvo is None:
            continue
        try:
            caminho = reconstruir_mod.reconstruir(mime, drive_id, alvo)
        except Exception as error:  # noqa: BLE001 - a API nativa pode estar off
            # Um Doc ainda pode virar .md pelo export do Drive.
            caminho = _exportar_texto(service, mime, drive_id, pdf, FORMATO_FALLBACK)
            if caminho is None:
                falhas += 1
                print(f"  {nome}: falhou ({describe_error(error)})")
                continue
        reconstruidos += 1
        print(f"  reconstruído {caminho.name}")

    return reconstruidos, falhas


def executar_backup(
    service,
    config: Config,
    destino_raiz: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> Stats:
    """Percorre o Drive e baixa o que mudou.

    Args:
        service: cliente da Drive API.
        config: configuração carregada.
        destino_raiz: pasta local onde gravar.
        dry_run: apenas listar o que seria baixado, sem gravar.
        verbose: detalhar cada arquivo.

    Returns:
        Estatísticas da execução.
    """
    stats = Stats()
    stats.dry_run = dry_run
    folder_id = config.backup.folder_id or ""
    incluir_compartilhados = config.backup.include_shared_drives

    if not dry_run:
        # Uma vez por execução: fecha, comprime e aplica a retenção.
        _rotacionar_logs(config, destino_raiz)

    registros = manifest_mod.carregar(destino_raiz)
    # Onde cada arquivo já foi gravado. Sem isso, um arquivo que ganhou sufixo
    # para evitar colisão seria baixado de novo a cada execução.
    caminho_por_id = {
        registro.drive_id: caminho for caminho, registro in registros.items()
    }
    ids_vistos: set[str] = set()
    listagem_completa = True

    try:
        entradas = listar_arquivos(service, folder_id, incluir_compartilhados)
        for entrada in entradas:
            if _eh_pasta(entrada.mime_type):
                continue

            ids_vistos.add(entrada.file_id)
            stats.total += 1
            destino = destino_raiz.joinpath(*entrada.pastas, entrada.name)
            # Documentos do Workspace ganham a extensão do formato exportado, que
            # o nome no Drive não traz. Aplicado aqui para que a checagem de
            # "inalterado" e o desvio de colisão já olhem o caminho final.
            destino = _destino_export(destino, EXPORTABLE.get(entrada.mime_type))
            anterior = caminho_por_id.get(entrada.file_id)
            existente = _destino_existente(
                destino_raiz / anterior if anterior else destino, entrada
            )

            if existente is not None:
                stats.ignorados += 1
                if verbose:
                    print(f"  inalterado  {entrada.name}")
                continue

            if dry_run:
                stats.baixados += 1
                print(
                    f"  baixaria     {entrada.name} ({_formatar_bytes(entrada.size)})"
                )
                continue

            print(f"  baixando     {entrada.name}...", end="", flush=True)

            try:
                destino = _unique_path(destino)
                gravado = _baixar_com_retry(
                    service, entrada, destino, config.retry.attempts
                )
                caminho_novo = str(gravado.relative_to(destino_raiz))
                manifest_mod.registrar(
                    registros,
                    caminho_novo,
                    entrada.file_id,
                    entrada.name,
                    gravado.stat().st_size,
                    entrada.modified_time,
                )
                # Se o arquivo mudou de nome/caminho (renome no Drive ou a
                # extensão que passamos a acrescentar), descarta a entrada
                # antiga para não deixar duas apontando para o mesmo ID.
                if anterior and anterior != caminho_novo:
                    registros.pop(anterior, None)
                stats.baixados += 1
                stats.bytes_novos += gravado.stat().st_size
                # Tipos sem export (ex.: Google Vids) só saem por operação longa.
                if entrada.mime_type in LRO_SOMENTE:
                    stats.requer_lro += 1
                print(f"\r  ok           {entrada.name}  ", flush=True)

                # Nativo grande demais para exportar: ficou em PDF. Registra
                # para `--listar-grandes`, sem contar como falha (o backup
                # cumpriu o essencial: guardou o conteúdo).
                if _excedeu_export(entrada, gravado):
                    stats.originais_pendentes += 1
                    stats.falhas_registro.append(
                        Falha(
                            nome=entrada.name,
                            categoria=falhas_mod.CAT_GRANDE,
                            detalhe=(
                                "grande demais para exportar; guardado em PDF "
                                "(original editável pela web)"
                            ),
                            drive_id=entrada.file_id,
                        )
                    )
            except (DownloadRestrictedError, DriveError, OSError, ValueError) as error:
                stats.falhas += 1
                categoria, detalhe = falhas_mod.categorizar(error)
                stats.falhas_registro.append(
                    Falha(
                        nome=entrada.name,
                        categoria=categoria,
                        detalhe=detalhe,
                        drive_id=entrada.file_id,
                    )
                )
                print(f"\r  {categoria:<13}{entrada.name}", flush=True)
    except DriveError as error:
        # A listagem parou no meio. Não dá para afirmar o que sumiu do Drive.
        listagem_completa = False
        stats.falhas += 1
        categoria, detalhe = falhas_mod.categorizar(error)
        stats.falhas_registro.append(
            Falha(nome="<listagem>", categoria=falhas_mod.CAT_LISTAGEM, detalhe=detalhe)
        )
        print(f"\r  listagem interrompida: {detalhe.splitlines()[0][:60]}")

    removidos = detectar_removidos(
        destino_raiz, registros, ids_vistos, listagem_completa
    )

    motivos: dict[str, str] = {}
    if removidos:
        motivos = {
            caminho: classificar_remocao(service, registros[caminho].drive_id)
            for caminho in removidos
        }

    removidos_efetivos = [
        caminho for caminho in removidos if motivos[caminho] != REMOCAO_SEM_ACESSO
    ]
    stats.removidos_na_origem = len(removidos_efetivos)
    stats.removidos_sem_acesso = len(removidos) - len(removidos_efetivos)

    pasta_logs = config.logs.pasta(destino_raiz)

    if removidos and not dry_run:
        log = registrar_removidos(pasta_logs, removidos, registros, motivos=motivos)
        for caminho in removidos:
            motivo = motivos[caminho]
            if motivo == REMOCAO_SEM_ACESSO:
                rotulo = "sem acesso  "
            elif motivo == REMOCAO_EXCLUIDO:
                rotulo = "excluido    "
            else:
                rotulo = "removido    "
            print(f"  {rotulo}{caminho}")
        if log is None:
            stats.erros.append(("<log>", "não foi possível gravar o log de remoções"))
        else:
            print(f"  registrado em {log}")

    if stats.falhas_registro and not dry_run:
        log = falhas_mod.registrar(pasta_logs, stats.falhas_registro)
        if log is None:
            print("\n  aviso: não foi possível gravar o log de falhas")
        elif stats.falhas > len(stats.falhas_registro):
            print(f"\n  falhas registradas em {log}")

    if not dry_run:
        manifest_mod.salvar(destino_raiz, registros)

    return stats


def carregar_configuracao() -> Config:
    """Carrega a configuração ou orienta o usuário a rodar o assistente."""
    from agebackup import config as config_mod

    config = config_mod.load()
    if config is None:
        raise ConfigError(
            "Nenhuma configuracao encontrada. Rode primeiro:\n  uv run agebackup-setup"
        )
    if not config.backup.destination:
        raise ConfigError(
            "Destino nao definido. Reconfigure com: uv run agebackup-setup"
        )
    return config
