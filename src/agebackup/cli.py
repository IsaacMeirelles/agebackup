"""Comando de linha do backup."""

from __future__ import annotations

import sys
from pathlib import Path

from agebackup import falhas as falhas_mod
from agebackup.backup import (
    carregar_configuracao,
    executar_backup,
    pendentes_de_original,
    reconstruir_pendentes,
)
from agebackup.config import Config, ConfigError
from agebackup.drive import DriveError, get_service
from agebackup.verificacao import verificar

LIMITE_ERROS_MOSTRADOS = 10
LIMITE_GRANDES_MOSTRADOS = 20
LIMITE_CHECK_MOSTRADOS = 10


def _link_original(drive_id: str) -> str:
    """Link do arquivo no Drive, para baixar o original pela web."""
    return f"https://drive.google.com/file/d/{drive_id}/view"


def _titulo(texto: str) -> None:
    print(f"\n{'=' * 62}\n  {texto}\n{'=' * 62}")


def mostrar_erros(falhas: list) -> None:
    """Lista as falhas da execução, limitando a quantidade exibida.

    Os arquivos grandes demais para exportar não entram aqui: eles foram salvos
    em PDF e são listados à parte por `mostrar_pendentes`.
    """
    reais = [falha for falha in falhas if falha.categoria != falhas_mod.CAT_GRANDE]
    if not reais:
        return

    print(f"\n  Falhas ({len(reais)}):")
    for falha in reais[:LIMITE_ERROS_MOSTRADOS]:
        print(f"    - {falha.nome}: {falha.categoria}")
        if falha.detalhe:
            print(f"        {falha.detalhe.splitlines()[0][:66]}")

    if len(reais) > LIMITE_ERROS_MOSTRADOS:
        print(f"    ... e mais {len(reais) - LIMITE_ERROS_MOSTRADOS} (veja o log).")


def mostrar_pendentes(falhas: list) -> None:
    """Lista os nativos grandes que ficaram em PDF, com o link do original."""
    grandes = [falha for falha in falhas if falha.categoria == falhas_mod.CAT_GRANDE]
    if not grandes:
        return

    print(f"\n  Originais grandes, guardados em PDF ({len(grandes)}):")
    for falha in grandes[:LIMITE_GRANDES_MOSTRADOS]:
        print(f"    - {falha.nome}")
        if falha.drive_id:
            print(f"        {_link_original(falha.drive_id)}")
    if len(grandes) > LIMITE_GRANDES_MOSTRADOS:
        print(f"    ... e mais {len(grandes) - LIMITE_GRANDES_MOSTRADOS}.")

    print(
        "\n  O conteúdo está no PDF. Para o original editável, abra o link e use\n"
        "  Arquivo > Fazer download. A lista também está em: agebackup-backup --listar-grandes"
    )


def listar_grandes(config: Config, destino_raiz: Path) -> None:
    """Lista os nativos grandes ainda pendentes de download manual.

    O log é histórico: um arquivo cujo original/editável já foi recuperado
    (``files.download`` ou reconstrução) deixa de aparecer aqui.
    """
    pasta_logs = config.logs.pasta(destino_raiz)
    todas = falhas_mod.ler(pasta_logs)
    grandes = [
        linha for linha in todas if linha.get("categoria") == falhas_mod.CAT_GRANDE
    ]
    pendentes = pendentes_de_original(destino_raiz, pasta_logs)

    _titulo("Originais grandes (baixar pela web)")
    print(f"  Log: {falhas_mod.caminho_log(pasta_logs)}")

    if not grandes:
        print("\n  Nenhum arquivo pendente.")
        return

    vistos: set[str] = set()
    for linha in grandes:
        drive_id = linha.get("drive_id", "")
        if drive_id and drive_id not in pendentes:
            continue
        chave = drive_id or linha.get("nome", "")
        if chave in vistos:
            continue
        vistos.add(chave)
        print(f"\n  {linha.get('nome', '?')}")
        if drive_id:
            print(f"      {_link_original(drive_id)}")

    if not vistos:
        print("\n  Nenhum arquivo pendente (os originais já foram recuperados).")
        return

    print(f"\n  {len(vistos)} arquivo(s). Abra o link e use Arquivo > Fazer download.")


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
        if linha.get("caminho"):
            print(f"      Caminho   : {linha['caminho']}")
        if linha.get("modificado"):
            print(f"      Modificado: {linha['modificado']}")


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

    retencao = config.logs.keep_logs
    print(
        f"  Retencao: {'indeterminado' if retencao == 0 else f'{retencao} execucoes'}"
    )
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
        "\n  Os logs antigos são comprimidos automaticamente quando a execução\n"
        "  seguinte começa (data e hora no nome).\n"
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
        "    --listar-grandes  Lista os arquivos grandes que ficaram em PDF\n"
        "    --reconstruir-grandes  Baixa o original/editavel dos grandes ja em PDF\n"
        "    --logs         Mostra os logs e a politica de rotacao\n"
        "    --check        Verifica a integridade do backup local (offline)\n"
        "    -h, --help     Mostra esta ajuda"
    )
    return 0


def _reconstruir_grandes() -> int:
    """Recupera o original/editável dos grandes já baixados como PDF."""
    try:
        config = carregar_configuracao()
    except ConfigError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    destino = Path(config.backup.destination).expanduser()

    try:
        service = get_service()
    except DriveError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    _titulo("Recuperar originais grandes")
    print(f"  Destino: {destino}")

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    if reconstruidos == 0 and falhas == 0:
        print("\n  Nada a recuperar. Veja a lista com: --listar-grandes")
        return 0

    print(f"\n  {reconstruidos} recuperado(s), {falhas} falha(s).")
    if falhas:
        print(
            "  Pode ser queda de rede ou API indisponivel; repita o comando.\n"
            "  Sem o original, baixe pela web com: --listar-grandes"
        )
    return 1 if falhas else 0


def _check() -> int:
    """Confere manifesto x disco, sem tocar na internet."""
    try:
        config = carregar_configuracao()
    except ConfigError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    destino = Path(config.backup.destination).expanduser()
    resultado = verificar(destino)

    _titulo("Verificacao do backup")
    print(f"  Destino    : {destino}")
    print(
        "  Manifesto  : "
        + ("ausente ou ilegivel" if resultado.manifesto_inutilizavel else "ok")
    )
    print(f"  Verificados: {resultado.verificados}")

    if resultado.faltando:
        print(f"\n  Faltando no disco ({len(resultado.faltando)}):")
        for caminho in resultado.faltando[:LIMITE_CHECK_MOSTRADOS]:
            print(f"    - {caminho}")
        if len(resultado.faltando) > LIMITE_CHECK_MOSTRADOS:
            print(f"    ... e mais {len(resultado.faltando) - LIMITE_CHECK_MOSTRADOS}.")

    if resultado.tamanho_divergente:
        print(f"\n  Tamanho divergente ({len(resultado.tamanho_divergente)}):")
        for caminho, esperado, atual in resultado.tamanho_divergente[
            :LIMITE_CHECK_MOSTRADOS
        ]:
            print(f"    - {caminho}  (manifesto {esperado}B, disco {atual}B)")
        if len(resultado.tamanho_divergente) > LIMITE_CHECK_MOSTRADOS:
            resto = len(resultado.tamanho_divergente) - LIMITE_CHECK_MOSTRADOS
            print(f"    ... e mais {resto}.")

    if resultado.tmp_orfaos:
        print(f"\n  Temporarios residuais ({len(resultado.tmp_orfaos)}):")
        for caminho in resultado.tmp_orfaos[:LIMITE_CHECK_MOSTRADOS]:
            print(f"    - {caminho}")
        print("  (restos de execucoes interrompidas; nao atrapalham o backup)")

    if resultado.fora_do_manifesto:
        print(f"\n  Fora do manifesto ({len(resultado.fora_do_manifesto)}):")
        for caminho in resultado.fora_do_manifesto[:LIMITE_CHECK_MOSTRADOS]:
            print(f"    - {caminho}")
        if len(resultado.fora_do_manifesto) > LIMITE_CHECK_MOSTRADOS:
            print(
                "    ... e mais "
                f"{len(resultado.fora_do_manifesto) - LIMITE_CHECK_MOSTRADOS}."
            )
        print("  (informativo: arquivos que o agebackup nao baixou)")

    print()
    if resultado.problemas:
        print("  ERRO: backup incompleto ou conferencia impossivel.")
        return 1
    print(f"  OK: {resultado.verificados} arquivo(s) conferido(s).")
    return 0


def main() -> int:
    """Ponto de entrada do backup."""
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    verbose = "--verbose" in args or "-v" in args

    if "--help" in args or "-h" in args:
        return _ajuda()

    if "--check" in args:
        return _check()

    if "--falhas" in args:
        try:
            config = carregar_configuracao()
        except ConfigError as error:
            print(f"  {error}", file=sys.stderr)
            return 1
        mostrar_falhas(config.logs.pasta(Path(config.backup.destination).expanduser()))
        return 0

    if "--listar-grandes" in args:
        try:
            config = carregar_configuracao()
        except ConfigError as error:
            print(f"  {error}", file=sys.stderr)
            return 1
        listar_grandes(config, Path(config.backup.destination).expanduser())
        return 0

    if "--reconstruir-grandes" in args:
        return _reconstruir_grandes()

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
    mostrar_pendentes(stats.falhas_registro)

    if dry_run:
        print("\n  Simulacao: nenhum arquivo foi gravado.")

    return 1 if stats.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
