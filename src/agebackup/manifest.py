"""Manifesto dos arquivos baixados e detecção de remoções na origem.

O manifesto registra o que já foi baixado com sucesso, ligando cada caminho
local ao ID do arquivo no Drive. Isso permite distinguir três situações que
o nome do arquivo sozinho não diferencia:

- o arquivo foi removido no Drive (o caso que nos interessa)
- o arquivo nunca foi baixado por este agebackup
- o arquivo foi colocado na pasta por você ou por outro programa
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from agebackup import rotacao
from agebackup.falhas import FALHAS_NAME

MANIFEST_NAME = ".agebackup-manifest.json"
REMOCIDOS_NAME = ".agebackup-removidos.log"
MANIFEST_VERSION = 1


@dataclass
class Registro:
    """Uma entrada do manifesto."""

    drive_id: str
    nome: str
    tamanho: int
    modificado: str
    baixado_em: str


def caminho_manifesto(destino: Path) -> Path:
    return destino / MANIFEST_NAME


def caminho_removidos(pasta_logs: Path) -> Path:
    """Caminho do log de remoções dentro da pasta de logs."""
    return pasta_logs / REMOCIDOS_NAME


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def carregar(destino: Path) -> dict[str, Registro]:
    """Lê o manifesto. Devolve um manifesto vazio se não existir ou estiver ruim."""
    arquivo = caminho_manifesto(destino)
    if not arquivo.exists():
        return {}

    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}

    if dados.get("version") != MANIFEST_VERSION:
        return {}

    registros: dict[str, Registro] = {}
    for caminho, item in (dados.get("arquivos") or {}).items():
        try:
            registros[caminho] = Registro(**item)
        except TypeError:
            continue

    return registros


def salvar(destino: Path, registros: dict[str, Registro]) -> bool:
    """Grava o manifesto de forma atômica.

    Devolve False se não conseguiu escrever, sem interromper o backup.
    """
    arquivo = caminho_manifesto(destino)
    parcial = arquivo.with_name(f"{arquivo.name}.tmp")

    try:
        payload = {
            "version": MANIFEST_VERSION,
            "atualizado_em": _agora(),
            "arquivos": {
                caminho: asdict(registro) for caminho, registro in registros.items()
            },
        }
        parcial.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        parcial.replace(arquivo)
    except OSError:
        parcial.unlink(missing_ok=True)
        return False

    return True


def registrar(
    registros: dict[str, Registro],
    caminho_relativo: str,
    drive_id: str,
    nome: str,
    tamanho: int,
    modificado: str,
) -> None:
    """Atualiza ou cria a entrada de um arquivo baixado."""
    registros[caminho_relativo] = Registro(
        drive_id=drive_id,
        nome=nome,
        tamanho=tamanho,
        modificado=modificado,
        baixado_em=_agora(),
    )


def _arquivos_locais(destino: Path) -> set[str]:
    """Lista os arquivos do destino, ignorando os arquivos internos do AgeBackup."""
    encontrados: set[str] = set()

    for caminho in destino.rglob("*"):
        if not caminho.is_file():
            continue
        if caminho.name in (MANIFEST_NAME, REMOCIDOS_NAME):
            continue
        if caminho.suffix == ".tmp" or caminho.name.endswith(".tmp"):
            continue
        # Logs de meses anteriores, comprimidos.
        if caminho.name.startswith(f"{REMOCIDOS_NAME}.") or caminho.name.startswith(
            f"{FALHAS_NAME}."
        ):
            continue
        encontrados.add(str(caminho.relative_to(destino)))

    return encontrados


def detectar_removidos(
    destino: Path,
    registros: dict[str, Registro],
    ids_presents: set[str],
    listagem_completa: bool,
) -> list[str]:
    """Devolve os caminhos locais cujos arquivos sumiram do Drive.

    Só considera arquivos que constam no manifesto. Um arquivo local que o
    agebackup nunca baixou não é considerado remoção: pode ter sido colocado ali
    por você.

    Args:
        destino: pasta local do backup.
        registros: manifesto atual.
        ids_presents: IDs de arquivo vistos na listagem do Drive.
        listagem_completa: False se a listagem foi interrompida por erro. Nesse
            caso não reporta nada, para não marcar em massa como removido o
            que apenas deixou de ser listado.

    Returns:
        Caminhos relativos removidos, em ordem alfabética.
    """
    if not listagem_completa:
        return []

    presentes = _arquivos_locais(destino)
    removidos = {
        caminho
        for caminho, registro in registros.items()
        if registro.drive_id not in ids_presents and caminho in presentes
    }

    return sorted(removidos)


def registrar_removidos(
    pasta_logs: Path,
    removidos: list[str],
    registros: dict[str, Registro],
    rotacionar: bool = False,
) -> Path | None:
    """Acrescenta as remoções ao log e as retira do manifesto.

    Não apaga nenhum arquivo do disco. Devolve o caminho do log, ou None se
    não havia o que registrar.
    """
    if not removidos:
        return None

    log = caminho_removidos(pasta_logs)

    if rotacionar:
        rotacao.rotacionar(log)

    momento = _agora()

    try:
        pasta_logs.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as arquivo:
            for caminho in removidos:
                arquivo.write(f"{momento}\t{caminho}\n")
    except OSError:
        return None

    for caminho in removidos:
        registros.pop(caminho, None)

    return log
