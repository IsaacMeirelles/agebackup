"""Compactação do backup em um arquivo .tar.gz.

Junta a pasta do backup inteira em um único arquivo comprimido, gravado no
destino configurado (por padrão, a pasta acima do backup). Serve para guardar
uma cópia fechada em outro disco, levar para a nuvem ou arquivar um retrato do
backup em uma data.

O comando é separado do backup: rode ``agebackup-compactar`` quando quiser, por
exemplo depois do backup ou por um agendador.

O nome gerado é ``<pasta>_AAAAMMDD-HHMM.tar.gz``. Um prefixo opcional (da
configuração ou de ``--prefixo``) entra antes da data:
``<pasta>_<prefixo>_AAAAMMDD-HHMM.tar.gz``. A gravação é atômica:
escreve um ``.tmp`` e só então renomeia, para não deixar um arquivo pela metade
se algo falhar no meio.

A compactação usa ``tarfile`` com gzip, nativo da biblioteca padrão, sem
dependências extras.
"""

from __future__ import annotations

import json
import os
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

# Tipos de compactação.
TIPO_FULL = "full"
TIPO_INCREMENTAL = "incremental"

# Marca entre o prefixo e a data no arquivo incremental. Fica antes da data para
# que o nome continue ordenável e a retenção (`<base>_*.tar.gz`) alcance os dois
# tipos.
MARCA_INCREMENTAL = "inc"

# Estado da compactação: guarda quando foi o último full, para decidir se a
# próxima execução é full (primeira da semana) ou incremental.
ESTADO_NAME = ".agebackup-compactacao.json"
ESTADO_VERSION = 1


@dataclass
class ResultadoCompactacao:
    """O que a compactação fez."""

    arquivo: Path | None = None
    itens: int = 0
    bytes_total: int = 0
    removidos: list[Path] = field(default_factory=list)
    erro: str = ""
    tipo: str = TIPO_FULL
    # Arquivo do full que serve de base para um incremental (vazio num full).
    base: Path | None = None


def _data(momento: datetime) -> str:
    return f"{momento:%Y%m%d-%H%M}"


def _nome_arquivo(
    base: str, prefixo: str, momento: datetime, tipo: str = TIPO_FULL
) -> str:
    """Monta o nome do arquivo compactado.

    Com prefixo: ``<base>_<prefixo>_AAAAMMDD-HHMM.tar.gz``. Sem prefixo (vazio):
    ``<base>_AAAAMMDD-HHMM.tar.gz``. Um incremental ganha a marca ``inc`` logo
    antes da data: ``<base>[_<prefixo>]_inc_AAAAMMDD-HHMM.tar.gz``.
    """
    partes = [base]
    if prefixo:
        partes.append(prefixo)
    if tipo == TIPO_INCREMENTAL:
        partes.append(MARCA_INCREMENTAL)
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


def _tamanho(caminho: Path) -> int:
    """Tamanho em bytes, ou 0 se não der para ler."""
    try:
        return caminho.stat().st_size
    except OSError:
        return 0


def caminho_estado(destino_dir: Path) -> Path:
    """Caminho do arquivo de estado da compactação."""
    return destino_dir / ESTADO_NAME


def _ler_estado(destino_dir: Path) -> dict:
    """Lê o estado da compactação. Vazio se não existir ou estiver ruim."""
    arquivo = caminho_estado(destino_dir)
    if not arquivo.exists():
        return {}
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}
    if dados.get("version") != ESTADO_VERSION:
        return {}
    return dados


def _escrever_estado(destino_dir: Path, dados: dict) -> None:
    """Grava o estado da compactação, de forma atômica."""
    arquivo = caminho_estado(destino_dir)
    parcial = arquivo.with_name(f"{arquivo.name}{SUFIXO_TMP}")
    corpo = {"version": ESTADO_VERSION, **dados}
    try:
        parcial.write_text(
            json.dumps(corpo, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(parcial, arquivo)
    except OSError:
        parcial.unlink(missing_ok=True)


def _semana_de(momento: datetime) -> tuple[int, int]:
    """Ano e semana ISO (segunda a domingo) de um momento."""
    iso = momento.isocalendar()
    return iso.year, iso.week


def decidir_tipo(destino_dir: Path, agora: datetime) -> tuple[str, Path | None]:
    """Decide se a próxima compactação é full ou incremental.

    É full quando não há estado, quando o último full foi numa semana ISO
    diferente da atual, ou quando o arquivo do último full não existe mais
    (apagado pela retenção). Nos demais casos é incremental, usando o full mais
    recente como base.

    Returns:
        O tipo (`"full"` ou `"incremental"`) e o arquivo base (None num full).
    """
    estado = _ler_estado(destino_dir)
    registrado = estado.get("ultimo_full")
    semana = estado.get("semana")
    arquivo = Path(registrado) if registrado else None

    if not registrado or not arquivo or not arquivo.exists():
        return TIPO_FULL, None

    if tuple(semana) != _semana_de(agora):
        return TIPO_FULL, None

    return TIPO_INCREMENTAL, arquivo


def _modificados_desde(origem: Path, momento: datetime) -> list[Path]:
    """Lista os arquivos (fora `.tmp`) modificados depois de `momento`."""
    limite = momento.timestamp()
    encontrados: list[Path] = []
    for raiz, _pastas, arquivos in os.walk(origem):
        for nome in arquivos:
            if nome.endswith(SUFIXO_TMP):
                continue
            caminho = Path(raiz) / nome
            try:
                if caminho.stat().st_mtime > limite:
                    encontrados.append(caminho)
            except OSError:
                continue
    return sorted(encontrados)


def _sem_temporarios(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Exclui do arquivo compactado os `.tmp` de execuções interrompidas."""
    return None if info.name.endswith(SUFIXO_TMP) else info


def _aplicar_retencao(destino_dir: Path, base: str, manter: int) -> list[Path]:
    """Apaga os arquivos mais antigos, mantendo os `manter` mais recentes.

    `manter = 0` significa guardar todos: nada é removido. O nome inclui a data
    (AAAAMMDD-HHMM), então a ordem alfabética já é a ordem cronológica.
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
    tipo: str = TIPO_FULL,
    base: Path | None = None,
    agora: datetime | None = None,
) -> ResultadoCompactacao:
    """Compacta `origem` em um `.tar.gz` dentro de `destino_dir`.

    Um **full** (`tipo="full"`) guarda a pasta inteira. Um **incremental**
    (`tipo="incremental"`) guarda só os arquivos modificados depois de `base`
    (o full da semana): para recompor, extraia o full e depois o incremental por
    cima. O estado do full mais recente é gravado em
    `destino_dir/.agebackup-compactacao.json`, base para a decisão automática de
    `decidir_tipo`.

    Args:
        origem: pasta do backup a compactar.
        destino_dir: pasta onde o arquivo é gravado. Não pode ficar dentro de
            `origem`, senão o próprio arquivo entraria no backup.
        nome: base do nome do arquivo. Padrão: o nome da pasta de origem.
        manter: quantos arquivos guardar. 0 guarda todos.
        prefixo: texto opcional entre o nome e a data
            (``<nome>_<prefixo>_AAAAMMDD-HHMM.tar.gz``). Vazio não muda o nome.
        dry_run: quando True, só calcula o que seria feito.
        tipo: `"full"` (pasta inteira) ou `"incremental"` (só o que mudou).
        base: arquivo do full de referência, para o incremental. A data de
            modificação dele define o corte.
        agora: momento de referência do nome e do estado. Use o momento atual.

    Returns:
        O caminho gerado, as contagens e eventual erro.
    """
    resultado = ResultadoCompactacao(tipo=tipo, base=base)

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

    if tipo == TIPO_INCREMENTAL:
        if base is None:
            resultado.erro = "compactacao incremental sem full de referencia"
            return resultado
        try:
            corte = datetime.fromtimestamp(base.stat().st_mtime, tz=UTC)
        except OSError as error:
            resultado.erro = f"nao foi possivel ler o full de referencia: {error}"
            return resultado

    momento = agora or datetime.now()
    base_nome = nome or origem.name
    prefixo = ajustar_prefixo_compactacao(prefixo)

    if tipo == TIPO_INCREMENTAL:
        arquivos = _modificados_desde(origem, corte)
        resultado.itens = len(arquivos)
        resultado.bytes_total = sum(_tamanho(arquivo) for arquivo in arquivos)
    else:
        arquivos = []
        resultado.itens, resultado.bytes_total = _contar(origem)

    alvo = destino_dir / _nome_arquivo(base_nome, prefixo, momento, tipo)
    resultado.arquivo = alvo

    if dry_run:
        return resultado

    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        resultado.erro = f"nao foi possivel criar {destino_dir}: {error}"
        return resultado

    parcial = destino_dir / f".{alvo.name}{SUFIXO_TMP}"
    try:
        with tarfile.open(parcial, "w:gz") as pacote:
            if tipo == TIPO_INCREMENTAL:
                for arquivo in arquivos:
                    relativo = arquivo.relative_to(origem)
                    pacote.add(
                        arquivo,
                        arcname=str(Path(origem.name) / relativo),
                        filter=_sem_temporarios,
                    )
            else:
                pacote.add(origem, arcname=origem.name, filter=_sem_temporarios)
        os.replace(parcial, alvo)
    except OSError, tarfile.TarError:
        parcial.unlink(missing_ok=True)
        resultado.erro = f"falha ao compactar: {alvo.name}"
        return resultado

    if tipo == TIPO_FULL:
        _escrever_estado(
            destino_dir,
            {
                "ultimo_full": str(alvo),
                "semana": list(_semana_de(momento)),
                "quando": momento.isoformat(timespec="seconds"),
            },
        )

    resultado.removidos = _aplicar_retencao(destino_dir, base_nome, manter)
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
        "    (sem opcoes)   Compacta o backup em <pasta>_AAAAMMDD-HHMM.tar.gz.\n"
        "                   A primeira da semana e full; as demais, incrementais\n"
        "    --full         Forca a compactacao full (pasta inteira)\n"
        "    --incremental  Forca a incremental (so o que mudou desde o full)\n"
        "    --destino P    Grava em P (padrao: o configurado, ou a pasta acima do backup)\n"
        "    --manter N     Guarda apenas os N arquivos mais recentes (0 = todos)\n"
        "    --prefixo X    Texto entre a pasta e a data (<pasta>_X_AAAAMMDD-HHMM.tar.gz)\n"
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

    # Tipo: a primeira compactacao da semana e full, as demais incrementais.
    # --full e --incremental forcam um dos dois.
    agora = datetime.now()
    if "--full" in args:
        tipo, base = TIPO_FULL, None
    elif "--incremental" in args:
        tipo, base = decidir_tipo(destino_dir, agora)
        if tipo != TIPO_INCREMENTAL:
            print(
                "  ERRO: nao ha full desta semana para servir de base ao "
                "incremental; rode sem --incremental para gerar o full.",
                file=sys.stderr,
            )
            return 1
    else:
        tipo, base = decidir_tipo(destino_dir, agora)

    _titulo("Compactar backup")
    print(f"  Origem   : {destino_backup}")
    print(f"  Destino  : {destino_dir}")
    print(f"  Tipo     : {tipo}")
    if tipo == TIPO_INCREMENTAL and base is not None:
        print(f"  Base     : {base.name}")
    print(f"  Retencao : {'guardar todos' if manter <= 0 else f'{manter} arquivo(s)'}")
    if prefixo:
        print(f"  Prefixo  : {prefixo}")
    print(f"  Modo     : {'simulacao (nada sera gravado)' if dry_run else 'real'}")

    resultado = compactar(
        destino_backup,
        destino_dir,
        manter=manter,
        prefixo=prefixo,
        dry_run=dry_run,
        tipo=tipo,
        base=base,
        agora=agora,
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
    print(f"  Tipo     : {resultado.tipo}")
    print(f"  Tamanho  : {tamanho:.1f} MB")
    print(f"  Conteudo : {resultado.itens} arquivo(s)")

    if resultado.removidos:
        print(f"  Removidos: {len(resultado.removidos)} arquivo(s) antigo(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
