"""Motor de backup do Google Drive."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gback import falhas as falhas_mod
from gback import manifest as manifest_mod
from gback import rotacao
from gback.config import Config, ConfigError
from gback.drive import (
    DownloadRestrictedError,
    DriveError,
    TransientDriveError,
    _unique_path,
    download_blob,
    export_document,
    file_name,
)
from gback.falhas import Falha
from gback.manifest import detectar_removidos, registrar_removidos

# Documentos do Google não existem como blob; precisam de export.
GOOGLE_WORKSPACE_MIME_PREFIX = "application/vnd.google-apps."
EXPORTABLE = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.drawing": "application/pdf",
    "application/vnd.google-apps.script": "application/vnd.google-apps.script+json",
}
# Policy now comes from config; keep default for backward compat reference
MAX_RETRIES_DEFAULT = 3
RETRY_DELAY = 2.0

# Arquivos que só podem ser baixados por operação de longa duração (LRO),
# via método files.download. Não há caminho alternativo.
#
# O Google Vids é o caso documentado: files.export devolve fileNotExportable
# ("Google Vids does not support files.export. Use files.download").
# https://developers.google.com/workspace/drive/api/guides/handle-errors
REQUER_LRO = frozenset(
    {
        "application/vnd.google-apps.video",  # Google Vids
    }
)

# Motivos de erro que indicam que a operação de longa duração resolveria.
# Mantidos em falhas.py, que é quem faz a classificação.

# O export de documentos do Workspace tem limite de 10 MB.
LIMITE_EXPORT = 10 * 1024 * 1024
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
    requer_lro: int = 0
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
        if self.requer_lro:
            partes.append(f"{self.requer_lro} exigem operação longa")
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


def exige_operacao_longa(entrada: FileEntry) -> str:
    """Diz se o arquivo só pode ser baixado por operação de longa duração.

    Devolve o motivo (string) quando exige, ou string vazia quando não.
    O gback não executa LRO, então esses arquivos são registrados como
    pendentes em vez de tentados.
    """
    if entrada.mime_type in REQUER_LRO:
        return (
            f"o tipo {entrada.mime_type} não aceita files.export; "
            "exige files.download (operação longa)"
        )

    if entrada.mime_type in EXPORTABLE and entrada.size > LIMITE_EXPORT:
        tamanho_mb = entrada.size / (1024 * 1024)
        return (
            f"documento de {tamanho_mb:.1f}MB excede o limite de "
            f"{LIMITE_EXPORT // (1024 * 1024)}MB do files.export"
        )

    return ""


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


def _baixar_com_retry(service, entrada: FileEntry, destino: Path, max_retries: int = MAX_RETRIES_DEFAULT) -> Path:
    """Baixa um arquivo, repetindo em falhas temporárias.

    Ao final ajusta o mtime do arquivo para a data de modificação informada pelo
    Drive. Sem isso, o backup seguinte não reconheceria o arquivo como
    inalterado e baixaria tudo de novo a cada execução.
    """
    tentativa = 0
    while True:
        try:
            if entrada.mime_type in EXPORTABLE:
                gravado = export_document(
                    service, entrada.file_id, destino, EXPORTABLE[entrada.mime_type]
                )
            else:
                gravado = download_blob(
                    service, entrada.file_id, destino, check_permissions=False
                )
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
            anterior = caminho_por_id.get(entrada.file_id)
            existente = _destino_existente(
                destino_raiz / anterior if anterior else destino, entrada
            )

            if existente is not None:
                stats.ignorados += 1
                if verbose:
                    print(f"  inalterado  {entrada.name}")
                continue

            # Arquivos que só podem ser baixados por operação de longa duração
            # (files.download) não são tentados: ficam registrados no log.
            motivo_lro = exige_operacao_longa(entrada)
            if motivo_lro:
                stats.requer_lro += 1
                stats.falhas_registro.append(
                    Falha(
                        nome=entrada.name,
                        categoria=falhas_mod.CAT_OPERACAO_LONGA,
                        detalhe=motivo_lro,
                        drive_id=entrada.file_id,
                    )
                )
                print(f"  requer LRO   {entrada.name}")
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
                gravado = _baixar_com_retry(service, entrada, destino, config.retry.attempts)
                manifest_mod.registrar(
                    registros,
                    str(gravado.relative_to(destino_raiz)),
                    entrada.file_id,
                    entrada.name,
                    gravado.stat().st_size,
                    entrada.modified_time,
                )
                stats.baixados += 1
                stats.bytes_novos += gravado.stat().st_size
                print(f"\r  ok           {entrada.name}  ", flush=True)
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
    stats.removidos_na_origem = len(removidos)

    pasta_logs = config.logs.pasta(destino_raiz)

    if removidos and not dry_run:
        log = registrar_removidos(pasta_logs, removidos, registros)
        for caminho in removidos:
            print(f"  removido     {caminho}")
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
    from gback import config as config_mod

    config = config_mod.load()
    if config is None:
        raise ConfigError(
            "Nenhuma configuracao encontrada. Rode primeiro:\n  uv run gback-setup"
        )
    if not config.backup.destination:
        raise ConfigError("Destino nao definido. Reconfigure com: uv run gback-setup")
    return config
