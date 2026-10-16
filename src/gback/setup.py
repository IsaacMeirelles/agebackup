"""Tela de configuração interativa da conta e credenciais."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from gback import config as config_mod
from gback.config import (
    AUTH_ADC,
    AUTH_SERVICE_ACCOUNT,
    MESES_MAXIMO,
    MESES_MINIMO,
    MESES_PADRAO,
    READONLY_SCOPE,
    AccountConfig,
    BackupConfig,
    Config,
    ConfigError,
    LogConfig,
)

SEPARADOR = "=" * 62

# Digitado num campo que já tem valor, limpa o campo em vez de substituí-lo.
LIMPAR = "-"


def configurar_logs(existente: LogConfig) -> LogConfig:
    """Passo 4: pasta, rotação e retenção dos logs."""
    _titulo("Passo 4 de 4 - Pasta, rotacao e retencao dos logs")

    print("  Os logs de falhas e de remocoes ficam numa subpasta do destino e")
    print("  sao comprimidos por mes. A retencao define por quanto tempo os")
    print("  arquivos antigos sao mantidos.")

    pasta_atual = existente.directory if existente else config_mod.LOGS_PADRAO
    print(f"\n  Pasta dos logs atual: {pasta_atual or '(raiz do destino)'}")
    print("  Digite '-' para gravar na raiz do destino.")
    pasta = _perguntar(
        "Pasta dos logs (dentro do destino)", pasta_atual, obrigatorio=False
    )
    if pasta == LIMPAR:
        pasta = ""
    pasta = config_mod.ajustar_pasta_logs(pasta)

    if existente is not None:
        atual = existente.keep_months
        atual_texto = "indeterminado" if atual == 0 else f"{atual} meses"
        print(f"\n  Retencao atual: {atual_texto}")
        print(f"  Compactacao atual: {'gzip' if existente.compress else 'desativada'}")
        # O padrao e "nao": pressionar Enter nunca deve alterar o que ja foi
        # configurado por engano.
        if not _perguntar_bool("Alterar a retencao?", False):
            return LogConfig(
                enabled=True,
                keep_months=existente.keep_months,
                compress=existente.compress,
                directory=pasta,
            )

    print("\n  0 = guardar todos os meses, sem apagar nada")
    print(f"  1 a {MESES_MAXIMO} = quantos meses manter")
    while True:
        resposta = _perguntar(
            "Meses de retencao",
            str(MESES_PADRAO),
        )
        try:
            meses = int(resposta)
        except ValueError:
            print("    Digite um numero inteiro.")
            continue
        if MESES_MINIMO <= meses <= MESES_MAXIMO:
            break
        print(f"    Precisa ser entre {MESES_MINIMO} e {MESES_MAXIMO}.")

    compress = _perguntar_bool("Comprimir os logs antigos com gzip?", True)

    return LogConfig(
        enabled=True, keep_months=meses, compress=compress, directory=pasta
    )


def _titulo(texto: str) -> None:
    print(f"\n{SEPARADOR}\n  {texto}\n{SEPARADOR}")


def _perguntar(pergunta: str, padrao: str = "", obrigatorio: bool = True) -> str:
    """Pede um valor ao usuário.

    Com `obrigatorio=False`, uma resposta em branco é aceita e devolvida como
    string vazia. Isso existe para perguntas em que "em branco" é uma resposta
    legítima — por exemplo, deixar o ID da pasta vazio para copiar o Drive
    inteiro.
    """
    sufixo = f" [{padrao}]" if padrao else ""
    while True:
        try:
            resposta = input(f"  {pergunta}{sufixo}: ").strip()
        except EOFError:
            return padrao
        if resposta:
            return resposta
        if padrao:
            return padrao
        if not obrigatorio:
            return ""
        print("    Preencha este campo ou digite Ctrl+C para cancelar.")


def _perguntar_bool(pergunta: str, padrao: bool) -> bool:
    sufixo = " [S/n]" if padrao else " [n/S]"
    while True:
        try:
            resposta = input(f"  {pergunta}{sufixo}: ").strip().lower()
        except EOFError:
            return padrao
        if not resposta:
            return padrao
        if resposta in ("s", "sim", "y", "yes"):
            return True
        if resposta in ("n", "nao", "não", "no"):
            return False
        print("    Responda com s (sim) ou n (não).")


def _pular() -> None:
    print("\n  Configuração cancelada. Nada foi alterado.")
    raise SystemExit(0)


def mostrar_status() -> None:
    """Exibe o estado atual sem alterar nada."""
    info = config_mod.status()
    adc = info["adc_info"]

    _titulo("Estado atual")

    print(
        f"  gcloud CLI     : {'instalado' if info['gcloud_installed'] else 'NAO INSTALADO'}"
    )
    if info["gcloud_path"]:
        print(f"    caminho      : {info['gcloud_path']}")

    cfg = info["config"]

    if cfg is not None and cfg.account.auth_method == AUTH_SERVICE_ACCOUNT:
        print("  Credenciais    : Service Account (arquivo JSON)")
        if cfg.account.email:
            print(f"    conta        : {cfg.account.email}")
    elif info["adc_present"]:
        print("  Credenciais    : encontradas (ADC)")
        if adc.get("email"):
            print(f"    conta        : {adc['email']}")
        if adc.get("project_id"):
            print(f"    projeto      : {adc['project_id']}")
    else:
        print("  Credenciais    : NENHUMA (rode a configuracao)")

    print(f"  Arquivo        : {info['config_file']}")
    if cfg is None:
        print("    conteudo     : ainda nao configurado")
    else:
        metodo = (
            "service_account"
            if cfg.account.auth_method == AUTH_SERVICE_ACCOUNT
            else "adc"
        )
        print(f"    conta        : {cfg.account.email or '(nao definida)'}")
        print(f"    metodo       : {metodo}")
        print(f"    autenticada  : {'sim' if cfg.account.verified else 'nao validada'}")
        print(f"    escopos      : {', '.join(cfg.account.scopes)}")
        print(f"    destino      : {cfg.backup.destination or '(nao definido)'}")
        print(f"    pasta Drive  : {cfg.backup.folder_id or '(Drive inteiro)'}")
        print(
            f"    drives       : {'incluidos' if cfg.backup.include_shared_drives else 'nao incluidos'}"
        )
        retencao = cfg.logs.keep_months
        print(
            f"    retencao     : {'indeterminado' if retencao == 0 else f'{retencao} meses'}"
        )
        print(f"    compactacao  : {'gzip' if cfg.logs.compress else 'desativada'}")
        print(f"    pasta logs   : {cfg.logs.directory or '(raiz do destino)'}")


@dataclass
class AuthForm:
    """Decisões de autenticação tomadas no passo 1.

    `auth_method` vale "manter" quando o usuário escolheu continuar com as
    credenciais já gravadas, ou AUTH_ADC / AUTH_SERVICE_ACCOUNT quando escolheu
    (re)autenticar de outra forma.
    """

    auth_method: str = "manter"
    service_account_key_path: str = ""
    email: str = ""
    reuse_existing: bool = True


def _resumo_conta(account: AccountConfig) -> str:
    """Uma linha legível descrevendo a autenticação salva."""
    if account.auth_method == AUTH_SERVICE_ACCOUNT:
        metodo = "Service Account"
    else:
        metodo = "ADC (gcloud)"
    return f"{metodo} - {account.email or 'conta desconhecida'}"


def configurar_conta(anterior: Config | None = None) -> AuthForm:
    """Passo 1: escolha do método de autenticação e das credenciais.

    Antes de qualquer coisa, pergunta se deve reaproveitar a configuração
    existente. Se a autenticação salva estiver quebrada, avisa e não deixa
    "manter" como escolha segura.
    """
    _titulo("Passo 1 de 4 - Conta e credenciais")

    form = AuthForm()

    if anterior is not None:
        print(f"  Configuracao existente: {_resumo_conta(anterior.account)}")
        if anterior.account.ask_reuse:
            usar = _perguntar_bool("\n  Usar a configuracao existente?", True)
        else:
            usar = True
            print(
                "\n  Reaproveitando automaticamente (a pergunta foi desativada"
                " numa execucao anterior)."
            )
        if not usar:
            print("\n  A configuracao existente sera IGNORADA. Comecando do zero.")
            form.reuse_existing = False
            anterior = None

    # Valida a autenticação atual antes de oferecer a opção de mantê-la.
    credenciais_validas = False
    if anterior is not None:
        print("\n  Verificando a autenticacao atual...")
        ok, mensagem, _ = config_mod.verify_connection(anterior.account)
        print(f"  {mensagem}")
        credenciais_validas = ok
        if not ok:
            print("  ATENCAO: a autenticacao atual NAO esta funcionando.")
            print("  Escolha um metodo abaixo para reautenticar.")

    print("\n  Metodo de autenticacao:")
    print("    1) ADC via gcloud     - usa sua conta Google (abre ou copia uma URL)")
    print("    2) Service Account    - chave em JSON, sem navegador")
    if credenciais_validas:
        print("    3) Manter a autenticacao atual (validada agora)")

    padrao = "3" if credenciais_validas else "1"
    while True:
        escolha = _perguntar("  Opcao", padrao, obrigatorio=False)
        if not escolha:
            escolha = padrao
        if escolha == "1":
            form.auth_method = AUTH_ADC
            break
        if escolha == "2":
            form.auth_method = AUTH_SERVICE_ACCOUNT
            break
        if escolha == "3" and credenciais_validas:
            form.auth_method = "manter"
            return form
        print("    Responda com 1, 2 ou 3.")

    if form.auth_method == AUTH_SERVICE_ACCOUNT:
        return _configurar_service_account(form)
    return _configurar_adc(form)


def _configurar_service_account(form: AuthForm) -> AuthForm:
    """Lê e valida o arquivo JSON de uma Service Account."""
    print("\n  Service Account: informe o caminho do arquivo JSON da chave.")
    print("  Crie a chave no Google Cloud e compartilhe as pastas do Drive")
    print("  com o e-mail da conta de servico (client_email) como Leitor.")

    while True:
        caminho = _perguntar("  Caminho do JSON", "", obrigatorio=False)
        if not caminho:
            print("    Informe um caminho ou digite Ctrl+C para cancelar.")
            continue

        chave = Path(caminho).expanduser()
        if not chave.exists():
            print(f"    Arquivo nao encontrado: {chave}")
            continue

        try:
            dados = json.loads(chave.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            print(f"    Nao foi possivel ler o JSON: {erro}")
            continue

        if not isinstance(dados, dict) or dados.get("type") != "service_account":
            print("    Este arquivo nao parece ser uma chave de Service Account.")
            continue

        # Guarda o caminho absoluto: um caminho relativo quebraria se o gback
        # fosse executado de outro diretório.
        form.service_account_key_path = str(chave.resolve())
        form.email = dados.get("client_email", "")
        print(f"    OK: {form.email or 'conta de servico'}")
        return form


def _configurar_adc(form: AuthForm) -> AuthForm:
    """Fluxo ADC via gcloud (com escopos e suporte a WSL)."""
    if not config_mod.gcloud_installed():
        print("\n  A gcloud CLI nao esta instalada nesta maquina.")
        print("  Instale: https://cloud.google.com/sdk/docs/install")
        print("  Ou escolha a opcao 2 (Service Account) na proxima vez.")
        _pular()

    print(f"\n  gcloud encontrada em: {config_mod.gcloud_path()}")

    if config_mod.adc_present():
        info = config_mod.adc_info()
        conta = info.get("email") or "conta desconhecida"
        print(f"  Credenciais ADC ja existem para: {conta}")
        if _perguntar_bool("  Fazer login novamente?", False):
            _autenticar()
    else:
        _autenticar()

    form.email = config_mod.adc_info().get("email", "")
    return form


def _autenticar() -> None:
    """Executa o login ADC e reporta o resultado."""
    print("\n  Escopos pedidos (leitura do Drive + cloud-platform):")
    print(f"    {READONLY_SCOPE}")
    print(f"    {config_mod.CLOUD_PLATFORM_SCOPE}")

    if config_mod.in_wsl():
        print("\n  WSL detectado: o navegador nao abre sozinho.")
        print("  1) Copie a URL que aparecera abaixo e abra no navegador do Windows.")
        print("  2) Autorize com sua conta Google.")
        print("  3) Copie o codigo exibido e cole aqui no terminal.")
    else:
        print("\n  Vai abrir o navegador para voce autorizar o acesso.")
        print("  Se aparecer aviso de app nao verificado:")
        print('  escolha "Avancado" e depois "Acessar o gback (nao seguro)".')

    try:
        config_mod.login([READONLY_SCOPE])
    except ConfigError as error:
        print(f"\n  ERRO: {error}")
        print("\n  Dica: se o navegador nao abre no seu ambiente, use a opcao 2")
        print("  (Service Account), que nao depende de navegador.")
        raise SystemExit(1) from error

    info = config_mod.adc_info()
    print(f"\n  Autenticado como: {info.get('email') or '(conta nao informada)'}")


@dataclass
class BackupForm:
    """Respostas do passo 2 do assistente."""

    destination: str
    folder_id: str
    shared_drives: bool


def _rotulo(atual: str, padrao: str) -> str:
    """Marca o valor atual quando difere do padrão."""
    if atual == padrao:
        return ""
    return f"  (atual: {atual})"


def configurar_backup(atual: BackupConfig | None = None) -> BackupForm:
    """Passo 2: opções do backup.

    Quando já existe configuração, cada pergunta mostra o valor atual como
    padrão. Pressionar Enter mantém; digitar outro valor substitui.
    """
    _titulo("Passo 2 de 4 - Destino e escopo do backup")

    padrao_destino = str(Path.home() / "gback")
    destino_atual = atual.destination if atual else ""

    print("  Pasta local onde os arquivos serao gravados.")
    if destino_atual and destino_atual != padrao_destino:
        print(f"  Configuracao atual: {destino_atual}")
    destino = _perguntar("Destino local", destino_atual or padrao_destino)

    folder_atual = atual.folder_id if atual else ""
    print("\n  Para fazer backup de apenas uma pasta do Drive, informe o ID.")
    if folder_atual:
        print(f"  Configuracao atual: {folder_atual}")
        print(
            "  Pressione Enter para manter, ou digite - para voltar ao Drive inteiro."
        )
    else:
        print("  Deixe em branco para baixar o Drive inteiro.")
    folder = _perguntar("ID da pasta no Drive", folder_atual, obrigatorio=False)
    if folder == LIMPAR:
        folder = ""

    shared_atual = atual.include_shared_drives if atual else False
    print("\n  Shared drives (Drive compartilhado de equipes) exigem escopo extra")
    print("  e podem nao estar acessiveis com sua conta.")
    if shared_atual:
        print("  Configuracao atual: sim")
    shared = _perguntar_bool("Incluir shared drives?", shared_atual)

    return BackupForm(destino, folder, shared)


def testar_conexao(
    account: AccountConfig | None = None, folder_id: str = ""
) -> tuple[bool, str]:
    """Passo 3: verificação real contra a API.

    Devolve (sucesso, email). O email vem da API e é a fonte confiável do
    endereço da conta. Quando `folder_id` é informado, confere também o acesso
    à pasta — é o que evita um backup silencioso de "0 arquivos".
    """
    _titulo("Passo 3 de 4 - Teste de conexao")

    print("  Consultando a Drive API...")
    ok, mensagem, email = config_mod.verify_connection(account, folder_id)
    print(f"  {mensagem}")
    return ok, email


def _perguntar_reuso_futuro(config: Config) -> None:
    """Depois de autenticar com sucesso, oferece desligar a pergunta de reuso."""
    print()
    perguntar = _perguntar_bool(
        "  Na proxima vez, perguntar de novo se deve usar a configuracao existente?",
        True,
    )
    config.account.ask_reuse = perguntar
    if not perguntar:
        print("  Ok. O setup vai reaproveitar a configuracao sem perguntar.")


def wizard() -> int:
    """Executa o assistente completo de configuração."""
    mostrar_status()

    _titulo("Configuracao do gback")

    # Carrega a configuração existente para usar seus valores como padrão.
    anterior = config_mod.load()

    if anterior is not None:
        print("\n  Pressione Enter para manter, ou digite outro valor para alterar.")
        print("  Para nao alterar nada, pressione Ctrl+C a qualquer momento.")

    try:
        auth = configurar_conta(anterior)

        base = anterior if (anterior is not None and auth.reuse_existing) else None

        resultado = configurar_backup(base.backup if base else None)

        config = base if base is not None else Config()

        if auth.auth_method != "manter":
            config.account.auth_method = auth.auth_method
            config.account.service_account_key_path = auth.service_account_key_path
            if auth.email:
                config.account.email = auth.email
        config.account.scopes = [READONLY_SCOPE]

        config.backup.destination = resultado.destination
        config.backup.folder_id = resultado.folder_id
        config.backup.include_shared_drives = resultado.shared_drives

        conexao_ok, email_api = testar_conexao(config.account, config.backup.folder_id)
        config.account.verified = conexao_ok
        if email_api:
            # Fonte confiável do endereço (o ADC do gcloud não guarda o e-mail).
            config.account.email = email_api

        config.logs = configurar_logs(config.logs)

        if conexao_ok:
            _perguntar_reuso_futuro(config)
        else:
            # Não valida a autenticação: mantém a pergunta ligada para o usuário
            # poder corrigir na próxima execução.
            config.account.ask_reuse = True

        caminho = config_mod.save(config)

    except KeyboardInterrupt, EOFError:
        print()
        _pular()

    _titulo("Configuracao salva")
    print(f"  Arquivo: {caminho}")
    print("  Permissoes: 600 (somente o usuario le)")

    if conexao_ok:
        print("\n  Tudo pronto. O backup pode ser executado.")
    else:
        print("\n  Configuracao salva, mas a conexao nao foi confirmada.")
        print("  Rode o teste novamente antes de fazer backup.")

    return 0


def editar_logs() -> int:
    """Edita apenas a política de rotação, preservando o resto da config."""
    _titulo("Politica de rotacao dos logs")

    atual = config_mod.load()
    if atual is None:
        print("  Nao ha configuracao salva. Rode primeiro: uv run gback-setup")
        return 1

    try:
        atual.logs = configurar_logs(atual.logs)
        caminho = config_mod.save(atual)
    except KeyboardInterrupt, EOFError:
        print()
        _pular()

    _titulo("Politica salva")
    print(f"  Arquivo: {caminho}")
    print(f"  Pasta dos logs: {atual.logs.directory or '(raiz do destino)'}")
    retencao = atual.logs.keep_months
    print(f"  Retencao: {'indeterminado' if retencao == 0 else f'{retencao} meses'}")
    return 0


def _ajuda() -> int:
    """Mostra a ajuda da tela de configuração."""
    _titulo("gback-setup - ajuda")
    print(
        "  Uso: gback-setup [opcoes]\n\n"
        "    (sem opcoes)   Assistente completo (4 passos)\n"
        "    --status       Mostra o estado atual\n"
        "    --test         Testa a conexao com a API\n"
        "    --logs         Edita so a retencao dos logs\n"
        "    --reset        Apaga a configuracao\n"
        "    -h, --help     Mostra esta ajuda"
    )
    return 0


def main() -> int:
    """Ponto de entrada da tela de configuração."""
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        return _ajuda()

    if "--status" in args:
        mostrar_status()
        return 0

    if "--logs" in args:
        return editar_logs()

    if "--reset" in args:
        if config_mod.clear():
            print(f"  Configuracao removida: {config_mod.CONFIG_FILE}")
        else:
            print("  Nao havia configuracao para remover.")
        return 0

    if "--test" in args:
        cfg = config_mod.load()
        folder = cfg.backup.folder_id if cfg is not None else ""
        ok, mensagem, _ = config_mod.verify_connection(folder_id=folder)
        print(f"  {mensagem}")
        return 0 if ok else 1

    return wizard()
