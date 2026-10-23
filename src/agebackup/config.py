"""Configuração da conta e das credenciais de acesso do AgeBackup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from agebackup import config_paths

# Configuração sempre junto à aplicação (sobrescreve comportamento antigo)
CONFIG_DIR = config_paths.get_config_dir()
CONFIG_FILE = config_paths.get_config_path()
# Arquivo legado (apenas para migração/compatibilidade)
LEGACY_CONFIG_DIR = config_paths.LEGACY_CONFIG_DIR
LEGACY_CONFIG_FILE = config_paths.LEGACY_CONFIG_FILE

ADC_FILE = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

# Somente leitura: suficiente para backup e com menos burocracia de verificação.
READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

# Escopos das APIs nativas (Slides, Docs, Sheets), usados só para reconstruir
# o formato editável dos arquivos grandes demais para o files.export (limite de
# 10 MB por requisição). São pedidos à parte, porque exigem cada API habilitada
# no projeto do Google.
PRESENTATIONS_READONLY_SCOPE = "https://www.googleapis.com/auth/presentations.readonly"
DOCUMENTS_READONLY_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
SPREADSHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

# Todos os escopos de reconstrução, na ordem em que os pedimos. O Drive é
# pedido junto porque a autenticação só é válida para os escopos concedidos.
SCOPES_RECONSTRUCAO = (
    PRESENTATIONS_READONLY_SCOPE,
    DOCUMENTS_READONLY_SCOPE,
    SPREADSHEETS_READONLY_SCOPE,
)

# Versões recentes do gcloud recusam emitir credenciais ADC apenas com escopos
# restritos (como o do Drive): exigem também o cloud-platform. Pedimos os dois.
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Métodos de autenticação aceitos.
AUTH_ADC = "adc"
AUTH_SERVICE_ACCOUNT = "service_account"

# Política de retry para falhas temporárias ao baixar
RETRY_PADRAO = 3
RETRY_MINIMO = 1
RETRY_MAXIMO = 10

# Retenção dos logs por execução. 0 significa "guardar tudo" (só comprimir).
# O padrão de 7 casa com uma semana de execuções diárias.
LOGS_PADRAO_MANTER = 7
LOGS_MAXIMO = 365

# Subpasta do destino onde os logs são gravados. Vazio = raiz do destino.
LOGS_PADRAO = "logs"

# Retenção dos arquivos compactados (.tar.gz). 0 significa "guardar todos".
MANTER_PADRAO = 0
MANTER_MINIMO = 0
MANTER_MAXIMO = 60

# Periodicidade da compactação full: quantos dias entre um full e o próximo.
# No intervalo, as execuções são incrementais (só os arquivos novos e
# alterados). O padrão é 7 dias (uma semana).
FULL_PADRAO_DIAS = 7
# 0 = compactar tudo a cada execução (sempre full).
FULL_MINIMO = 0
FULL_MAXIMO = 365

# Retenção dos arquivos já enviados ao servidor FTP. 0 significa "guardar todos".
# O padrão de 7 casa com uma semana de execuções diárias.
MANTER_ENVIO_PADRAO = 7
MANTER_ENVIO_MAXIMO = 365


@dataclass
class AccountConfig:
    """Dados da conta configurada."""

    email: str = ""
    scopes: list[str] = field(default_factory=lambda: [READONLY_SCOPE])
    auth_method: str = AUTH_ADC  # adc | service_account
    service_account_key_path: str = ""
    # Conteúdo do JSON da Service Account, cifrado no agebackup.json. Quando
    # presente, dispensa o arquivo externo e o caminho acima.
    service_account_json_criptografado: str = ""
    # Conteúdo do ADC (authorized_user), cifrado no agebackup.json. Permite
    # levar a autenticação para outro servidor sem depender do HOME/gcloud.
    adc_json_criptografado: str = ""
    # Vira True depois de uma autenticação validada com sucesso. Serve para
    # saber que a configuração salva não está quebrada.
    verified: bool = False
    # Perguntar "usar a configuração existente?" ao abrir o assistente.
    # Depois de uma autenticação bem-sucedida o usuário pode desligar isso.
    ask_reuse: bool = True

    def chave_presente(self) -> bool:
        """True se a credencial necessária existe.

        No modo Service Account a autenticação usa o JSON cifrado dentro do
        `agebackup.json` ou, na falta dele, o arquivo indicado em
        `service_account_key_path`. Em ADC devolve True porque a credencial
        pode estar no arquivo externo do gcloud ou cifrada no próprio JSON.
        """
        if self.auth_method != AUTH_SERVICE_ACCOUNT:
            return True
        if self.service_account_json_criptografado:
            return True
        if not self.service_account_key_path:
            return False
        return Path(self.service_account_key_path).expanduser().exists()


@dataclass
class LogConfig:
    """Rotação e retenção dos logs.

    Cada execução gera um log com data e hora no nome; na execução seguinte o
    anterior é comprimido. `keep_logs` define quantos logs fechados são mantidos
    antes de serem apagados.

    `directory` é a subpasta do destino onde os logs ficam (padrão: "logs").
    Vazio significa a raiz do próprio destino.
    """

    enabled: bool = True
    keep_logs: int = LOGS_PADRAO_MANTER
    compress: bool = True
    directory: str = LOGS_PADRAO

    def pasta(self, destino: Path) -> Path:
        """Pasta onde os logs são gravados, dentro do destino."""
        return destino / self.directory if self.directory else destino


@dataclass
class RetryConfig:
    """Configuração de tentativas de recuperação para downloads."""

    attempts: int = RETRY_PADRAO


@dataclass
class CompactacaoConfig:
    """Compactação do backup em um arquivo .tar.gz.

    `destino` é a pasta onde os arquivos compactados são gravados (vazio =
    pasta acima do backup). `manter` limita quantos arquivos ficam guardados;
    0 significa "guardar todos". `prefixo`, quando não vazio, entra no nome do
    arquivo entre a pasta e a data (``<pasta>_<prefixo>_AAAAMMDD-HHMM.tar.gz``).

    `full_a_cada` define a periodicidade da compactação **full**: quantos dias
    entre um full e o próximo. No intervalo, a execução é **incremental** (só
    os arquivos novos e alterados). O padrão é 7 dias; 0 significa compactar
    tudo a cada execução.
    """

    destino: str = ""
    manter: int = MANTER_PADRAO
    prefixo: str = ""
    full_a_cada: int = FULL_PADRAO_DIAS

    def pasta(self, destino_backup: Path) -> Path:
        """Pasta onde os arquivos compactados são gravados."""
        if self.destino:
            return Path(self.destino).expanduser()
        return destino_backup.expanduser().parent

    def texto_full_a_cada(self) -> str:
        """Descrição curta da periodicidade, para mostrar na tela."""
        if self.full_a_cada <= 0:
            return "sempre (a cada execucao)"
        if self.full_a_cada == 1:
            return "a cada 1 dia"
        return f"a cada {self.full_a_cada} dias"


@dataclass
class EnvioConfig:
    """Envio dos arquivos compactados para um servidor FTP/FTPS.

    `credenciais` é o arquivo com host/usuário/senha (vazio = ``ftp.ini`` na
    pasta de configuração). `manter` limita quantos arquivos ficam no servidor;
    0 significa "guardar todos". `pasta_remota` permite personalizar o caminho
    remoto com variáveis YYYY, YY, MM, M, dd, d.
    """

    credenciais: str = ""
    manter: int = MANTER_ENVIO_PADRAO
    pasta_remota: str = ""

    def caminho_credenciais(self) -> Path:
        """Arquivo de credenciais do FTP."""
        if self.credenciais:
            return Path(self.credenciais).expanduser()
        return CONFIG_DIR / "ftp.ini"


@dataclass
class BackupConfig:
    """Opções do backup."""

    destination: str = ""
    folder_id: str = ""
    include_shared_drives: bool = False


@dataclass
class FtpConfig:
    """Dados FTP/FTPS salvos diretamente na configuração."""

    host: str = ""
    porta: int = 21
    usuario: str = ""
    senha_criptografada: str = ""
    pasta_remota: str = ""
    tls: bool = True

    def tem_dados(self) -> bool:
        return bool(self.host and self.usuario)


@dataclass
class Config:
    """Configuração completa do AgeBackup."""

    account: AccountConfig = field(default_factory=AccountConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    logs: LogConfig = field(default_factory=LogConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    compactacao: CompactacaoConfig = field(default_factory=CompactacaoConfig)
    envio: EnvioConfig = field(default_factory=EnvioConfig)
    ftp: FtpConfig = field(default_factory=FtpConfig)

    def to_dict(self) -> dict:
        return asdict(self)


def load() -> Config | None:
    """Carrega a configuração salva, ou None se ainda não existir."""
    # Só migra quando ninguém redirecionou o CONFIG_FILE (testes, por exemplo).
    if CONFIG_FILE == config_paths.get_config_path():
        try:
            config_paths.migrar_se_necessario()
        except OSError:
            # Não falha se a migração der problema; usa o local atual mesmo.
            pass

    if not CONFIG_FILE.exists():
        return None

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Não foi possível ler {CONFIG_FILE}: {error}") from error

    cfg = Config(
        account=AccountConfig(**_conhecidos(data.get("account"), AccountConfig)),
        backup=BackupConfig(**_conhecidos(data.get("backup"), BackupConfig)),
        logs=LogConfig(**_conhecidos(data.get("logs"), LogConfig)),
        retry=RetryConfig(**_conhecidos(data.get("retry"), RetryConfig)),
        compactacao=CompactacaoConfig(
            **_conhecidos(data.get("compactacao"), CompactacaoConfig)
        ),
        envio=EnvioConfig(**_conhecidos(data.get("envio"), EnvioConfig)),
        ftp=FtpConfig(**_conhecidos(data.get("ftp"), FtpConfig)),
    )
    return cfg


def _conhecidos(dados: object, modelo: type) -> dict:
    """Filtra só as chaves que o modelo reconhece.

    Assim uma configuração salva por uma versão mais nova não quebra ao ser
    lida por uma mais antiga, e uma mais antiga ganha os padrões das novas.
    """
    if not isinstance(dados, dict):
        return {}

    campos = {campo.name for campo in fields(modelo)}
    filtrado = {chave: valor for chave, valor in dados.items() if chave in campos}
    if modelo is LogConfig:
        return _ajustar_log(filtrado)
    if modelo is RetryConfig:
        return _ajustar_retry(filtrado)
    if modelo is CompactacaoConfig:
        return _ajustar_compactacao(filtrado)
    if modelo is EnvioConfig:
        return _ajustar_envio(filtrado)
    if modelo is FtpConfig:
        return filtrado
    return filtrado


def _ajustar_envio(dados: dict) -> dict:
    """Normaliza as credenciais e a retenção do envio ao servidor."""
    if "manter" in dados:
        try:
            dados["manter"] = max(0, min(MANTER_ENVIO_MAXIMO, int(dados["manter"])))
        except TypeError, ValueError:
            dados["manter"] = MANTER_ENVIO_PADRAO
    if "credenciais" in dados and not isinstance(dados["credenciais"], str):
        dados["credenciais"] = ""
    return dados


def _ajustar_log(dados: dict) -> dict:
    """Normaliza a retenção e a pasta dos logs."""
    campos = LOGS_MAXIMO
    if "keep_logs" in dados:
        try:
            dados["keep_logs"] = max(0, min(campos, int(dados["keep_logs"])))
        except TypeError, ValueError:
            dados["keep_logs"] = LOGS_PADRAO_MANTER
    elif "keep_months" in dados:
        # Configuração antiga, medida em meses: converte para a nova, em
        # execuções (o dobro, aproximando uma execução por dia útil).
        dados.pop("keep_months", None)
        dados["keep_logs"] = LOGS_PADRAO_MANTER
    if "directory" in dados:
        dados["directory"] = ajustar_pasta_logs(dados["directory"])
    return dados


def _ajustar_retry(dados: dict) -> dict:
    """Normaliza as tentativas de retry."""
    if "attempts" in dados:
        try:
            dados["attempts"] = max(
                RETRY_MINIMO, min(RETRY_MAXIMO, int(dados["attempts"]))
            )
        except TypeError, ValueError:
            dados["attempts"] = RETRY_PADRAO
    return dados


def _ajustar_compactacao(dados: dict) -> dict:
    """Normaliza a retenção, o destino e o prefixo dos arquivos compactados."""
    if "manter" in dados:
        try:
            dados["manter"] = max(
                MANTER_MINIMO, min(MANTER_MAXIMO, int(dados["manter"]))
            )
        except TypeError, ValueError:
            dados["manter"] = MANTER_PADRAO
    if "destino" in dados and not isinstance(dados["destino"], str):
        dados["destino"] = ""
    if "prefixo" in dados:
        dados["prefixo"] = ajustar_prefixo_compactacao(dados["prefixo"])
    if "full_a_cada" in dados:
        try:
            dados["full_a_cada"] = max(
                FULL_MINIMO, min(FULL_MAXIMO, int(dados["full_a_cada"]))
            )
        except TypeError, ValueError:
            dados["full_a_cada"] = FULL_PADRAO_DIAS
    return dados


def ajustar_prefixo_compactacao(valor: object) -> str:
    """Sanitiza o prefixo do nome dos arquivos compactados.

    Vazio significa não usar prefixo: o nome volta ao padrão
    ``<pasta>_AAAAMMDD-HHMM.tar.gz``. Valores com separador de caminho, `..` ou
    caractere de controle são ignorados, porque o prefixo entra no nome de um
    arquivo — não abre pasta nem sai do destino.
    """
    if not isinstance(valor, str):
        return ""

    bruto = valor.strip()
    if not bruto or bruto in {".", ".."}:
        return ""

    proibidos = ("/", "\\", "\0")
    if any(proibido in bruto for proibido in proibidos):
        return ""

    return bruto


def ajustar_pasta_logs(valor: object) -> str:
    """Sanitiza o nome da subpasta dos logs dentro do destino.

    Vazio significa a raiz do destino. Caminhos absolutos e com `..` voltam ao
    padrão: os logs precisam ficar dentro do backup.
    """
    if not isinstance(valor, str):
        return LOGS_PADRAO

    bruto = valor.strip()
    if not bruto:
        return ""

    caminho = Path(bruto)
    if caminho.is_absolute() or ".." in caminho.parts:
        return LOGS_PADRAO
    return str(caminho)


def save(config: Config) -> Path:
    """Salva a configuração junto à aplicação com permissão restrita ao usuário."""
    try:
        # Usa o diretório do CONFIG_FILE (respeita redirecionamentos em testes).
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Mantém chmod no diretório quando possível
        try:
            CONFIG_DIR.chmod(0o700)
        except OSError:
            pass
        CONFIG_FILE.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        CONFIG_FILE.chmod(0o600)
    except OSError as error:
        raise ConfigError(f"Não foi possível salvar {CONFIG_FILE}: {error}") from error

    return CONFIG_FILE


def clear() -> bool:
    """Remove a configuração. Devolve False se não havia nada."""
    if not CONFIG_FILE.exists():
        return False
    CONFIG_FILE.unlink()
    return True


def proteger_chave_service_account(caminho: str) -> str:
    """Protege a chave de Service Account e devolve seu caminho final.

    Se a chave já estiver dentro de CONFIG_DIR, apenas garante a permissão
    correta (0o600). Caso contrário, copia a chave para CONFIG_DIR com
    permissão restrita (0o600) e devolve esse novo caminho. Não remove o
    arquivo original.
    """
    try:
        chave = Path(caminho).expanduser().resolve()
    except OSError:
        return caminho

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass

    try:
        if chave.is_relative_to(CONFIG_DIR):
            chave.chmod(0o600)
            return str(chave)

        destino = CONFIG_DIR / chave.name
        # Evita sobrescrever arquivos existentes com nomes iguais.
        if destino.exists():
            suffix = chave.stem + "-" + str(int(chave.stat().st_mtime)) + chave.suffix
            destino = CONFIG_DIR / suffix
        import shutil

        shutil.copy2(chave, destino)
        destino.chmod(0o600)
        return str(destino)
    except OSError:
        return caminho


class ConfigError(Exception):
    """Erro na configuração."""


def gcloud_path() -> str | None:
    """Localiza o executável do gcloud, ou None se não estiver instalado."""
    return shutil.which("gcloud")


def gcloud_installed() -> bool:
    """Verifica se a gcloud CLI está disponível."""
    return gcloud_path() is not None


def _texto_credencial_criptografada(valor: str, nome: str) -> str:
    """Decifra uma credencial guardada no JSON, com erro legível."""
    from agebackup import crypto_ftp

    if not valor:
        return ""
    texto = crypto_ftp.descriptografar(valor)
    if not texto:
        raise ConfigError(
            f"Não foi possível decifrar a credencial {nome}. "
            "Confira se o arquivo .agebackup-ftp.key está junto do agebackup.json."
        )
    return texto


def _json_credencial(valor: str, nome: str) -> dict:
    """Decifra e valida o JSON de uma credencial embutida."""
    texto = _texto_credencial_criptografada(valor, nome)
    if not texto:
        return {}
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as error:
        raise ConfigError(
            f"Credencial {nome} inválida no agebackup.json: {error}"
        ) from error
    if not isinstance(dados, dict):
        raise ConfigError(f"Credencial {nome} não é um objeto JSON válido.")
    return dados


def _dados_adc() -> dict:
    """Dados ADC do JSON cifrado ou, na falta dele, do arquivo do gcloud."""
    config = load()
    if config is not None and config.account.adc_json_criptografado:
        try:
            return _json_credencial(config.account.adc_json_criptografado, "ADC")
        except ConfigError:
            return {}

    if not ADC_FILE.exists():
        return {}
    try:
        dados = json.loads(ADC_FILE.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}


def adc_present() -> bool:
    """Verifica se existem credenciais de Application Default Credentials."""
    if ADC_FILE.exists():
        return True
    try:
        config = load()
    except ConfigError:
        return False
    return bool(config and config.account.adc_json_criptografado)


def adc_info() -> dict:
    """Lê o ADC e devolve email, client_id e project_id, se houver."""
    data = _dados_adc()
    if not data:
        return {}

    # Atenção: o ADC do gcloud (authorized_user) NÃO guarda o e-mail da conta —
    # só o client_id, o refresh_token e, às vezes, o quota_project_id. O e-mail
    # de verdade é obtido pela API (verify_connection). Aqui é só um palpite.
    return {
        "email": data.get("account") or data.get("email") or "",
        "client_id": data.get("client_id", ""),
        "project_id": data.get("quota_project_id", ""),
        "type": data.get("type", "unknown"),
    }


def in_wsl() -> bool:
    """Detecta se o processo roda dentro do WSL.

    No WSL o `gcloud` não consegue abrir o navegador do Windows sozinho; nesse
    caso usamos `--no-launch-browser` e o usuário copia a URL/cola o código.
    """
    try:
        versao = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
        if "microsoft" in versao.lower() or "wsl" in versao.lower():
            return True
    except OSError:
        pass
    return bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSLENV"))


def login(scopes: list[str] | None = None) -> bool:
    """Dispara `gcloud auth application-default login`.

    Devolve False se o gcloud não estiver instalado ou se o usuário cancelar.

    O escopo cloud-platform é acrescentado automaticamente: o gcloud recente
    recusa emitir credenciais apenas com escopos restritos como o do Drive.
    No WSL, adiciona `--no-launch-browser` porque não há navegador acessível.
    """
    if not gcloud_installed():
        raise ConfigError(
            "gcloud CLI não encontrado. Instale com:\n"
            "  https://cloud.google.com/sdk/docs/install"
        )

    scope_list = list(scopes or [READONLY_SCOPE])
    if CLOUD_PLATFORM_SCOPE not in scope_list:
        scope_list.append(CLOUD_PLATFORM_SCOPE)

    command = [
        gcloud_path(),
        "auth",
        "application-default",
        "login",
        "--scopes",
        ",".join(scope_list),
    ]
    if in_wsl():
        command.append("--no-launch-browser")

    try:
        result = subprocess.run(command, check=False, text=True)
    except OSError as error:
        raise ConfigError(f"Falha ao executar o gcloud: {error}") from error

    if result.returncode != 0:
        raise ConfigError(
            f"O login falhou (código {result.returncode}). "
            "Verifique se o login foi concluído no navegador."
        )

    return adc_present()


def build_credentials(
    account: AccountConfig | None = None, scopes: list[str] | None = None
):
    """Monta as credenciais Google a partir da configuração.

    Suporta dois métodos:
      * Service Account: usa o JSON cifrado no `agebackup.json` ou, na falta
        dele, o arquivo indicado em `service_account_key_path`.
      * ADC: usa o JSON cifrado no `agebackup.json` ou o que estiver no
        ambiente (gcloud / GOOGLE_APPLICATION_CREDENTIALS).

    Levanta `ConfigError` quando a credencial está configurada mas não pode ser
    lida/decifrada.
    """
    import google.auth

    scope_list = list(scopes or [READONLY_SCOPE])
    if account is None:
        cfg = load()
        account = cfg.account if cfg is not None else None

    if account is not None and account.auth_method == AUTH_SERVICE_ACCOUNT:
        if account.service_account_key_path:
            from google.oauth2 import service_account

            chave = Path(account.service_account_key_path).expanduser()
            if chave.exists():
                return service_account.Credentials.from_service_account_file(
                    str(chave), scopes=scope_list
                )
            if not account.service_account_json_criptografado:
                raise ConfigError(f"Chave de Service Account não encontrada: {chave}")

        if account.service_account_json_criptografado:
            from google.oauth2 import service_account

            dados = _json_credencial(
                account.service_account_json_criptografado, "Service Account"
            )
            return service_account.Credentials.from_service_account_info(
                dados, scopes=scope_list
            )

    if account is not None and account.adc_json_criptografado:
        from google.oauth2.credentials import Credentials

        dados = _json_credencial(account.adc_json_criptografado, "ADC")
        return Credentials.from_authorized_user_info(dados, scopes=scope_list)

    credentials, _ = google.auth.default(scopes=scope_list)
    return credentials


def verify_connection(
    account: AccountConfig | None = None, folder_id: str = ""
) -> tuple[bool, str, str]:
    """Testa a conexão com a Drive API usando as credenciais atuais.

    Devolve (sucesso, mensagem, email). Faz uma chamada real de leitura à API.

    O e-mail vem da resposta da API (`about().get`): é a única fonte confiável,
    porque o arquivo ADC do gcloud não guarda o endereço da conta.

    Quando `folder_id` é informado, confere também se a credencial enxerga essa
    pasta. Isso pega o caso mais comum de "0 arquivos": a pasta existe, mas não
    foi compartilhada com a Service Account.

    `account` permite testar uma conta ainda não salva (útil no assistente,
    que valida a Service Account antes de gravá-la no disco).
    """
    try:
        from agebackup.drive import get_service

        credentials = build_credentials(account)
        service = get_service(credentials=credentials)
        about = service.about().get(fields="user(emailAddress)").execute()
        email = about.get("user", {}).get("emailAddress", "")
        quem = email or "conta desconhecida"
    except Exception as error:  # noqa: BLE001 - a tela precisa mostrar qualquer falha
        return False, f"Falha na conexão: {describe_error(error)}", ""

    if folder_id:
        try:
            pasta = (
                service.files()
                .get(fileId=folder_id, fields="id,name", supportsAllDrives=True)
                .execute()
            )
        except Exception as error:  # noqa: BLE001
            return (
                False,
                (
                    f"Conectado como {quem}, mas a pasta {folder_id} nao foi "
                    f"encontrada ({describe_error(error)}). Compartilhe a pasta "
                    "com essa conta como Leitor, ou confira o ID."
                ),
                email,
            )
        return True, f"Conectado como {quem} (pasta: {pasta.get('name', '?')})", email

    return True, f"Conectado como {quem}", email


def describe_error(error: Exception) -> str:
    """Transforma uma exceção em uma linha legível para o terminal."""
    status = getattr(getattr(error, "resp", None), "status", None)

    if status:
        details = getattr(error, "error_details", "")
        codes = {
            item.get("reason")
            for item in details
            if isinstance(details, list) and isinstance(item, dict)
        }
        resumo = ", ".join(sorted(code for code in codes if code))
        return f"HTTP {status} ({resumo})" if resumo else f"HTTP {status}"

    texto = str(error).strip()
    return texto.splitlines()[0] if texto else type(error).__name__


def status() -> dict:
    """Resume o estado atual da configuração para exibição."""
    config = load()
    return {
        "gcloud_installed": gcloud_installed(),
        "gcloud_path": gcloud_path(),
        "adc_present": adc_present(),
        "adc_info": adc_info(),
        "config_file": CONFIG_FILE,
        "config_exists": config is not None,
        "config": config,
        "chave_presente": config.account.chave_presente() if config else False,
    }
