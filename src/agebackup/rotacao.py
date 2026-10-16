"""Rotação mensal dos logs do AgeBackup.

Cada log segue o padrão `<nome>.AAAA-MM.log` para os meses já fechados e um
arquivo `<nome>.log` para o mês corrente. Quando o mês vira, o arquivo do mês
que acabou é comprimido em `<nome>.AAAA-MM.log.gz` e um novo `.log` começa.

Exemplo do que fica na pasta de logs (por padrão `logs/` dentro do backup):

    .agebackup-falhas.log              # mês corrente, texto
    .agebackup-falhas.2026-09.log.gz   # mês anterior, comprimido
    .agebackup-falhas.2026-08.log.gz   # mais antigo, comprimido

A fronteira entre meses é decidida por um arquivo de marca (`.agebackup-mês`), e
não pelo mtime do log. Isso porque escrever no log no mês corrente atualiza o
mtime e faria um log antigo passar "despercebido", juntando meses distintos no
mesmo arquivo.

A compactação usa gzip, nativo da biblioteca padrão, sem dependências extras.
"""

from __future__ import annotations

import gzip
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MARCA_NAME = ".agebackup-mes"
PADRAO_ARQUIVO = "{nome}.{ano:04d}-{mes:02d}.log"
PADRAO_COMPACTADO = "{nome}.{ano:04d}-{mes:02d}.log.gz"


def _stamp(momento: datetime) -> str:
    return f"{momento.year:04d}-{momento.month:02d}"


def caminho_marca(destino: Path) -> Path:
    return destino / MARCA_NAME


def caminho_do_mes(log: Path, momento: datetime) -> Path:
    """Nome do arquivo de um mês específico."""
    return log.with_name(
        PADRAO_ARQUIVO.format(nome=log.name, ano=momento.year, mes=momento.month)
    )


def caminho_compactado(log: Path, momento: datetime) -> Path:
    """Nome do arquivo comprimido de um mês específico."""
    return log.with_name(
        PADRAO_COMPACTADO.format(nome=log.name, ano=momento.year, mes=momento.month)
    )


@dataclass
class ResultadoRotacao:
    """O que a rotação fez."""

    comprimidos: list[Path]
    removidos: list[Path]
    erro: str = ""


def _ler_marca(destino: Path) -> str | None:
    """Devolve o mês (AAAA-MM) registrado na marca, ou None se não houver."""
    marca = caminho_marca(destino)
    if not marca.exists():
        return None
    try:
        return marca.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _escrever_marca(destino: Path, mes: str) -> None:
    """Registra o mês corrente na marca, de forma atômica."""
    marca = caminho_marca(destino)
    parcial = marca.with_name(f"{marca.name}.tmp")
    try:
        parcial.write_text(mes, encoding="utf-8")
        os.replace(parcial, marca)
    except OSError:
        parcial.unlink(missing_ok=True)


def _mes_para_numero(mes: str) -> int:
    """Converte 'AAAA-MM' em um inteiro ordenável (AAAA * 12 + MM)."""
    ano, mes_numero = (int(parte) for parte in mes.split("-"))
    return ano * 12 + mes_numero


def _mes_de_arquivo(nome: str, nome_log: str) -> str | None:
    """Extrai 'AAAA-MM' do nome de um arquivo de log já comprimido."""
    if not nome.startswith(nome_log):
        return None

    resto = nome[len(nome_log) + 1 :]
    if not resto.endswith(".log.gz"):
        return None

    mes = resto[: -len(".log.gz")]
    partes = mes.split("-")
    if len(partes) == 2 and len(partes[0]) == 4 and len(partes[1]) == 2:
        return mes
    return None


def aplicar_retencao(
    log: Path,
    mes_atual: str,
    meses: int,
    removidos: list[Path],
) -> None:
    """Apaga os arquivos comprimidos mais antigos que o limite de meses.

    `meses = 0` significa guardar tudo: nada é removido.
    """
    if meses <= 0:
        return

    limite = _mes_para_numero(mes_atual) - meses

    if limite <= 0:
        return

    # Trabalha sobre os arquivos comprimidos, que existem mesmo quando o log do
    # mês corrente ainda não foi criado.
    for arquivo in log.parent.glob(f"{log.name}.*.log.gz"):
        mes = _mes_de_arquivo(arquivo.name, log.name)
        if mes is None:
            continue
        if _mes_para_numero(mes) < limite:
            try:
                arquivo.unlink()
                removidos.append(arquivo)
            except OSError:
                continue


def rotacionar(
    log: Path,
    agora: datetime | None = None,
    meses: int = 0,
    comprimir: bool = True,
) -> ResultadoRotacao:
    """Fecha o log do mês anterior e comprime os arquivos antigos.

    Decide a virada comparando o mês atual com o mês registrado na marca.

    Idempotente: chamar várias vezes no mesmo mês não faz nada além do
    necessário.

    Args:
        log: caminho do log corrente, ex.: `pasta/.agebackup-falhas.log`.
        agora: momento de referência. Use o momento atual.
        meses: quantos meses de arquivos comprimidos manter. 0 guarda tudo.
        comprimir: quando False, apenas move o log do mês anterior sem
            comprimir.

    Returns:
        Lista dos arquivos comprimidos, dos apagados e eventual erro.
    """
    momento = agora or datetime.now(UTC)
    mes_atual = _stamp(momento)
    destino = log.parent
    comprimidos: list[Path] = []
    removidos: list[Path] = []
    erro = ""

    try:
        mes_marcado = _ler_marca(destino)

        if mes_marcado is None:
            # Primeira execução: fixa a fronteira sem mover nada.
            _escrever_marca(destino, mes_atual)
        elif mes_marcado != mes_atual:
            fechado = _fechar_mes(log, mes_marcado)
            if fechado is not None:
                if comprimir:
                    comprimidos.append(_comprimir(fechado))
                else:
                    removidos.append(fechado)
            _escrever_marca(destino, mes_atual)

        # Arquivos de meses anteriores podem ter ficado soltos (execução
        # anterior falhou). Comprime sempre que encontrar, não só na virada.
        if comprimir:
            _compactar_antigos(log, mes_atual, comprimidos, removidos)

        aplicar_retencao(log, mes_atual, meses, removidos)
    except OSError as exc:
        erro = str(exc)

    return ResultadoRotacao(comprimidos=comprimidos, removidos=removidos, erro=erro)


def _fechar_mes(log: Path, mes_anterior: str) -> Path | None:
    """Move o conteúdo do log corrente para o arquivo do mês que acabou."""
    if not log.exists():
        return None

    ano, mes = (int(parte) for parte in mes_anterior.split("-"))
    alvo = log.with_name(PADRAO_ARQUIVO.format(nome=log.name, ano=ano, mes=mes))

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
    log: Path, mes_atual: str, comprimidos: list[Path], removidos: list[Path]
) -> None:
    """Comprime os `.log` de meses anteriores que ainda estão soltos."""
    for candidato in sorted(log.parent.glob(f"{log.name}.*.log")):
        try:
            nome = candidato.name
            ano_mes = nome[len(log.name) + 1 : -len(".log")]
            ano, mes = (int(parte) for parte in ano_mes.split("-"))
            if f"{ano:04d}-{mes:02d}" >= mes_atual:
                continue
        except ValueError:
            # Nome inesperado: deixa intacto em vez de arriscar.
            removidos.append(candidato)
            continue

        try:
            comprimidos.append(_comprimir(candidato))
        except OSError as exc:
            removidos.append(candidato)
            _ = exc


def _comprimir(arquivo: Path) -> Path:
    """Comprime em gzip e remove o original. Devolve o caminho comprimido."""
    destino = arquivo.with_name(f"{arquivo.name}.gz")
    parcial = destino.with_name(f"{destino.name}.tmp")

    with arquivo.open("rb") as origem, gzip.open(parcial, "wb") as saida:
        shutil.copyfileobj(origem, saida)

    os.replace(parcial, destino)
    arquivo.unlink()
    return destino


def arquivados(log: Path) -> list[Path]:
    """Lista os arquivos já comprimidos, do mais recente para o mais antigo."""
    return sorted(log.parent.glob(f"{log.name}.*.log.gz"), reverse=True)


def mes_do_arquivo(nome: str, nome_log: str) -> str | None:
    """Extrai `AAAA-MM` do nome de um arquivo de log."""
    if not nome.startswith(nome_log):
        return None

    resto = nome[len(nome_log) + 1 :]
    for sufixo in (".log.gz", ".log"):
        if resto.endswith(sufixo):
            return resto[: -len(sufixo)]
    return None
