"""Compactação do backup em um arquivo .tar.gz.

Junta a pasta do backup inteira em um único arquivo comprimido, gravado no
destino configurado (por padrão, a pasta acima do backup). Serve para guardar
uma cópia fechada em outro disco, levar para a nuvem ou arquivar um retrato do
backup em uma data.

O comando é separado do backup: rode ``agebackup-compactar`` quando quiser, por
exemplo depois do backup ou por um agendador.

O nome gerado é ``<pasta>_AAAAMMDD.tar.gz``. Um prefixo opcional (da
configuração ou de ``--prefixo``) entra antes da data:
``<pasta>_<prefixo>_AAAAMMDD.tar.gz``. A gravação é atômica:
escreve um ``.tmp`` e só então renomeia, para não deixar um arquivo pela metade
se algo falhar no meio.

A compactação usa ``tarfile`` com gzip, nativo da biblioteca padrão, sem
dependências extras.
"""

from __future__ import annotations

import os
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agebackup.backup import carregar_configuracao
from agebackup.config import (
    MANTER_MAXIMO,
    MANTER_MINIMO,
    MANTER_PADRAO,
    ConfigError,
    ajustar_prefixo_compactacao,
)
from agebackup.verificacao import SUFIXO_TMP

LIMITE_MOSTRADOS = 20


@dataclass
class ResultadoCompactacao:
    """O que a compactação fez."""

    arquivo: Path | None = None
    itens: int = 0
    bytes_total: int = 0
    removidos: list[Path] = field(default_factory=list)
    erro: str = ""


def _data(momento: datetime) -> str:
    return f"{momento:%Y%m%d}"


def _nome_arquivo(base: str, prefixo: str, momento: datetime) -> str:
    """Monta o nome do arquivo compactado.

    Com prefixo: ``<base>_<prefixo>_AAAAMMDD.tar.gz``. Sem prefixo (vazio):
    ``<base>_AAAAMMDD.tar.gz``.
    """
    partes = [base]
    if prefixo:
        partes.append(prefixo)
    partes.append(_data(momento))
    return "_".join(partes) + ".tar.gz"


def _dentro(caminho: Path, pasta: Path) -> bool:
    """Diz se `caminho` fica dentro de `pasta` (ou é a própria pasta)."""
    try:
        return caminho.resolve().is_relative_to(pasta.resolve())
    except OSError:
        return False


def _contar(origem: Path) -> tuple[int, int]:
    """Conta arquivos (fora os `.tmp` residuais) e o total em bytes."""
    itens = 0
    total = 0
    for raiz, _pastas, arquivos in os.walk(origem):
        for nome in arquivos:
            if nome.endswith(SUFIXO_TMP):
                continue
            try:
                total += (Path(raiz) / nome).stat().st_size
            except OSError:
                continue
            itens += 1
    return itens, total


def _sem_temporarios(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Exclui do arquivo compactado os `.tmp` de execuções interrompidas."""
    return None if info.name.endswith(SUFIXO_TMP) else info


def _aplicar_retencao(destino_dir: Path, base: str, manter: int) -> list[Path]:
    """Apaga os arquivos mais antigos, mantendo os `manter` mais recentes.

    `manter = 0` significa guardar todos: nada é removido. O nome inclui a data
    (AAAAMMDD), então a ordem alfabética já é a ordem cronológica.
    """
    if manter <= 0:
        return []

    arquivos = sorted(destino_dir.glob(f"{base}_*.tar.gz"))
    removidos: list[Path] = []
    for antigo in arquivos[: max(0, len(arquivos) - manter)]:
        try:
            antigo.unlink()
            removidos.append(antigo)
        except OSError:
            continue
    return removidos


def arquivos_compactados(destino_dir: Path, base: str | None = None) -> list[Path]:
    """Lista os arquivos compactados, do mais recente para o mais antigo."""
    padrao = f"{base}_*.tar.gz" if base else "*.tar.gz"
    return sorted(destino_dir.glob(padrao), reverse=True)


def compactar(
    origem: Path,
    destino_dir: Path,
    *,
    nome: str | None = None,
    manter: int = MANTER_PADRAO,
    prefixo: str = "",
    dry_run: bool = False,
) -> ResultadoCompactacao:
    """Compacta `origem` em um `.tar.gz` dentro de `destino_dir`.

    Args:
        origem: pasta do backup a compactar.
        destino_dir: pasta onde o arquivo é gravado. Não pode ficar dentro de
            `origem`, senão o próprio arquivo entraria no backup.
        nome: base do nome do arquivo. Padrão: o nome da pasta de origem.
        manter: quantos arquivos guardar. 0 guarda todos.
        prefixo: texto opcional entre o nome e a data
            (``<nome>_<prefixo>_AAAAMMDD.tar.gz``). Vazio não muda o nome.
        dry_run: quando True, só calcula o que seria feito.

    Returns:
        O caminho gerado, as contagens e eventual erro.
    """
    resultado = ResultadoCompactacao()

    origem = Path(origem).expanduser()
    if not origem.is_dir():
        resultado.erro = f"pasta de origem nao encontrada: {origem}"
        return resultado

    destino_dir = Path(destino_dir).expanduser()
    if _dentro(destino_dir, origem):
        resultado.erro = (
            "a pasta de destino dos arquivos compactados nao pode ficar "
            f"dentro do backup ({origem})"
        )
        return resultado

    base = nome or origem.name
    prefixo = ajustar_prefixo_compactacao(prefixo)
    alvo = destino_dir / _nome_arquivo(base, prefixo, datetime.now())
    resultado.itens, resultado.bytes_total = _contar(origem)

    if dry_run:
        resultado.arquivo = alvo
        return resultado

    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        resultado.erro = f"nao foi possivel criar {destino_dir}: {error}"
        return resultado

    parcial = destino_dir / f".{alvo.name}{SUFIXO_TMP}"
    try:
        with tarfile.open(parcial, "w:gz") as pacote:
            pacote.add(origem, arcname=origem.name, filter=_sem_temporarios)
        os.replace(parcial, alvo)
    except OSError, tarfile.TarError:
        parcial.unlink(missing_ok=True)
        resultado.erro = f"falha ao compactar: {alvo.name}"
        return resultado

    resultado.arquivo = alvo
    resultado.removidos = _aplicar_retencao(destino_dir, base, manter)
    return resultado


def _titulo(texto: str) -> None:
    print(f"\n{'=' * 62}\n  {texto}\n{'=' * 62}")


def _valor(args: list[str], nome: str) -> str | None:
    """Devolve o valor de uma opção `--nome valor`, se presente."""
    if nome not in args:
        return None
    indice = args.index(nome)
    return args[indice + 1] if indice + 1 < len(args) else None


def _ajuda() -> int:
    """Mostra a ajuda do comando."""
    _titulo("agebackup-compactar - ajuda")
    print(
        "  Uso: agebackup-compactar [opcoes]\n\n"
        "    (sem opcoes)   Compacta o backup em <pasta>_AAAAMMDD.tar.gz\n"
        "    --destino P    Grava em P (padrao: o configurado, ou a pasta acima do backup)\n"
        "    --manter N     Guarda apenas os N arquivos mais recentes (0 = todos)\n"
        "    --prefixo X    Texto entre a pasta e a data (<pasta>_X_AAAAMMDD.tar.gz)\n"
        "    --listar       Lista os arquivos de compactacao ja gerados\n"
        "    --dry-run      Simula, sem gravar nada\n"
        "    -h, --help     Mostra esta ajuda"
    )
    return 0


def _listar(config, destino_backup: Path) -> int:
    """Lista os arquivos de compactação já gerados."""
    destino_dir = config.compactacao.pasta(destino_backup)
    arquivos = arquivos_compactados(destino_dir)

    _titulo("Arquivos compactados")
    print(f"  Pasta: {destino_dir}")

    if not arquivos:
        print("\n  Nenhum arquivo ainda. Gere o primeiro com: agebackup-compactar")
        return 0

    for arquivo in arquivos[:LIMITE_MOSTRADOS]:
        tamanho = arquivo.stat().st_size / (1024 * 1024)
        print(f"    {arquivo.name}  ({tamanho:.1f} MB)")

    if len(arquivos) > LIMITE_MOSTRADOS:
        print(f"    ... e mais {len(arquivos) - LIMITE_MOSTRADOS}.")

    print(f"\n  Total: {len(arquivos)} arquivo(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da compactação do backup."""
    args = list(sys.argv[1:] if argv is None else argv)

    if "--help" in args or "-h" in args:
        return _ajuda()

    try:
        config = carregar_configuracao()
    except ConfigError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    destino_backup = Path(config.backup.destination).expanduser()

    if "--listar" in args:
        return _listar(config, destino_backup)

    extra = _valor(args, "--destino")
    destino_dir = (
        Path(extra).expanduser() if extra else config.compactacao.pasta(destino_backup)
    )

    manter = config.compactacao.manter
    manter_texto = _valor(args, "--manter")
    if manter_texto is not None:
        try:
            manter = max(MANTER_MINIMO, min(MANTER_MAXIMO, int(manter_texto)))
        except ValueError:
            print(f"  --manter espera um numero: {manter_texto!r}", file=sys.stderr)
            return 1

    dry_run = "--dry-run" in args

    prefixo = config.compactacao.prefixo
    prefixo_texto = _valor(args, "--prefixo")
    if prefixo_texto is not None:
        prefixo = ajustar_prefixo_compactacao(prefixo_texto)
        if prefixo_texto.strip() and not prefixo:
            print(
                f"  --prefixo invalido (use um nome sem / ou \\): {prefixo_texto!r}",
                file=sys.stderr,
            )
            return 1

    if not destino_backup.is_dir():
        print(f"  ERRO: backup nao encontrado em {destino_backup}", file=sys.stderr)
        return 1

    _titulo("Compactar backup")
    print(f"  Origem   : {destino_backup}")
    print(f"  Destino  : {destino_dir}")
    print(f"  Retencao : {'guardar todos' if manter <= 0 else f'{manter} arquivo(s)'}")
    if prefixo:
        print(f"  Prefixo  : {prefixo}")
    print(f"  Modo     : {'simulacao (nada sera gravado)' if dry_run else 'real'}")

    resultado = compactar(
        destino_backup, destino_dir, manter=manter, prefixo=prefixo, dry_run=dry_run
    )

    if resultado.erro:
        print(f"\n  ERRO: {resultado.erro}", file=sys.stderr)
        return 1

    if dry_run:
        print(
            f"\n  Seriam compactados {resultado.itens} arquivo(s) em "
            f"{resultado.arquivo}."
        )
        print("  Simulacao: nenhum arquivo foi gravado.")
        return 0

    tamanho = resultado.arquivo.stat().st_size / (1024 * 1024)
    print(f"\n  Arquivo  : {resultado.arquivo}")
    print(f"  Tamanho  : {tamanho:.1f} MB")
    print(f"  Conteudo : {resultado.itens} arquivo(s)")

    if resultado.removidos:
        print(f"  Removidos: {len(resultado.removidos)} arquivo(s) antigo(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
