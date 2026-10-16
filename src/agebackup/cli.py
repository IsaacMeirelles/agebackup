"""Comando de linha do backup."""

from __future__ import annotations

import sys
from pathlib import Path

from agebackup import falhas as falhas_mod
from agebackup.backup import carregar_configuracao, executar_backup
from agebackup.config import ConfigError
from agebackup.drive import DriveError, get_service

LIMITE_ERROS_MOSTRADOS = 10


def _titulo(texto: str) -> None:
    print(f"\n{'=' * 62}\n  {texto}\n{'=' * 62}")


def mostrar_erros(falhas: list) -> None:
    """Lista as falhas da execução, limitando a quantidade exibida."""
    if not falhas:
        return

    print(f"\n  Falhas ({len(falhas)}):")
    for falha in falhas[:LIMITE_ERROS_MOSTRADOS]:
        print(f"    - {falha.nome}: {falha.categoria}")
        if falha.detalhe:
            print(f"        {falha.detalhe.splitlines()[0][:66]}")

    if len(falhas) > LIMITE_ERROS_MOSTRADOS:
        print(f"    ... e mais {len(falhas) - LIMITE_ERROS_MOSTRADOS} (veja o log).")


def mostrar_falhas(pasta_logs: Path) -> None:
    """Mostra as falhas registradas no log, com o total por categoria."""
    linhas = falhas_mod.ler(pasta_logs, ultimas=LIMITE_ERROS_MOSTRADOS)
    if not linhas:
        return

    contagem = falhas_mod.contar_por_categoria(falhas_mod.ler(pasta_logs))
    resumo = ", ".join(f"{n} {categoria}" for categoria, n in contagem.items())

    _titulo("Log de falhas")
    print(f"  Arquivo: {falhas_mod.caminho_log(pasta_logs)}")
    print(f"  Total: {resumo}")
    print("\n  Últimas:")
    for linha in linhas:
        print(f"    {linha['quando']}  {linha['nome']}  ({linha['categoria']})")


def mostrar_logs() -> None:
    """Lista todos os logs, os do mês corrente e os arquivos já comprimidos."""
    from agebackup import manifest as manifest_mod
    from agebackup import rotacao

    _titulo("Logs do AgeBackup")

    try:
        config = carregar_configuracao()
    except ConfigError as error:
        print(f"  {error}", file=sys.stderr)
        return

    destino = Path(config.backup.destination).expanduser()
    pasta_logs = config.logs.pasta(destino)

    retencao = config.logs.keep_months
    print(f"  Retencao: {'indeterminado' if retencao == 0 else f'{retencao} meses'}")
    print(f"  Compactacao: {'gzip' if config.logs.compress else 'desativada'}\n")
    print(f"  Pasta dos logs: {pasta_logs}")

    logs = [
        ("falhas", falhas_mod.caminho_log(pasta_logs)),
        ("removidos", manifest_mod.caminho_removidos(pasta_logs)),
    ]

    for nome, caminho in logs:
        existe = caminho.exists()
        print(f"\n  {nome}: {caminho}")
        if not existe:
            print("    (vazio)")

        for arquivo in rotacao.arquivados(caminho):
            tamanho = arquivo.stat().st_size
            print(f"    {arquivo.name}  ({tamanho / 1024:.1f}KB comprimido)")

    print(
        "\n  Logs antigos são comprimidos automaticamente quando o mês vira.\n"
        "  Para ler um arquivo compactado: zcat <arquivo>.gz"
    )


def _ajuda() -> int:
    """Mostra a ajuda do comando."""
    _titulo("agebackup-backup - ajuda")
    print(
        "  Uso: agebackup-backup [opcoes]\n\n"
        "    (sem opcoes)   Executa o backup\n"
        "    --dry-run      Simula, sem gravar nada\n"
        "    -v, --verbose  Mostra o progresso detalhado\n"
        "    --falhas       Mostra o log de falhas\n"
        "    --logs         Mostra os logs e a politica de rotacao\n"
        "    -h, --help     Mostra esta ajuda"
    )
    return 0


def main() -> int:
    """Ponto de entrada do backup."""
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    verbose = "--verbose" in args or "-v" in args

    if "--help" in args or "-h" in args:
        return _ajuda()

    if "--falhas" in args:
        try:
            config = carregar_configuracao()
        except ConfigError as error:
            print(f"  {error}", file=sys.stderr)
            return 1
        mostrar_falhas(config.logs.pasta(Path(config.backup.destination).expanduser()))
        return 0

    if "--logs" in args:
        mostrar_logs()
        return 0

    try:
        config = carregar_configuracao()
    except ConfigError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    destino = Path(config.backup.destination).expanduser()

    _titulo("Backup do Google Drive")
    print(f"  Conta    : {config.account.email or '(nao identificada)'}")
    print(f"  Destino  : {destino}")
    print(f"  Pasta    : {config.backup.folder_id or 'Drive inteiro'}")
    print(
        f"  Drives   : {'com compartilhados' if config.backup.include_shared_drives else 'apenas o meu'}"
    )
    print(f"  Modo     : {'simulacao (nada sera gravado)' if dry_run else 'real'}")
    print(f"  Logs     : {config.logs.pasta(destino)}")

    if not dry_run:
        try:
            destino.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            print(
                f"\n  ERRO: nao foi possivel usar o destino {destino}", file=sys.stderr
            )
            print(f"  {error}", file=sys.stderr)
            print(
                "  Escolha uma pasta onde voce possa escrever, com:\n"
                "    uv run agebackup-setup",
                file=sys.stderr,
            )
            return 1

    try:
        service = get_service()
    except DriveError as error:
        print(f"\n  ERRO: {error}", file=sys.stderr)
        print("  Rode: uv run agebackup-setup", file=sys.stderr)
        return 1

    print("\n  Consultando o Drive...")
    stats = executar_backup(service, config, destino, dry_run=dry_run, verbose=verbose)

    _titulo("Resumo")
    print(f"  {stats.resumo()}")

    mostrar_erros(stats.falhas_registro)

    if dry_run:
        print("\n  Simulacao: nenhum arquivo foi gravado.")

    return 1 if stats.falhas or stats.requer_lro else 0


if __name__ == "__main__":
    raise SystemExit(main())
