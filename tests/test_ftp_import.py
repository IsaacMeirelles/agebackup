"""Testes da importação e gravação segura das credenciais FTP."""

from __future__ import annotations

import json

import pytest

from agebackup import config as config_mod
from agebackup import config_paths, crypto_ftp, ftp, ftp_import
from agebackup.config import Config


@pytest.fixture(autouse=True)
def app_isolado(tmp_path, monkeypatch):
    """Coloca o agebackup.json e a chave de cifragem num diretório temporário."""
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(config_paths, "get_config_dir", lambda: app)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", app)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", app / "agebackup.json")
    monkeypatch.setattr(config_mod, "ADC_FILE", app / "adc.json")
    return app


def test_aplicar_credenciais_cifra_senha_e_limpa_caminho_externo():
    cfg = Config()
    cfg.envio.credenciais = "/tmp/antigo.ini"

    ftp_import.aplicar_credenciais(
        cfg,
        host="ftp.exemplo.com",
        porta="2121",
        usuario="fulano",
        senha="segredo",
        pasta="/backups/YYYY",
        tls=False,
        manter=4,
    )

    assert cfg.ftp.host == "ftp.exemplo.com"
    assert cfg.ftp.porta == 2121
    assert cfg.ftp.usuario == "fulano"
    assert cfg.ftp.senha_criptografada
    assert cfg.ftp.senha_criptografada != "segredo"
    assert crypto_ftp.descriptografar(cfg.ftp.senha_criptografada) == "segredo"
    assert cfg.ftp.pasta_remota == "/backups/YYYY"
    assert cfg.ftp.tls is False
    assert cfg.envio.credenciais == ""
    assert cfg.envio.pasta_remota == "/backups/YYYY"
    assert cfg.envio.manter == 4


def test_senha_em_branco_preserva_a_senha_cifrada_existente():
    cfg = Config()
    ftp_import.aplicar_credenciais(
        cfg,
        host="ftp.exemplo.com",
        usuario="fulano",
        senha="segredo",
    )
    cifrada = cfg.ftp.senha_criptografada

    ftp_import.aplicar_credenciais(
        cfg,
        host="outro.exemplo.com",
        usuario="fulano",
        senha="",
    )

    assert cfg.ftp.host == "outro.exemplo.com"
    assert cfg.ftp.senha_criptografada == cifrada
    assert crypto_ftp.descriptografar(cfg.ftp.senha_criptografada) == "segredo"


def test_salvar_e_obter_credenciais_do_config_json():
    cfg = Config()
    ftp_import.aplicar_credenciais(
        cfg,
        host="ftp.exemplo.com",
        porta=21,
        usuario="fulano",
        senha="segredo",
        pasta="/RSKO/YYYY-MM",
    )
    config_mod.save(cfg)

    carregado = config_mod.load()
    cred = ftp.obter_credenciais(carregado)

    assert carregado is not None
    assert carregado.ftp.tem_dados() is True
    assert carregado.envio.credenciais == ""
    assert cred.host == "ftp.exemplo.com"
    assert cred.porta == 21
    assert cred.usuario == "fulano"
    assert cred.senha == "segredo"
    assert cred.pasta == "/RSKO/YYYY-MM"


def test_importar_do_ini_grava_senha_cifrada_no_config(tmp_path):
    ini = tmp_path / "ftp.ini"
    ini.write_text(
        "[ftp]\nhost = ftp.exemplo.com\nuser = fulano\n"
        "password = segredo\nporta = 2121\ntls = false\n",
        encoding="utf-8",
    )

    assert ftp_import.importar_do_ini(ini) is True

    cfg = config_mod.load()
    assert cfg is not None
    assert cfg.ftp.host == "ftp.exemplo.com"
    assert cfg.ftp.porta == 2121
    assert cfg.ftp.usuario == "fulano"
    assert cfg.ftp.senha_criptografada != "segredo"
    assert crypto_ftp.descriptografar(cfg.ftp.senha_criptografada) == "segredo"
    assert cfg.ftp.tls is False
    assert cfg.envio.credenciais == ""


def test_limpar_credenciais_mantem_caminho_externo():
    cfg = Config()
    ftp_import.aplicar_credenciais(
        cfg,
        host="ftp.exemplo.com",
        usuario="fulano",
        senha="segredo",
    )
    cfg.envio.credenciais = "/tmp/ftp.ini"

    ftp_import.aplicar_credenciais(cfg, host="", usuario="")

    assert cfg.ftp.tem_dados() is False
    assert cfg.ftp.senha_criptografada == ""
    assert cfg.envio.credenciais == "/tmp/ftp.ini"


def test_host_sem_usuario_e_recusado():
    with pytest.raises(ValueError, match="host e usuário"):
        ftp_import.aplicar_credenciais(
            Config(), host="ftp.exemplo.com", usuario="", senha="segredo"
        )


def test_senha_sem_host_e_recusada():
    with pytest.raises(ValueError, match="host e usuário"):
        ftp_import.aplicar_credenciais(Config(), host="", usuario="", senha="segredo")


def test_porta_invalida_e_recusada():
    with pytest.raises(ValueError, match="Porta FTP"):
        ftp_import.aplicar_credenciais(
            Config(), host="ftp.exemplo.com", usuario="fulano", porta="abc"
        )


def test_porta_fora_da_faixa_e_recusada():
    with pytest.raises(ValueError, match="fora da faixa"):
        ftp_import.aplicar_credenciais(
            Config(), host="ftp.exemplo.com", usuario="fulano", porta=70000
        )


def test_porta_vazia_usa_21():
    cfg = ftp_import.aplicar_credenciais(
        Config(), host="ftp.exemplo.com", usuario="fulano", porta=""
    )

    assert cfg.ftp.porta == 21


# ---------------------------------------------------------------------------
# Credenciais Google embutidas no agebackup.json
# ---------------------------------------------------------------------------


def test_service_account_embutida_e_usada_para_montar_credenciais(monkeypatch):
    from google.oauth2 import service_account

    dados = {
        "type": "service_account",
        "project_id": "projeto",
        "private_key_id": "id",
        "private_key": "-----BEGIN PRIVATE KEY-----\n...\n",
        "client_email": "conta@projeto.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    conta = config_mod.AccountConfig(
        auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
        email=dados["client_email"],
        service_account_json_criptografado=crypto_ftp.criptografar(json.dumps(dados)),
    )

    usado = {}
    marcador = object()

    def from_info(info, scopes):
        usado["info"] = info
        usado["scopes"] = scopes
        return marcador

    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_info", from_info
    )

    assert config_mod.build_credentials(conta) is marcador
    assert usado["info"] == dados
    assert usado["scopes"] == [config_mod.READONLY_SCOPE]


def test_adc_embutida_e_usada_para_montar_credenciais(monkeypatch):
    from google.oauth2.credentials import Credentials

    dados = {
        "type": "authorized_user",
        "client_id": "cliente",
        "client_secret": "segredo",
        "refresh_token": "token",
    }
    conta = config_mod.AccountConfig(
        auth_method=config_mod.AUTH_ADC,
        adc_json_criptografado=crypto_ftp.criptografar(json.dumps(dados)),
    )

    usado = {}
    marcador = object()

    def from_info(info, scopes=None):
        usado["info"] = info
        usado["scopes"] = scopes
        return marcador

    monkeypatch.setattr(Credentials, "from_authorized_user_info", from_info)

    assert config_mod.build_credentials(conta) is marcador
    assert usado["info"] == dados
    assert usado["scopes"] == [config_mod.READONLY_SCOPE]


def test_adc_embutida_dispensa_arquivo_externo():
    dados = {
        "type": "authorized_user",
        "client_id": "cliente",
        "client_secret": "segredo",
        "refresh_token": "token",
        "quota_project_id": "projeto",
    }
    config_mod.save(
        Config(
            account=config_mod.AccountConfig(
                auth_method=config_mod.AUTH_ADC,
                adc_json_criptografado=crypto_ftp.criptografar(json.dumps(dados)),
            )
        )
    )

    assert config_mod.adc_present() is True
    assert config_mod.adc_info()["project_id"] == "projeto"
    assert config_mod.adc_info()["type"] == "authorized_user"


def test_chave_presente_quando_service_account_esta_embutida():
    conta = config_mod.AccountConfig(
        auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
        service_account_json_criptografado="texto-cifrado",
    )

    assert conta.chave_presente() is True


def test_credencial_embutida_ilegivel_falha_com_mensagem():
    conta = config_mod.AccountConfig(
        auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
        service_account_json_criptografado="conteudo-invalido",
    )

    with pytest.raises(config_mod.ConfigError, match="decifrar"):
        config_mod.build_credentials(conta)
