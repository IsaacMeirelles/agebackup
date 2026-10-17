"""Configuração da conta e das credenciais de acesso do AgeBackup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "agebackup"
CONFIG_FILE = CONFIG_DIR / "config.json"
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

# Política de rotação dos logs. 0 significa "guardar tudo" (só comprimir).
MESES_PADRAO = 12
MESES_MINIMO = 0
MESES_MAXIMO = 120

# Subpasta do destino onde os logs são gravados. Vazio = raiz do destino.
LOGS_PADRAO = "logs"


@dataclass
class AccountConfig:
    """Dados da conta configurada."""

    email: str = ""
    scopes: list[str] = field(default_factory=lambda: [READONLY_SCOPE])
    auth_method: str = AUTH_ADC  # adc | service_account
    service_account_key_path: str = ""
    # Vira True depois de uma autenticação validada com sucesso. Serve para
    # saber que a configuração salva não está quebrada.
    verified: bool = False
    # Perguntar "usar a configuração existente?" ao abrir o assistente.
    # Depois de uma autenticação bem-sucedida o usuário pode desligar isso.
    ask_reuse: bool = True

    def chave_presente(self) -> bool:
        """True se a credencial necessária existe no disco.

        No modo Service Account a autenticação depende do arquivo JSON da
        chave: se ele sumiu, a configuração está quebrada mesmo com
        `verified` gravado. Em ADC não há arquivo próprio, então devolve True.
        """
        if self.auth_method != AUTH_SERVICE_ACCOUNT:
            return True
        if not self.service_account_key_path:
            return False
        return Path(self.service_account_key_path).expanduser().exists()


@dataclass
class LogConfig:
    """Rotação e retenção dos logs.

    Os logs são comprimidos por mês. `keep_months` define por quanto tempo os
    arquivos comprimidos são mantidos antes de serem apagados.

    `directory` é a subpasta do destino onde os logs ficam (padrão: "logs").
    Vazio significa a raiz do próprio destino.
    """

    enabled: bool = True
    keep_months: int = MESES_PADRAO
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
class BackupConfig:
    """Opções do backup."""

    destination: str = ""
    folder_id: str = ""
    include_shared_drives: bool = False


@dataclass
class Config:
    """Configuração completa do AgeBackup."""

    account: AccountConfig = field(default_factory=AccountConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    logs: LogConfig = field(default_factory=LogConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)

    def to_dict(self) -> dict:
        return asdict(self)


def load() -> Config | None:
    """Carrega a configuração salva, ou None se ainda não existir."""
    if not CONFIG_FILE.exists():
        return None

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Não foi possível ler {CONFIG_FILE}: {error}") from error

    return Config(
        account=AccountConfig(**_conhecidos(data.get("account"), AccountConfig)),
        backup=BackupConfig(**_conhecidos(data.get("backup"), BackupConfig)),
        logs=LogConfig(**_conhecidos(data.get("logs"), LogConfig)),
        retry=RetryConfig(**_conhecidos(data.get("retry"), RetryConfig)),
    )


def _conhecidos(dados: object, modelo: type) -> dict:
    """Filtra só as chaves que o modelo reconhece.

    Assim uma configuração salva por uma versão mais nova não quebra ao ser
    lida por uma mais antiga, e uma mais antiga ganha os padrões das novas.
    """
    if not isinstance(dados, dict):
        return {}

    campos = {campo.name for campo in fields(modelo)}
    filtrado = {chave: valor for chave, valor in dados.items() if chave in campos}
    return (
        _ajustar_log(filtrado)
        if modelo is LogConfig
        else _ajustar_retry(filtrado) if modelo is RetryConfig else filtrado
    )


def _ajustar_log(dados: dict) -> dict:
    """Normaliza a retenção e a pasta dos logs."""
    if "keep_months" in dados:
        try:
            dados["keep_months"] = max(
                MESES_MINIMO, min(MESES_MAXIMO, int(dados["keep_months"]))
            )
        except TypeError, ValueError:
            dados["keep_months"] = MESES_PADRAO
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
    """Salva a configuração com permissão restrita ao usuário."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.chmod(0o700)
        CONFIG_FILE.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
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


def adc_present() -> bool:
    """Verifica se existem credenciais de Application Default Credentials."""
    return ADC_FILE.exists()


def adc_info() -> dict:
    """Lê o arquivo ADC e devolve email, client_id e project_id, se houver."""
    if not ADC_FILE.exists():
        return {}

    try:
        data = json.loads(ADC_FILE.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
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
      * Service Account: lê o arquivo JSON informado em `service_account_key_path`.
      * ADC: usa o que estiver no ambiente (gcloud / GOOGLE_APPLICATION_CREDENTIALS).

    Levanta `ConfigError` quando a Service Account está configurada mas o
    arquivo não existe.
    """
    import google.auth

    scope_list = list(scopes or [READONLY_SCOPE])
    if account is None:
        cfg = load()
        account = cfg.account if cfg is not None else None

    if (
        account is not None
        and account.auth_method == AUTH_SERVICE_ACCOUNT
        and account.service_account_key_path
    ):
        from google.oauth2 import service_account

        chave = Path(account.service_account_key_path).expanduser()
        if not chave.exists():
            raise ConfigError(f"Chave de Service Account não encontrada: {chave}")
        return service_account.Credentials.from_service_account_file(
            str(chave), scopes=scope_list
        )

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
