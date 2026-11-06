"""Rotina de cópia do backup local para destinos secundários.

Camada 2 do backup: lê a pasta do backup (o destino do Google Drive) e grava
snapshots completos em um ou mais destinos próprios — outro disco ou uma
unidade de rede já montada (ex.: ``/mnt/nas``).

Cada execução cria um snapshot completo (árvore espelho da fonte):

- ``full``: copia todos os arquivos do zero. Ponto no tempo independente.
- ``incremental``: arquivos inalterados desde o último snapshot viram
  hardlinks; só os novos/alterados são copiados.
- ``diferencial``: o mesmo, mas a âncora é o último ``full``.

Os hardlinks são feitos sempre dentro do destino (destino → destino), então
funcionam mesmo quando a fonte está em outro sistema de arquivos. Nada é
apagado durante uma execução: a retenção é o único ponto que remove snapshots
antigos, e apagar um snapshot nunca corrompe os outros (o inode sobrevive
enquanto algum hardlink para ele existir).
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agebackup.backup import carregar_configuracao, formatar_bytes
from agebackup.config import (
    Config,
    ConfigError,
    DestinoRotinaConfig,
    ManterRotinaConfig,
)
from agebackup.verificacao import SUFIXO_TMP

# Pasta (na fonte) com o estado da rotina. Fica fora dos snapshots.
ROTINA_DIR = ".agebackup-rotina"

# Sufixo curto que entra no nome do diretório de cada snapshot.
SUFIXO_RUN = {"full": "full", "incremental": "inc", "diferencial": "dif"}
TIPO_POR_SUFIXO = {sufixo: tipo for tipo, sufixo in SUFIXO_RUN.items()}

# AAAA-MM-DDTHHMMSS-<tipo>[-<n>]  (o sufixo numérico evita colisão na mesma
# segundo, comum em testes e em execuções encadeadas).
PADRAO_RUN = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{6})-(full|inc|dif)(?:-\d+)?$")

# Erros que significam "este sistema de arquivos não faz hardlink". Nesses
# casos o snapshot continua correto, mas os inalterados são copiados.
ERROS_SEM_LINK = {
    errno.EXDEV,
    errno.EPERM,
    errno.EOPNOTSUPP,
    errno.ENOSYS,
    errno.EMLINK,
}


@dataclass
class Fonte:
    """Retrato da fonte no início da execução."""

    arquivos: dict[str, tuple[int, int]] = field(default_factory=dict)
    pastas: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)


@dataclass
class Contadores:
    """O que aconteceu (ou aconteceria) em um destino."""

    arquivos: int = 0
    pastas: int = 0
    copiados: int = 0
    ligados: int = 0
    bytes_copiados: int = 0
    sem_link: bool = False


def _titulo(texto: str) -> None:
    print(f"\n{'=' * 62}\n  {texto}\n{'=' * 62}")


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def varrer_fonte(fonte: Path) -> Fonte:
    """Lista arquivos e pastas da fonte, com (tamanho, mtime_ns) de cada um.

    Ficam de fora a pasta de estado da própria rotina (só na raiz) e os parciais
    ``*.tmp`` — mas apenas quando o arquivo final já existe ao lado; um arquivo
    legítimo terminado em ``.tmp`` (vindo do Drive) continua entrando. O
    manifesto e os logs entram: o snapshot fica restaurável e auto-descritivo.

    O que não puder ser lido com segurança (permissão, link simbólico de pasta)
    vira item de ``erros`` em vez de ser omitido em silêncio — o chamador deve
    abortar em vez de gravar um snapshot incompleto.
    """
    dados = Fonte()

    def registrar_erro(erro: OSError) -> None:
        dados.erros.append(f"{erro.filename or '?'}: {erro.strerror}")

    for raiz, pastas, nomes in os.walk(fonte, onerror=registrar_erro):
        rel_raiz = Path(raiz).relative_to(fonte)
        reais = []

        for nome in sorted(pastas):
            if nome == ROTINA_DIR and not rel_raiz.parts:
                continue
            caminho = Path(raiz) / nome
            if caminho.is_symlink():
                dados.erros.append(f"{caminho}: link simbolico de pasta nao e copiado")
                continue
            reais.append(nome)
        pastas[:] = reais

        if rel_raiz.parts:
            dados.pastas.append(rel_raiz.as_posix())

        conjunto = set(nomes)
        for nome in sorted(nomes):
            if nome.endswith(SUFIXO_TMP) and nome[: -len(SUFIXO_TMP)] in conjunto:
                # Resto de download interrompido: o arquivo final está ao lado.
                continue
            caminho = Path(raiz) / nome
            try:
                info = caminho.stat()
            except OSError as erro:
                dados.erros.append(f"{caminho}: {erro.strerror}")
                continue
            dados.arquivos[(rel_raiz / nome).as_posix()] = (
                info.st_size,
                info.st_mtime_ns,
            )

    return dados


def _runs(destino: Path) -> list[tuple[str, str, Path]]:
    """Snapshots existentes no destino, do mais antigo para o mais novo."""
    try:
        entradas = sorted(destino.iterdir())
    except OSError:
        return []

    runs: list[tuple[str, str, Path]] = []
    for item in entradas:
        if item.name.startswith(".") or not item.is_dir():
            continue
        casou = PADRAO_RUN.match(item.name)
        if not casou:
            continue
        runs.append((item.name, TIPO_POR_SUFIXO[casou.group(2)], item))
    return runs


def escolher_ancora(destino: Path, tipo: str) -> Path | None:
    """Snapshot usado como referência de hardlink para o tipo pedido."""
    if tipo == "full":
        return None

    runs = _runs(destino)
    candidatos = runs if tipo == "incremental" else [r for r in runs if r[1] == "full"]
    return candidatos[-1][2] if candidatos else None


def _mesmo_arquivo(caminho: Path, tamanho: int, mtime_ns: int) -> bool:
    """True se o arquivo existe com exatamente o mesmo tamanho e mtime."""
    try:
        info = caminho.stat()
    except OSError:
        return False
    return info.st_size == tamanho and info.st_mtime_ns == mtime_ns


def _ligar(origem: Path, alvo: Path) -> bool:
    """Tenta criar um hardlink. False quando o sistema de arquivos não suporta."""
    try:
        os.link(origem, alvo)
        return True
    except OSError as erro:
        if erro.errno in ERROS_SEM_LINK:
            return False
        raise


def _copiar(origem: Path, alvo: Path) -> None:
    """Copia preservando o mtime, com nome parcial e troca atômica."""
    parcial = alvo.with_name(alvo.name + SUFIXO_TMP)
    shutil.copy2(origem, parcial)
    os.replace(parcial, alvo)


def montar_snapshot(
    fonte: Path,
    dados: Fonte,
    run_dir: Path,
    ancora: Path | None,
    *,
    simular: bool = False,
) -> Contadores:
    """Cria (ou simula) a árvore do snapshot reaproveitando o que está na âncora."""
    contagem = Contadores(arquivos=len(dados.arquivos), pastas=len(dados.pastas))

    if not simular:
        run_dir.mkdir(parents=True, exist_ok=True)
        for rel in dados.pastas:
            (run_dir / rel).mkdir(parents=True, exist_ok=True)

    for rel, (tamanho, mtime_ns) in dados.arquivos.items():
        alvo = run_dir / rel
        anterior = ancora / rel if ancora is not None else None

        if (
            anterior is not None
            and not contagem.sem_link
            and _mesmo_arquivo(anterior, tamanho, mtime_ns)
        ):
            if simular or _ligar(anterior, alvo):
                contagem.ligados += 1
                continue
            contagem.sem_link = True

        contagem.copiados += 1
        contagem.bytes_copiados += tamanho
        if not simular:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            _copiar(fonte / rel, alvo)

    return contagem


def limpar_temporarios(destino: Path) -> list[str]:
    """Remove restos de execuções interrompidas (``.<run>.tmp``)."""
    removidos: list[str] = []
    padrao = re.compile(r"^\.\d{4}-\d{2}-\d{2}T\d{6}-(full|inc|dif)(?:-\d+)?\.tmp$")

    try:
        entradas = list(destino.iterdir())
    except OSError:
        return removidos

    for item in entradas:
        if not padrao.match(item.name):
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removidos.append(item.name)
    return removidos


def aplicar_retencao(destino: Path, manter: ManterRotinaConfig) -> list[str]:
    """Apaga os snapshots mais antigos que excedem o limite de cada tipo.

    ``0`` significa "guardar todos". Apagar um snapshot é seguro: os arquivos
    que ele emprestava a outros snapshots continuam vivos nos hardlinks deles.
    """
    limites = {
        "full": manter.full,
        "incremental": manter.incremental,
        "diferencial": manter.diferencial,
    }

    por_tipo: dict[str, list[tuple[str, str, Path]]] = {}
    for run in _runs(destino):
        por_tipo.setdefault(run[1], []).append(run)

    removidos: list[str] = []
    for tipo, runs in por_tipo.items():
        limite = limites[tipo]
        if limite <= 0 or len(runs) <= limite:
            continue
        for run_id, _, caminho in runs[: len(runs) - limite]:
            shutil.rmtree(caminho)
            removidos.append(run_id)
    return removidos


def prever_retencao(destino: Path, manter: ManterRotinaConfig, tipo: str) -> list[str]:
    """Snapshots que a retenção removeria se um run de ``tipo`` fosse criado."""
    limites = {
        "full": manter.full,
        "incremental": manter.incremental,
        "diferencial": manter.diferencial,
    }

    por_tipo: dict[str, list[tuple[str, str, Path]]] = {}
    for run in _runs(destino):
        por_tipo.setdefault(run[1], []).append(run)

    removidos: list[str] = []
    for atual, runs in por_tipo.items():
        total = len(runs) + (1 if atual == tipo else 0)
        limite = limites[atual]
        if limite <= 0 or total <= limite:
            continue
        removidos.extend(run_id for run_id, _, _ in runs[: total - limite])
    return removidos


def _slug(nome: str) -> str:
    """Nome de arquivo seguro para o estado de um destino."""
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "_", nome).strip("._")
    return limpo or "destino"


def _validar_destinos(destinos: list[DestinoRotinaConfig]) -> str:
    """Confere que cada destino tem um estado próprio (nome não repetido)."""
    vistos: dict[str, str] = {}
    for destino in destinos:
        nome = destino.nome or destino.caminho
        chave = _slug(nome)
        if chave in vistos:
            return (
                f"destinos com o mesmo nome/estado: {vistos[chave]!r} e {nome!r}; "
                "renomeie um deles"
            )
        vistos[chave] = nome
    return ""


def caminho_estado(fonte: Path, nome_destino: str) -> Path:
    """Arquivo de estado do destino, dentro da pasta da rotina."""
    return fonte / ROTINA_DIR / f"estado-{_slug(nome_destino)}.json"


def carregar_estado(fonte: Path, nome_destino: str) -> dict:
    """Lê o estado do destino. Devolve {} se não existir ou estiver ruim."""
    arquivo = caminho_estado(fonte, nome_destino)
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}
    if not isinstance(dados, dict) or dados.get("versao") != 1:
        return {}
    return dados


def salvar_estado(
    fonte: Path,
    nome_destino: str,
    destino: Path,
    registro: dict | None,
) -> Path:
    """Grava o estado de forma atômica, reconstruindo a lista a partir do disco.

    Os snapshots podados somem do estado; os que continuam mantêm os
    contadores já conhecidos.
    """
    anterior = carregar_estado(fonte, nome_destino)
    conhecidos: dict[str, dict] = {}
    for item in anterior.get("runs") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            conhecidos[item["id"]] = item
    if registro is not None:
        conhecidos[registro["id"]] = registro

    runs = []
    for run_id, tipo, _ in _runs(destino):
        item = dict(conhecidos.get(run_id) or {})
        item["id"] = run_id
        item["tipo"] = tipo
        runs.append(item)

    dados = {
        "versao": 1,
        "destino": str(destino),
        "atualizado_em": _agora(),
        "runs": runs,
        "ultimo_full": next(
            (item["id"] for item in reversed(runs) if item["tipo"] == "full"), ""
        ),
        "ultimo_run": runs[-1]["id"] if runs else "",
    }

    pasta = fonte / ROTINA_DIR
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = caminho_estado(fonte, nome_destino)
    parcial = arquivo.with_name(arquivo.name + SUFIXO_TMP)
    parcial.write_text(
        json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(parcial, arquivo)
    return arquivo


def _novo_run_id(destino: Path, tipo: str, momento: datetime) -> str:
    """Nome do snapshot, com sufixo numérico se já existir no mesmo segundo."""
    base = f"{momento:%Y-%m-%dT%H%M%S}-{SUFIXO_RUN[tipo]}"
    if not (destino / base).exists():
        return base

    numero = 2
    while (destino / f"{base}-{numero}").exists():
        numero += 1
    return f"{base}-{numero}"


def _dentro_da_fonte(fonte: Path, destino: Path) -> bool:
    """True se o destino está dentro da fonte (ou é a própria fonte)."""
    try:
        fonte = fonte.resolve()
        destino = destino.resolve()
    except OSError:
        return False
    return destino == fonte or fonte in destino.parents


def _descrever(contagem: Contadores) -> str:
    partes = [
        f"{contagem.arquivos} arquivo(s)",
        f"{contagem.copiados} copiado(s) ({formatar_bytes(contagem.bytes_copiados)})",
        f"{contagem.ligados} ligado(s)",
    ]
    return ", ".join(partes)


def executar_rotina(
    config: Config,
    tipo: str,
    nome_destino: str = "",
    *,
    dry_run: bool = False,
) -> int:
    """Executa a rotina nos destinos configurados. Devolve o código de saída."""
    fonte = Path(config.backup.destination).expanduser()
    if not fonte.is_dir():
        print(f"  ERRO: backup nao encontrado em {fonte}", file=sys.stderr)
        return 1

    destinos = [destino for destino in config.rotina.destinos if destino.ativo]
    duplicado = _validar_destinos(destinos)
    if duplicado:
        print(f"  ERRO: {duplicado}", file=sys.stderr)
        return 1

    if nome_destino:
        destinos = [destino for destino in destinos if destino.nome == nome_destino]
        if not destinos:
            print(
                f"  ERRO: nenhum destino ativo com o nome {nome_destino!r}",
                file=sys.stderr,
            )
            return 1
    elif not destinos:
        print(
            "  ERRO: nenhum destino de rotina configurado.\n"
            '  Adicione a chave "rotina" ao agebackup.json (veja o REQUISITOS.md).',
            file=sys.stderr,
        )
        return 1

    _titulo(f"Rotina - {tipo}")
    print(f"  Fonte: {fonte}")

    dados = varrer_fonte(fonte)
    if dados.erros:
        print(
            f"\n  ERRO: nao foi possivel ler {len(dados.erros)} item(ns) da fonte:",
            file=sys.stderr,
        )
        for erro in dados.erros[:10]:
            print(f"    {erro}", file=sys.stderr)
        if len(dados.erros) > 10:
            print(f"    ... e mais {len(dados.erros) - 10}.", file=sys.stderr)
        return 1

    falhou = False

    for destino_cfg in destinos:
        caminho = Path(destino_cfg.caminho).expanduser()
        nome = destino_cfg.nome or str(caminho)

        if not caminho.is_dir():
            print(f"\n  {nome}: destino inacessivel ({caminho})", file=sys.stderr)
            falhou = True
            continue

        if _dentro_da_fonte(fonte, caminho):
            print(
                f"\n  {nome}: o destino nao pode ficar dentro do backup ({caminho})",
                file=sys.stderr,
            )
            falhou = True
            continue

        if not os.access(caminho, os.W_OK):
            print(f"\n  {nome}: sem permissao de escrita em {caminho}", file=sys.stderr)
            falhou = True
            continue

        efetivo = tipo
        if tipo != "full" and not _runs(caminho):
            efetivo = "full"
            print(f"\n  {nome}: primeiro snapshot; executando como full.")
        elif tipo == "diferencial" and escolher_ancora(caminho, "diferencial") is None:
            efetivo = "full"
            print(f"\n  {nome}: sem full anterior; executando como full.")

        ancora = escolher_ancora(caminho, efetivo)
        momento = datetime.now()
        run_id = _novo_run_id(caminho, efetivo, momento)
        temporario = caminho / f".{run_id}.tmp"

        if dry_run:
            contagem = montar_snapshot(fonte, dados, temporario, ancora, simular=True)
            print(f"\n  {nome}: {run_id}")
            print(f"    {_descrever(contagem)}")
            removiveis = prever_retencao(caminho, config.rotina.manter, efetivo)
            if removiveis:
                print(
                    f"    retencao removeria: {len(removiveis)} snapshot(s) antigo(s)"
                )
            continue

        try:
            limpar_temporarios(caminho)
            contagem = montar_snapshot(fonte, dados, temporario, ancora)
            os.replace(temporario, caminho / run_id)
        except OSError as erro:
            print(f"\n  {nome}: falha ao gravar o snapshot: {erro}", file=sys.stderr)
            falhou = True
            continue

        problemas: list[str] = []
        removidos: list[str] = []
        try:
            removidos = aplicar_retencao(caminho, config.rotina.manter)
        except OSError as erro:
            problemas.append(f"retencao nao aplicada: {erro}")

        registro = {
            "id": run_id,
            "tipo": efetivo,
            "inicio": momento.astimezone().isoformat(timespec="seconds"),
            "fim": _agora(),
            "arquivos": contagem.arquivos,
            "copiados": contagem.copiados,
            "ligados": contagem.ligados,
            "bytes": contagem.bytes_copiados,
            "pastas": contagem.pastas,
            "sem_link": contagem.sem_link,
        }
        try:
            salvar_estado(fonte, nome, caminho, registro)
        except OSError as erro:
            problemas.append(f"estado nao atualizado: {erro}")

        print(f"\n  {nome}: {run_id}")
        print(f"    {_descrever(contagem)}")
        if contagem.sem_link:
            print("    aviso: destino sem hardlink; os inalterados foram copiados")
        if removidos:
            print(f"    retencao: {len(removidos)} snapshot(s) antigo(s) removido(s)")
        if problemas:
            falhou = True
            for problema in problemas:
                print(f"    aviso: snapshot gravado, mas {problema}", file=sys.stderr)

    if dry_run:
        print("\n  Simulacao: nenhum arquivo foi gravado.")

    return 1 if falhou else 0


def _status(config: Config) -> int:
    """Mostra os snapshots existentes em cada destino."""
    _titulo("Rotina - status")

    if not config.rotina.destinos:
        print("\n  Nenhum destino configurado.")
        print('  Adicione a chave "rotina" ao agebackup.json (veja o REQUISITOS.md).')
        return 0

    manter = config.rotina.manter
    print(
        f"  Retencao: full={manter.full or 'todos'}, "
        f"incremental={manter.incremental or 'todos'}, "
        f"diferencial={manter.diferencial or 'todos'}"
    )

    for destino_cfg in config.rotina.destinos:
        caminho = Path(destino_cfg.caminho).expanduser()
        situacao = "ativo" if destino_cfg.ativo else "inativo"
        print(f"\n  {destino_cfg.nome or caminho} ({situacao}): {caminho}")

        if not caminho.is_dir():
            print("    (inacessivel)")
            continue

        runs = _runs(caminho)
        if not runs:
            print("    (nenhum snapshot ainda)")
            continue

        contagem: dict[str, int] = {}
        for _, tipo, _ in runs:
            contagem[tipo] = contagem.get(tipo, 0) + 1
        resumo = ", ".join(
            f"{quantidade} {tipo}" for tipo, quantidade in contagem.items()
        )
        print(f"    {len(runs)} snapshot(s): {resumo}")

        for run_id, _, _ in runs[-5:]:
            print(f"    - {run_id}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da rotina (``agebackup-rotina``)."""
    parser = argparse.ArgumentParser(
        prog="agebackup-rotina",
        description="Copia o backup local para destinos secundarios, em snapshots.",
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--full",
        dest="tipo",
        action="store_const",
        const="full",
        help="copia todos os arquivos (padrao quando nao ha snapshot anterior)",
    )
    grupo.add_argument(
        "--incremental",
        dest="tipo",
        action="store_const",
        const="incremental",
        help="copia so o que mudou desde o ultimo snapshot (padrao)",
    )
    grupo.add_argument(
        "--diferencial",
        dest="tipo",
        action="store_const",
        const="diferencial",
        help="copia so o que mudou desde o ultimo full",
    )
    grupo.add_argument(
        "--status", action="store_true", help="mostra os snapshots existentes"
    )
    parser.add_argument(
        "--destino",
        metavar="NOME",
        default="",
        help="executa apenas o destino com este nome",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="simula, sem gravar nada"
    )
    parser.set_defaults(tipo="incremental")

    args = parser.parse_args(argv)

    try:
        config = carregar_configuracao()
    except ConfigError as erro:
        print(f"  {erro}", file=sys.stderr)
        return 1

    if args.status:
        return _status(config)

    return executar_rotina(config, args.tipo, args.destino, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
