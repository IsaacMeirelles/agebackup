"""Testes da tela de configuração."""

import json
from pathlib import Path

import pytest

from agebackup import config as config_mod
from agebackup.config import (
    MESES_MAXIMO,
    MESES_MINIMO,
    MESES_PADRAO,
    AccountConfig,
    BackupConfig,
    Config,
    ConfigError,
    LogConfig,
)


@pytest.fixture(autouse=True)
def home_isolado(tmp_path, monkeypatch):
    """Redireciona ~/.config para um diretório temporário."""
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".config" / "agebackup")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / ".config" / "agebackup" / "config.json"
    )
    monkeypatch.setattr(
        config_mod,
        "ADC_FILE",
        tmp_path / ".config" / "gcloud" / "application_default_credentials.json",
    )
    return tmp_path


def _criar_adc(**overrides) -> Path:
    """Cria um ADC no formato real do gcloud (authorized_user, sem e-mail)."""
    arquivo = config_mod.ADC_FILE
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    dados = {
        "client_id": "123.apps.googleusercontent.com",
        "client_secret": "segredo",
        "refresh_token": "1//0abc",
        "quota_project_id": "meu-projeto",
        "type": "authorized_user",
        "universe_domain": "googleapis.com",
    }
    dados.update(overrides)
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    return arquivo


def test_gcloud_ausente_e_detectado(monkeypatch):
    monkeypatch.setattr(config_mod.shutil, "which", lambda _: None)

    assert config_mod.gcloud_installed() is False
    assert config_mod.gcloud_path() is None


def test_gcloud_presente_e_localizado(monkeypatch):
    monkeypatch.setattr(config_mod.shutil, "which", lambda nome: "/usr/bin/gcloud")

    assert config_mod.gcloud_installed() is True
    assert config_mod.gcloud_path() == "/usr/bin/gcloud"


def test_adc_ausente():
    assert config_mod.adc_present() is False
    assert config_mod.adc_info() == {}


def test_adc_valido_e_lido():
    _criar_adc()

    info = config_mod.adc_info()

    assert config_mod.adc_present() is True
    # O ADC do gcloud não guarda o e-mail: o project_id não pode virar e-mail.
    assert info["email"] == ""
    assert info["project_id"] == "meu-projeto"
    assert info["type"] == "authorized_user"


def test_adc_com_campo_account_devolve_email():
    _criar_adc(account="usuario@exemplo.com")

    assert config_mod.adc_info()["email"] == "usuario@exemplo.com"


def test_adc_corrompido_nao_quebra():
    config_mod.ADC_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.ADC_FILE.write_text("{quebrado", encoding="utf-8")

    assert config_mod.adc_present() is True
    assert config_mod.adc_info() == {}


def test_login_sem_gcloud_falha_com_instrucao(monkeypatch):
    monkeypatch.setattr(config_mod.shutil, "which", lambda _: None)

    with pytest.raises(ConfigError, match="gcloud CLI não encontrado"):
        config_mod.login()


def test_login_monta_comando_com_escopo(monkeypatch):
    comandos = []

    monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/gcloud")
    _criar_adc()

    def fake_run(comando, check, text):
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(config_mod.subprocess, "run", fake_run)

    assert config_mod.login() is True

    comando = comandos[0]
    assert comando[:4] == ["/usr/bin/gcloud", "auth", "application-default", "login"]
    assert "--scopes" in comando
    escopos = comando[comando.index("--scopes") + 1]
    assert config_mod.READONLY_SCOPE in escopos
    assert config_mod.CLOUD_PLATFORM_SCOPE in escopos


def test_login_falha_quando_codigo_diferente_de_zero(monkeypatch):
    monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/gcloud")
    monkeypatch.setattr(
        config_mod.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 1})()
    )

    with pytest.raises(ConfigError, match="login falhou"):
        config_mod.login()


def test_save_cria_arquivo_com_permissao_restrita(home_isolado):
    config = Config(
        account=AccountConfig(email="u@e.com"),
        backup=BackupConfig(destination=str(home_isolado / "backup")),
    )

    caminho = config_mod.save(config)

    assert caminho.exists()
    assert oct(caminho.stat().st_mode)[-3:] == "600"
    assert oct(caminho.parent.stat().st_mode)[-3:] == "700"


def test_save_e_load_preservam_dados(home_isolado):
    original = Config(
        account=AccountConfig(email="u@e.com"),
        backup=BackupConfig(
            destination=str(home_isolado / "b"),
            folder_id="PASTA",
            include_shared_drives=True,
        ),
    )
    config_mod.save(original)

    carregado = config_mod.load()

    assert carregado is not None
    assert carregado.account.email == "u@e.com"
    assert carregado.backup.folder_id == "PASTA"
    assert carregado.backup.include_shared_drives is True


def test_load_sem_arquivo_retorna_none():
    assert config_mod.load() is None


def test_load_json_invalido_falha_com_mensagem():
    config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_FILE.write_text("{invalido", encoding="utf-8")

    with pytest.raises(ConfigError, match="Não foi possível ler"):
        config_mod.load()


def test_clear_remove_a_configuracao():
    config_mod.save(Config())

    assert config_mod.clear() is True
    assert config_mod.load() is None


def test_clear_sem_arquivo_retorna_false():
    assert config_mod.clear() is False


def test_escopo_padrao_e_somente_leitura():
    assert AccountConfig().scopes == ["https://www.googleapis.com/auth/drive.readonly"]


def test_describe_error_formata_http():
    class Resp:
        status = 403

    erro = type(
        "E", (Exception,), {"resp": Resp(), "error_details": [{"reason": "x"}]}
    )()

    assert config_mod.describe_error(erro) == "HTTP 403 (x)"


def test_describe_error_sem_status_usa_mensagem():
    assert config_mod.describe_error(ValueError("falha aqui")) == "falha aqui"


def test_describe_error_sem_mensagem_usa_tipo():
    assert config_mod.describe_error(ValueError()) == "ValueError"


def test_status_resume_configuracao():
    _criar_adc()
    config_mod.save(Config(account=AccountConfig(email="u@e.com")))

    info = config_mod.status()

    assert info["adc_present"] is True
    assert info["config_exists"] is True
    assert info["config"].account.email == "u@e.com"


def test_chave_presente_em_adc_sempre_verdadeiro():
    assert AccountConfig(auth_method="adc").chave_presente() is True


def test_chave_presente_service_account_ausente():
    conta = AccountConfig(
        auth_method="service_account",
        service_account_key_path="/nao/existe/chave.json",
    )
    assert conta.chave_presente() is False


def test_chave_presente_service_account_sem_caminho():
    conta = AccountConfig(auth_method="service_account")
    assert conta.chave_presente() is False


def test_chave_presente_service_account_arquivo_existe(tmp_path):
    chave = tmp_path / "chave.json"
    chave.write_text("{}")

    conta = AccountConfig(
        auth_method="service_account", service_account_key_path=str(chave)
    )
    assert conta.chave_presente() is True


def test_status_marca_chave_ausente(tmp_path):
    config_mod.save(
        Config(
            account=AccountConfig(
                auth_method="service_account",
                service_account_key_path=str(tmp_path / "sumiu.json"),
            )
        )
    )

    assert config_mod.status()["chave_presente"] is False


def test_logs_padrao_de_12_meses():
    assert LogConfig().keep_months == MESES_PADRAO
    assert LogConfig().compress is True


def test_logs_salvo_e_carregado(home_isolado):
    config = Config(logs=LogConfig(keep_months=6, compress=False))
    config_mod.save(config)

    assert config_mod.load().logs.keep_months == 6
    assert config_mod.load().logs.compress is False


def test_config_sem_secao_logs_usa_padrao(home_isolado):
    """Config salva por versão anterior não deve quebrar."""
    config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_FILE.write_text(
        json.dumps(
            {
                "account": {"email": "u@e.com"},
                "backup": {"destination": "/tmp/x"},
            }
        ),
        encoding="utf-8",
    )

    config = config_mod.load()

    assert config.logs.keep_months == MESES_PADRAO


def test_config_com_chave_desconhecida_e_ignorada(home_isolado):
    config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_FILE.write_text(
        json.dumps({"account": {"email": "u@e.com", "campo_futuro": 1}}),
        encoding="utf-8",
    )

    assert config_mod.load().account.email == "u@e.com"


def test_retencao_acima_do_limite_e_limitada(home_isolado):
    config_mod.save(Config(logs=LogConfig(keep_months=9999)))

    assert config_mod.load().logs.keep_months == MESES_MAXIMO


def test_retencao_negativa_vira_padrao(home_isolado):
    config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_FILE.write_text(
        json.dumps({"logs": {"keep_months": -5}}), encoding="utf-8"
    )

    assert config_mod.load().logs.keep_months == MESES_MINIMO


def test_retencao_texto_invalido_vira_padrao(home_isolado):
    config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_FILE.write_text(
        json.dumps({"logs": {"keep_months": "muitos"}}), encoding="utf-8"
    )

    assert config_mod.load().logs.keep_months == MESES_PADRAO


# ---------------------------------------------------------------------------
# Pasta dos logs
# ---------------------------------------------------------------------------


def test_pasta_dos_logs_padrao(tmp_path):
    assert LogConfig().directory == config_mod.LOGS_PADRAO
    assert LogConfig().pasta(tmp_path) == tmp_path / "logs"


def test_pasta_dos_logs_vazia_usa_a_raiz(tmp_path):
    assert LogConfig(directory="").pasta(tmp_path) == tmp_path


def test_pasta_dos_logs_salva_e_carregada(home_isolado):
    config_mod.save(Config(logs=LogConfig(directory="historico")))

    assert config_mod.load().logs.directory == "historico"


def test_pasta_dos_logs_config_antiga_usa_padrao(home_isolado):
    """Sem a chave `directory`, usa "logs" (padrão)."""
    config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_FILE.write_text(
        json.dumps({"logs": {"keep_months": 6}}), encoding="utf-8"
    )

    assert config_mod.load().logs.directory == config_mod.LOGS_PADRAO


def test_pasta_dos_logs_absoluta_volta_ao_padrao(home_isolado):
    config_mod.save(Config(logs=LogConfig(directory="/etc/agebackup")))

    assert config_mod.load().logs.directory == config_mod.LOGS_PADRAO


def test_pasta_dos_logs_com_dois_pontos_volta_ao_padrao(home_isolado):
    config_mod.save(Config(logs=LogConfig(directory="../fora")))

    assert config_mod.load().logs.directory == config_mod.LOGS_PADRAO


def test_ajustar_pasta_logs_normaliza_vazio():
    assert config_mod.ajustar_pasta_logs("") == ""
    assert config_mod.ajustar_pasta_logs("  ") == ""
    assert config_mod.ajustar_pasta_logs("  logs  ") == "logs"
    assert config_mod.ajustar_pasta_logs(None) == config_mod.LOGS_PADRAO
    assert config_mod.ajustar_pasta_logs("/etc") == config_mod.LOGS_PADRAO
    assert config_mod.ajustar_pasta_logs("a/../b") == config_mod.LOGS_PADRAO


# ---------------------------------------------------------------------------
# Detecção de WSL e montagem do comando de login
# ---------------------------------------------------------------------------


def test_in_wsl_detecta_pelo_proc_version(monkeypatch, tmp_path):
    proc = tmp_path / "version"
    proc.write_text("Linux version ... microsoft-standard-WSL2", encoding="utf-8")
    monkeypatch.setattr(config_mod, "Path", lambda *a, **k: proc)

    assert config_mod.in_wsl() is True


def test_in_wsl_detecta_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
    # /proc/version real pode não existir/ser irrelevante; a variável basta.
    assert config_mod.in_wsl() is True


def test_in_wsl_falso_no_linux_comum(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSLENV", raising=False)
    monkeypatch.setattr(
        config_mod.Path, "read_text", lambda *a, **k: "Linux version 6.0"
    )
    monkeypatch.setattr(config_mod.Path, "exists", lambda *a, **k: True)

    assert config_mod.in_wsl() is False


def test_login_em_wsl_usa_no_launch_browser(monkeypatch):
    comandos = []
    monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/gcloud")
    monkeypatch.setattr(config_mod, "in_wsl", lambda: True)
    _criar_adc()

    def fake_run(comando, check, text):
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(config_mod.subprocess, "run", fake_run)

    config_mod.login()

    assert "--no-launch-browser" in comandos[0]


def test_login_fora_do_wsl_nao_usa_no_launch_browser(monkeypatch):
    comandos = []
    monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/gcloud")
    monkeypatch.setattr(config_mod, "in_wsl", lambda: False)
    _criar_adc()

    def fake_run(comando, check, text):
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(config_mod.subprocess, "run", fake_run)

    config_mod.login()

    assert "--no-launch-browser" not in comandos[0]


def test_login_nao_duplica_cloud_platform(monkeypatch):
    comandos = []
    monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/gcloud")
    monkeypatch.setattr(config_mod, "in_wsl", lambda: False)
    _criar_adc()

    def fake_run(comando, check, text):
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(config_mod.subprocess, "run", fake_run)

    config_mod.login([config_mod.READONLY_SCOPE, config_mod.CLOUD_PLATFORM_SCOPE])

    escopos = comandos[0][comandos[0].index("--scopes") + 1]
    assert escopos.count(config_mod.CLOUD_PLATFORM_SCOPE) == 1


# ---------------------------------------------------------------------------
# Montagem de credenciais (ADC x Service Account)
# ---------------------------------------------------------------------------


def test_build_credentials_adc_usa_google_auth_default(monkeypatch):
    import google.auth

    marcador = object()
    monkeypatch.setattr(google.auth, "default", lambda scopes: (marcador, "projeto"))

    credenciais = config_mod.build_credentials(
        AccountConfig(auth_method=config_mod.AUTH_ADC)
    )

    assert credenciais is marcador


def test_build_credentials_service_account_le_arquivo(monkeypatch, tmp_path):
    import google.oauth2.service_account as sa

    chave = tmp_path / "chave.json"
    chave.write_text("{}", encoding="utf-8")

    marcador = object()
    usado = {}

    def from_file(caminho, scopes):
        usado["caminho"] = caminho
        usado["scopes"] = scopes
        return marcador

    monkeypatch.setattr(sa.Credentials, "from_service_account_file", from_file)

    conta = AccountConfig(
        auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
        service_account_key_path=str(chave),
    )
    credenciais = config_mod.build_credentials(conta)

    assert credenciais is marcador
    assert usado["caminho"] == str(chave)


def test_build_credentials_service_account_sem_arquivo_falha():
    conta = AccountConfig(
        auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
        service_account_key_path="/nao/existe/chave.json",
    )

    with pytest.raises(ConfigError, match="não encontrada"):
        config_mod.build_credentials(conta)


class _AboutFalso:
    def __init__(self, email: str) -> None:
        self._email = email

    def get(self, **kwargs: object) -> _AboutFalso:
        return self

    def execute(self) -> dict:
        return {"user": {"emailAddress": self._email}}


class _GetFalso:
    def __init__(self, erro: Exception | None) -> None:
        self._erro = erro

    def execute(self) -> dict:
        if self._erro is not None:
            raise self._erro
        return {"id": "X", "name": "Minha Pasta"}


class _FilesFalso:
    def __init__(self, erro: Exception | None) -> None:
        self._erro = erro

    def get(self, **kwargs: object) -> _GetFalso:
        return _GetFalso(self._erro)


class _ServiceFalso:
    def __init__(self, email: str = "u@e.com", erro: Exception | None = None) -> None:
        self._email = email
        self._erro = erro

    def about(self) -> _AboutFalso:
        return _AboutFalso(self._email)

    def files(self) -> _FilesFalso:
        return _FilesFalso(self._erro)


def _preparar_verify(monkeypatch, service) -> None:
    from agebackup import drive

    monkeypatch.setattr(config_mod, "build_credentials", lambda *a, **k: object())
    monkeypatch.setattr(drive, "get_service", lambda credentials=None: service)


def test_verify_connection_ok_devolve_email(monkeypatch):
    _preparar_verify(monkeypatch, _ServiceFalso(email="real@empresa.com"))

    ok, mensagem, email = config_mod.verify_connection()

    assert ok is True
    assert email == "real@empresa.com"
    assert "real@empresa.com" in mensagem


def test_verify_connection_pasta_acessivel(monkeypatch):
    _preparar_verify(monkeypatch, _ServiceFalso())

    ok, mensagem, _ = config_mod.verify_connection(folder_id="PASTA")

    assert ok is True
    assert "Minha Pasta" in mensagem


def test_verify_connection_pasta_inacessivel_avisa(monkeypatch):
    _preparar_verify(monkeypatch, _ServiceFalso(erro=Exception("File not found")))

    ok, mensagem, _ = config_mod.verify_connection(folder_id="PASTA")

    assert ok is False
    assert "nao foi encontrada" in mensagem
    assert "Compartilhe a pasta" in mensagem


def test_verify_connection_falha_de_credencial(monkeypatch):
    def explode(*args: object, **kwargs: object) -> None:
        raise config_mod.ConfigError("sem credenciais")

    monkeypatch.setattr(config_mod, "build_credentials", explode)

    ok, mensagem, email = config_mod.verify_connection()

    assert ok is False
    assert email == ""
    assert "Falha na conexão" in mensagem


def test_account_novos_campos_tem_padrao():
    conta = AccountConfig()

    assert conta.auth_method == config_mod.AUTH_ADC
    assert conta.service_account_key_path == ""
    assert conta.verified is False
    assert conta.ask_reuse is True


def test_account_novos_campos_sao_persistidos(home_isolado):
    config = Config(
        account=AccountConfig(
            auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
            service_account_key_path="/tmp/k.json",
            verified=True,
            ask_reuse=False,
        )
    )
    config_mod.save(config)

    conta = config_mod.load().account

    assert conta.auth_method == config_mod.AUTH_SERVICE_ACCOUNT
    assert conta.service_account_key_path == "/tmp/k.json"
    assert conta.verified is True
    assert conta.ask_reuse is False
