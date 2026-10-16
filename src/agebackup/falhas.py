"""Log persistente dos arquivos que nãofue possível baixar.

O log de remoções (`manifest.py`) responde "o que sumiu do Drive". Este
responde "o que não consegui copiar", que é outra coisa: o arquivo continua no
Drive e continua faltando aqui.

O formato é TSV, com uma linha por tentativa falha, para ser lido tanto por
pessoa (`cat`, `grep`) quanto por script (`awk`, `cut`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agebackup import rotacao

FALHAS_NAME = ".agebackup-falhas.log"

# Categorias possíveis. Mantidas estáveis porque o log vira histórico.
CAT_BLOQUEADO = "bloqueado"
CAT_PERMISSAO = "permissao"
CAT_INEXISTENTE = "inexistente"
CAT_TEMPORARIA = "temporaria"
CAT_OPERACAO_LONGA = "operacao_longa"
CAT_LOCAL = "erro_local"
CAT_API = "erro_api"
CAT_LISTAGEM = "listagem"
CAT_COTA = "cota_excedida"
CAT_DESCONHECIDO = "desconhecido"

# Motivos que indicam que só o método files.download (operação de longa
# duração) resolve. Ver https://developers.google.com/workspace/drive/api/guides/handle-errors
MOTIVOS_LRO = frozenset(
    {
        "fileNotExportable",  # Google Vids não aceita files.export
        "fileNotDownloadable",  # documento do Workspace não é blob
    }
)

# Motivos de limite de uso da API.
MOTIVOS_COTA = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "dailyLimitExceeded",
        "sharingRateLimitExceeded",
    }
)

CATEGORIAS = frozenset(
    {
        CAT_BLOQUEADO,
        CAT_PERMISSAO,
        CAT_INEXISTENTE,
        CAT_TEMPORARIA,
        CAT_OPERACAO_LONGA,
        CAT_LOCAL,
        CAT_API,
        CAT_LISTAGEM,
        CAT_COTA,
        CAT_DESCONHECIDO,
    }
)


@dataclass
class Falha:
    """Uma falha de download."""

    nome: str
    categoria: str = CAT_DESCONHECIDO
    detalhe: str = ""
    drive_id: str = ""
    tentativas: int = 1
    quando: str = ""

    def __post_init__(self) -> None:
        if self.categoria not in CATEGORIAS:
            self.categoria = CAT_DESCONHECIDO
        if not self.quando:
            self.quando = datetime.now(UTC).isoformat(timespec="seconds")

    def para_linha(self) -> str:
        """Serializa em TSV, removendo tabs e quebras de linha do detalhe."""
        campos = [
            self.quando,
            self.nome,
            self.categoria,
            str(self.tentativas),
            self.drive_id,
            _limpar(self.detalhe),
        ]
        return "\t".join(campos)


def _limpar(texto: str) -> str:
    """Deixa o detalhe em uma linha, sem tabs, para não quebrar o TSV."""
    return " ".join(str(texto).split())[:500]


def caminho_log(pasta_logs: Path) -> Path:
    """Caminho do log de falhas dentro da pasta de logs."""
    return pasta_logs / FALHAS_NAME


def categorizar(error: Exception) -> tuple[str, str]:
    """Deduz a categoria e o detalhe legível de uma exceção."""
    from agebackup.drive import (
        DownloadRestrictedError,
        FileNotFoundInDriveError,
        TransientDriveError,
    )

    if isinstance(error, DownloadRestrictedError):
        return CAT_BLOQUEADO, "download bloqueado pelo dono do arquivo"
    if isinstance(error, FileNotFoundInDriveError):
        return CAT_INEXISTENTE, "arquivo não encontrado no Drive"
    if isinstance(error, TransientDriveError):
        return CAT_TEMPORARIA, str(error)
    if isinstance(error, OSError):
        return CAT_LOCAL, str(error)

    status = getattr(getattr(error, "resp", None), "status", None)
    if status:
        return _categorizar_http(error, status)
    if isinstance(error, ValueError):
        return CAT_LOCAL, str(error)

    return CAT_DESCONHECIDO, str(error)


def _codigos_de_erro(error: Exception) -> set[str]:
    """Extrai os motivos (`reason`) que a API devolveu no corpo do erro."""
    detalhes = getattr(error, "error_details", "")
    if not isinstance(detalhes, list):
        return set()
    return {
        item["reason"]
        for item in detalhes
        if isinstance(item, dict) and item.get("reason")
    }


def _categorizar_http(error: Exception, status: int) -> tuple[str, str]:
    """Categoriza um erro HTTP, reconhecendo os que exigem operação longa."""
    codigos = _codigos_de_erro(error)
    resumo = ", ".join(sorted(codigos))

    if codigos & MOTIVOS_LRO:
        return (
            CAT_OPERACAO_LONGA,
            f"exige files.download (operação de longa duração); motivo da API: {resumo}",
        )

    if codigos & MOTIVOS_COTA:
        return (CAT_COTA, f"cota da API excedida; motivo: {resumo}")

    return (CAT_API, f"HTTP {status} ({resumo})" if resumo else f"HTTP {status}")


def registrar(
    pasta_logs: Path,
    falhas: Iterable[Falha],
    sobrescrever: bool = False,
    rotacionar: bool = False,
) -> Path | None:
    """Acrescenta as falhas ao log.

    Por padrão anexa ao histórico. Com `sobrescrever`, substitui o arquivo,
    para registrar o estado da última execução.

    Com `rotacionar`, fecha e comprime o mês anterior antes de escrever.

    Devolve o caminho do log, ou None se não havia o que registrar ou se não
    foi possível escrever.
    """
    lista = list(falhas)
    if not lista:
        return None

    log = caminho_log(pasta_logs)

    if rotacionar:
        rotacao.rotacionar(log)

    try:
        pasta_logs.mkdir(parents=True, exist_ok=True)

        if sobrescrever and log.exists():
            # Reescreve do zero, deixando marca do que substituiu.
            log.write_text(
                f"# substituido em {datetime.now(UTC).isoformat(timespec='seconds')}\n",
                encoding="utf-8",
            )

        with log.open("a", encoding="utf-8") as arquivo:
            for falha in lista:
                arquivo.write(f"{falha.para_linha()}\n")
    except OSError:
        return None

    return log


def ler(pasta_logs: Path, ultimas: int = 0) -> list[dict[str, str]]:
    """Lê o log de falhas.

    Devolve uma lista de dicionários com as colunas do TSV. Se `ultimas` for
    maior que zero, devolve apenas as últimas N falhas.
    """
    log = caminho_log(pasta_logs)
    if not log.exists():
        return []

    linhas: list[dict[str, str]] = []
    try:
        for bruta in log.read_text(encoding="utf-8").splitlines():
            if not bruta.strip() or bruta.startswith("#"):
                continue
            partes = bruta.split("\t")
            partes += [""] * (5 - len(partes))
            linhas.append(
                {
                    "quando": partes[0],
                    "nome": partes[1],
                    "categoria": partes[2],
                    "tentativas": partes[3],
                    "drive_id": partes[4],
                    "detalhe": partes[5] if len(partes) > 5 else "",
                }
            )
    except OSError:
        return []

    return linhas[-ultimas:] if ultimas > 0 else linhas


def contar_por_categoria(falhas: list[dict[str, str]]) -> dict[str, int]:
    """Conta as falhas por categoria, da mais frequente para a menos."""
    contagem: dict[str, int] = {}
    for falha in falhas:
        categoria = falha.get("categoria", CAT_DESCONHECIDO)
        contagem[categoria] = contagem.get(categoria, 0) + 1
    return dict(sorted(contagem.items(), key=lambda item: -item[1]))
