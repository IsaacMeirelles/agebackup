"""Log persistente do status dos envios ao FTP/FTPS.

Uma linha por arquivo enviado (ou tentado), no formato TSV. Serve para saber o
que foi para o servidor, quando, de qual caminho local, para qual pasta remota e
com qual resultado, sem depender da janela do programa.

As colunas são:

1. data/hora da tentativa (ISO 8601);
2. status: ``ok`` ou ``falha``;
3. nome do arquivo;
4. caminho local completo;
5. tamanho local em bytes;
6. tamanho remoto em bytes (0 quando não conferido);
7. pasta remota usada;
8. conferência aplicada (``tamanho``, ``sha256`` ou vazio);
9. detalhe (erro, quando houver).

O log é rotacionado junto com os demais (``.agebackup-envios.log`` vira
``.agebackup-envios.<data>-<hora>.log.gz``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agebackup.logging_paths import caminho_completo

ENVIOS_NAME = ".agebackup-envios.log"
STATUS_OK = "ok"
STATUS_FALHA = "falha"
_STATUS = (STATUS_OK, STATUS_FALHA)


def caminho_log(pasta_logs: Path) -> Path:
    return Path(pasta_logs) / ENVIOS_NAME


def _limpar(texto: str, limite: int = 500) -> str:
    """Deixa o texto em uma linha, sem tabs, para não quebrar o TSV."""
    return " ".join(str(texto).split())[:limite]


@dataclass
class Envio:
    """Resultado de uma tentativa de envio."""

    arquivo: str
    caminho: str = ""
    status: str = STATUS_OK
    tamanho_local: int = 0
    tamanho_remoto: int = 0
    pasta_remota: str = ""
    conferencia: str = ""
    detalhe: str = ""
    quando: str = ""

    def __post_init__(self) -> None:
        if self.status not in _STATUS:
            self.status = STATUS_FALHA
        if not self.quando:
            self.quando = datetime.now(UTC).isoformat(timespec="seconds")

    def para_linha(self) -> str:
        campos = [
            self.quando,
            self.status,
            _limpar(self.arquivo),
            _limpar(self.caminho, limite=1000),
            str(max(0, int(self.tamanho_local))),
            str(max(0, int(self.tamanho_remoto or 0))),
            _limpar(self.pasta_remota),
            _limpar(self.conferencia),
            _limpar(self.detalhe),
        ]
        return "\t".join(campos)


def de_resultado(resultado, pasta_remota: str = "", arquivo: str = "") -> Envio:
    """Monta o registro a partir de um ``ftp.ResultadoEnvio``.

    Usa ``getattr`` para não criar dependência circular com o módulo ``ftp``.
    """
    caminho = getattr(resultado, "arquivo", None) or arquivo
    erro = getattr(resultado, "erro", "") or ""
    tamanho_remoto = getattr(resultado, "tamanho_remoto", None) or 0
    enviado = bool(getattr(resultado, "enviado", False))
    return Envio(
        arquivo=Path(caminho).name if caminho else "",
        caminho=caminho_completo(caminho) if caminho else "",
        status=STATUS_OK if enviado and not erro else STATUS_FALHA,
        tamanho_local=getattr(resultado, "tamanho_local", 0) or 0,
        tamanho_remoto=tamanho_remoto,
        pasta_remota=pasta_remota,
        conferencia="tamanho" if tamanho_remoto else "",
        detalhe=erro,
    )


def registrar(pasta_logs: Path, envios: list[Envio]) -> Path | None:
    """Acrescenta os envios ao log. Devolve o caminho ou None em erro de I/O."""
    if not envios:
        return None

    log = caminho_log(pasta_logs)
    try:
        pasta_logs.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as arquivo:
            for envio in envios:
                arquivo.write(f"{envio.para_linha()}\n")
    except OSError:
        return None

    return log


def ler(pasta_logs: Path, ultimas: int = 0) -> list[dict[str, str]]:
    """Lê o log de envios, opcionalmente só as últimas N linhas."""
    log = caminho_log(pasta_logs)
    if not log.exists():
        return []

    linhas: list[dict[str, str]] = []
    try:
        for bruta in log.read_text(encoding="utf-8").splitlines():
            if not bruta.strip() or bruta.startswith("#"):
                continue
            partes = bruta.split("\t")
            partes += [""] * (9 - len(partes))
            linhas.append(
                {
                    "quando": partes[0],
                    "status": partes[1],
                    "arquivo": partes[2],
                    "caminho": partes[3],
                    "tamanho_local": partes[4],
                    "tamanho_remoto": partes[5],
                    "pasta_remota": partes[6],
                    "conferencia": partes[7],
                    "detalhe": partes[8],
                }
            )
    except OSError:
        return []

    return linhas[-ultimas:] if ultimas > 0 else linhas
