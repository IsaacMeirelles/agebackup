"""Rotação dos logs do AgeBackup, por execução.

Cada execução começa um log novo, com data e hora no nome. A rotação fecha o
log da execução anterior e guarda apenas os mais recentes, para o histórico não
crescer sem limite.

O nome do arquivo da execução corrente é `<nome>.log` (ex.:
`.agebackup-falhas.log`). Na virada, ele vira
`<nome>.<AAAA-MM-DD>-<HHMM>.log.gz` — a data/hora é a da última gravação da
execução anterior — e um `.log` novo começa. Exemplo:

    .agebackup-falhas.log                       # execução em andamento
    .agebackup-falhas.2026-10-21-1842.log.gz    # execução anterior, comprimida
    .agebackup-falhas.2026-10-20-0300.log.gz    # mais antiga, comprimida

A virada é detectada no início de cada execução: a rotação só é chamada antes
de qualquer escrita, então qualquer log encontrado ali pertence à execução
anterior. O selo usado no nome é o mtime desse log, ou seja, o momento em que a
execução anterior gravou pela última vez. Não é preciso criar arquivo de marca
(versões antigas usavam `.agebackup-mes`; ele não é mais lido nem gerado).

A compactação usa gzip, nativo da biblioteca padrão, sem dependências extras.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Nome de um log já fechado: <nome>.<AAAA-MM-DD>-<HHMM>.log.gz
# Também aceita o formato antigo, só com o mês (<nome>.<AAAA-MM>.log.gz), para
# que históricos anteriores continuem sendo lidos e respeitem a retenção.
PADRAO_SELO = re.compile(r"^\d{4}-\d{2}(-\d{2}-\d{4})?$")


def _stamp(momento: datetime) -> str:
    """Selo da execução: data e hora (``2026-10-21-1842``)."""
    return f"{momento:%Y-%m-%d-%H%M}"


def _stamp_mes(momento: datetime) -> str:
    """Selo mensal (``2026-10``), usado só pelo formato antigo."""
    return f"{momento:%Y-%m}"


def caminho_do_mes(log: Path, momento: datetime) -> Path:
    """Nome do arquivo de uma execução específica."""
    return log.with_name(f"{log.name}.{_stamp(momento)}.log")


def caminho_compactado(log: Path, momento: datetime) -> Path:
    """Nome do arquivo comprimido de uma execução específica."""
    return log.with_name(f"{log.name}.{_stamp(momento)}.log.gz")


def selo_do_arquivo(nome: str, nome_log: str) -> str | None:
    """Extrai o selo (``AAAA-MM-DD-HHMM`` ou ``AAAA-MM``) de um log fechado."""
    if not nome.startswith(nome_log + "."):
        return None

    resto = nome[len(nome_log) + 1 :]
    for sufixo in (".log.gz", ".log"):
        if resto.endswith(sufixo):
            selo = resto[: -len(sufixo)]
            return selo if PADRAO_SELO.match(selo) else None
    return None


@dataclass
class ResultadoRotacao:
    """O que a rotação fez."""

    comprimidos: list[Path]
    removidos: list[Path]
    erro: str = ""


def _selo_do_log(log: Path) -> str | None:
    """Selo da execução anterior, tirado do mtime do log corrente."""
    try:
        mtime = log.stat().st_mtime
    except OSError:
        return None
    return _stamp(datetime.fromtimestamp(mtime, tz=UTC))


def _data_do_selo(selo: str) -> datetime | None:
    """Converte o selo em data, para ordenar os logs. None se não reconhecer."""
    formatos = ("%Y-%m-%d-%H%M", "%Y-%m")
    for formato in formatos:
        try:
            return datetime.strptime(selo, formato)
        except ValueError:
            continue
    return None


def arquivados(log: Path) -> list[Path]:
    """Lista os logs já fechados, do mais recente para o mais antigo."""
    encontrados: list[tuple[datetime, Path]] = []
    for arquivo in log.parent.glob(f"{log.name}.*.log.gz"):
        selo = selo_do_arquivo(arquivo.name, log.name)
        if selo is None:
            continue
        quando = _data_do_selo(selo)
        if quando is None:
            continue
        encontrados.append((quando, arquivo))

    encontrados.sort(key=lambda item: item[0], reverse=True)
    return [arquivo for _, arquivo in encontrados]


def aplicar_retencao(
    log: Path,
    manter: int,
    removidos: list[Path],
) -> None:
    """Apaga os logs fechados mais antigos, mantendo os `manter` recentes.

    `manter = 0` significa guardar tudo: nada é removido.
    """
    if manter <= 0:
        return

    arquivos = arquivados(log)
    for antigo in arquivos[manter:]:
        try:
            antigo.unlink()
            removidos.append(antigo)
        except OSError:
            continue


def rotacionar(
    log: Path,
    manter: int = 0,
    comprimir: bool = True,
) -> ResultadoRotacao:
    """Fecha o log da execução anterior e comprime os logs antigos.

    Deve ser chamado no início da execução, antes de escrever no log. Se o
    arquivo existir nesse momento, ele é da execução anterior e vira
    `<nome>.<AAAA-MM-DD>-<HHMM>.log.gz`, com o selo tirado do mtime.

    Com `manter` maior que zero, apaga os logs fechados além dos N mais
    recentes. Idempotente: chamar de novo sem um log corrente não faz nada.

    Args:
        log: caminho do log corrente, ex.: `pasta/.agebackup-falhas.log`.
        manter: quantos logs fechados guardar. 0 guarda todos.
        comprimir: quando False, apenas move o log anterior sem comprimir.

    Returns:
        Lista dos arquivos comprimidos, dos apagados e eventual erro.
    """
    comprimidos: list[Path] = []
    removidos: list[Path] = []
    erro = ""

    try:
        selo_anterior = _selo_do_log(log)
        if selo_anterior is not None:
            fechado = _fechar_execucao(log, selo_anterior)
            if fechado is not None:
                if comprimir:
                    comprimidos.append(_comprimir(fechado))
                else:
                    removidos.append(fechado)

        # Logs de execuções anteriores podem ter ficado soltos (execução
        # anterior falhou). Comprime sempre que encontrar, não só na virada.
        if comprimir:
            _compactar_antigos(log, comprimidos, removidos)

        aplicar_retencao(log, manter, removidos)
    except OSError as exc:
        erro = str(exc)

    return ResultadoRotacao(comprimidos=comprimidos, removidos=removidos, erro=erro)


def _fechar_execucao(log: Path, selo_anterior: str) -> Path | None:
    """Move o conteúdo do log corrente para o arquivo da execução que acabou."""
    if not log.exists():
        return None

    alvo = log.with_name(f"{log.name}.{selo_anterior}.log")

    try:
        if alvo.exists():
            with (
                alvo.open("a", encoding="utf-8") as destino,
                log.open(encoding="utf-8") as origem,
            ):
                shutil.copyfileobj(origem, destino)
            log.unlink()
        else:
            log.replace(alvo)
    except OSError as exc:
        raise OSError(f"não foi possível fechar o log {log.name}: {exc}") from exc

    return alvo


def _compactar_antigos(
    log: Path, comprimidos: list[Path], removidos: list[Path]
) -> None:
    """Comprime os `.log` de execuções anteriores que ainda estão soltos."""
    for candidato in sorted(log.parent.glob(f"{log.name}.*.log")):
        if selo_do_arquivo(candidato.name, log.name) is None:
            continue

        try:
            comprimidos.append(_comprimir(candidato))
        except OSError:
            removidos.append(candidato)


def _comprimir(arquivo: Path) -> Path:
    """Comprime em gzip e remove o original. Devolve o caminho comprimido.

    Se o destino já existir (duas execuções no mesmo minuto), acrescenta um
    novo membro gzip em vez de sobrescrever. O resultado continua legível: o
    gzip e o ``zcat`` leem membros concatenados.
    """
    destino = arquivo.with_name(f"{arquivo.name}.gz")
    parcial = destino.with_name(f"{destino.name}.tmp")

    with arquivo.open("rb") as origem, gzip.open(parcial, "wb") as saida:
        shutil.copyfileobj(origem, saida)

    if destino.exists():
        with destino.open("ab") as saida, parcial.open("rb") as novo:
            shutil.copyfileobj(novo, saida)
        parcial.unlink()
    else:
        os.replace(parcial, destino)
    arquivo.unlink()
    return destino


def mes_do_arquivo(nome: str, nome_log: str) -> str | None:
    """Extrai o selo de um arquivo de log (compatível com o formato antigo)."""
    return selo_do_arquivo(nome, nome_log)
