"""Testes das perguntas do assistente de configuração.

O foco é o `_perguntar`, que precisa distinguir "campo obrigatório" de
"campo onde a resposta em branco é válida".
"""

import io
import json
from pathlib import Path
from unittest import mock

import pytest

from agebackup import config as config_mod
from agebackup import setup
from agebackup.config import AccountConfig, BackupConfig, Config, LogConfig


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


def _responder(entradas: list[str]):
    """Devolve um contexto que simula o input com as respostas dadas.

    O prompt é ecoado no fluxo capturado, imitando o que o terminal faria.
    Assim os testes podem conferir qual pergunta foi (ou não) feita.
    """
    fluxo = iter(entradas)
    saida = io.StringIO()

    def fake_input(prompt: str = "") -> str:
        saida.write(prompt)
        return next(fluxo)

    return mock.patch("builtins.input", fake_input), saida


def _configurar_backup(
    entradas: list[str], atual=None, respostas_extra: list[str] | None = None
):
    fluxo_total = list(entradas) + list(respostas_extra or [])
    entrada, saida = _responder(fluxo_total)
    with entrada, mock.patch("sys.stdout", new=saida):
        resultado = setup.configurar_backup(atual)
    return resultado, saida.getvalue()


class TestPerguntar:
    def test_resposta_vazia_com_padrao_retorna_padrao(self):
        entrada, _ = _responder([""])
        with entrada:
            assert setup._perguntar("Campo", "padrao") == "padrao"

    def test_resposta_preenchida_e_devolvida(self):
        entrada, _ = _responder(["digitado"])
        with entrada:
            assert setup._perguntar("Campo", "padrao") == "digitado"

    def test_espacos_sao_removidos(self):
        entrada, _ = _responder(["  com espaco  "])
        with entrada:
            assert setup._perguntar("Campo") == "com espaco"

    def test_campo_opcional_aceita_vazio(self):
        entrada, _ = _responder([""])
        with entrada:
            assert setup._perguntar("Campo", obrigatorio=False) == ""

    def test_campo_opcional_aceita_valor(self):
        entrada, _ = _responder(["abc"])
        with entrada:
            assert setup._perguntar("Campo", obrigatorio=False) == "abc"

    def test_campo_opcional_com_padrao_usa_padrao(self):
        entrada, _ = _responder([""])
        with entrada:
            assert setup._perguntar("Campo", "12", obrigatorio=False) == "12"

    def test_campo_obrigatorio_nao_aceita_vazio(self):
        """Reentra no laço até receber algo, descartando as respostas vazias."""
        entrada, saida = _responder(["", "", "final"])
        with entrada, mock.patch("sys.stdout", new=saida):
            assert setup._perguntar("Campo") == "final"

        texto = saida.getvalue()
        assert texto.count("Preencha este campo") == 2

    def test_eof_devolve_padrao(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            assert setup._perguntar("Campo", "padrao") == "padrao"

    def test_eof_em_opcional_devolve_vazio(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            assert setup._perguntar("Campo", obrigatorio=False) == ""


class TestConfigurarBackup:
    def test_id_em_branco_significa_drive_inteiro(self):
        """Regressão: antes, deixar o ID vazio repetia a pergunta para sempre."""
        resultado, saida = _configurar_backup(["/tmp/backup", "", "n"])

        assert resultado.folder_id == ""
        assert "Preencha este campo" not in saida

    def test_id_preenchido_e_aceito(self):
        resultado, _ = _configurar_backup(["/tmp/backup", "1a2B3c", "n"])

        assert resultado.folder_id == "1a2B3c"

    def test_destino_vazio_usa_padrao(self):
        resultado, _ = _configurar_backup(["", "", "n"])

        assert resultado.destination.endswith("agebackup")
        assert resultado.destination != ""

    def test_shared_drives_pode_ser_ligado(self):
        resultado, _ = _configurar_backup(["/tmp/backup", "", "s"])

        assert resultado.shared_drives is True

    def test_shared_drives_aceita_nao(self):
        resultado, _ = _configurar_backup(["/tmp/backup", "", "n"])

        assert resultado.shared_drives is False

    def test_shared_drives_vazio_mantem_padrao(self):
        resultado, _ = _configurar_backup(["/tmp/backup", "", ""])

        assert resultado.shared_drives is False


class TestPerguntarBool:
    def test_s_e_sim(self):
        for resposta in ("s", "S", "sim", "y", "yes"):
            with mock.patch("builtins.input", return_value=resposta):
                assert setup._perguntar_bool("Campo", False) is True

    def test_n_e_nao(self):
        for resposta in ("n", "N", "nao", "não", "no"):
            with mock.patch("builtins.input", return_value=resposta):
                assert setup._perguntar_bool("Campo", True) is False

    def test_vazio_mantem_padrao_true(self):
        with mock.patch("builtins.input", return_value=""):
            assert setup._perguntar_bool("Campo", True) is True

    def test_vazio_mantem_padrao_false(self):
        with mock.patch("builtins.input", return_value=""):
            assert setup._perguntar_bool("Campo", False) is False

    def test_resposta_invalida_repergunta(self):
        entrada, saida = _responder(["talvez", "s"])
        with entrada, mock.patch("sys.stdout", new=saida):
            assert setup._perguntar_bool("Campo", False) is True

        assert "Responda com s" in saida.getvalue()

    def test_eof_devolve_padrao(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            assert setup._perguntar_bool("Campo", True) is True


class TestConfigurarBackupReaproveitaExistente:
    """Regressão: o assistente não pode apagar valores já configurados."""

    def test_sem_config_anterior_usa_padrao(self):
        resultado, saida = _configurar_backup(["", "", "n"])

        assert resultado.destination.endswith("agebackup")
        assert "Configuracao atual" not in saida

    def test_mostra_o_destino_atual(self):
        atual = BackupConfig(destination="/dados/backup")

        resultado, saida = _configurar_backup(["", "", "n"], atual)

        assert resultado.destination == "/dados/backup"
        assert "Configuracao atual: /dados/backup" in saida

    def test_enter_mantem_o_destino_atual(self):
        atual = BackupConfig(destination="/dados/backup")

        resultado, _ = _configurar_backup(["", "", "n"], atual)

        assert resultado.destination == "/dados/backup"

    def test_enter_mantem_a_pasta_atual(self):
        """Regressão: antes, o Enter no ID apagava a pasta configurada."""
        atual = BackupConfig(destination="/d", folder_id="PASTA_123")

        resultado, saida = _configurar_backup(["", "", "n"], atual)

        assert resultado.folder_id == "PASTA_123"
        assert "Configuracao atual: PASTA_123" in saida

    def test_guion_limpa_a_pasta_para_drive_inteiro(self):
        """Sem isso, nao havia como voltar ao Drive inteiro apos configurar."""
        atual = BackupConfig(destination="/d", folder_id="PASTA_123")

        resultado, _ = _configurar_backup(["", "-", "n"], atual)

        assert resultado.folder_id == ""

    def test_guion_em_campo_vazio_fica_vazio(self):
        resultado, _ = _configurar_backup(["", "", "n"])

        assert resultado.folder_id == ""

    def test_enter_mantem_shared_drives(self):
        atual = BackupConfig(destination="/d", include_shared_drives=True)

        resultado, saida = _configurar_backup(["", "", ""], atual)

        assert resultado.shared_drives is True
        assert "Configuracao atual: sim" in saida

    def test_shared_drives_desligado_explicitamente(self):
        atual = BackupConfig(destination="/d", include_shared_drives=True)

        resultado, _ = _configurar_backup(["", "", "n"], atual)

        assert resultado.shared_drives is False

    def test_destino_pode_ser_trocado(self):
        atual = BackupConfig(destination="/antigo")

        resultado, _ = _configurar_backup(["/novo", "", "n"], atual)

        assert resultado.destination == "/novo"


# ---------------------------------------------------------------------------
# Passo 4: pasta, rotação e retenção dos logs
# ---------------------------------------------------------------------------


def _configurar_logs(entradas, existente=None):
    entrada, saida = _responder(entradas)
    with entrada, mock.patch("sys.stdout", new=saida):
        resultado = setup.configurar_logs(existente)
    return resultado, saida.getvalue()


class TestConfigurarLogs:
    def test_padrao_usa_subpasta_logs(self):
        resultado, _ = _configurar_logs(["", "7", "s"])

        assert resultado.directory == "logs"
        assert resultado.keep_logs == 7
        assert resultado.compress is True

    def test_pasta_personalizada(self):
        resultado, _ = _configurar_logs(["meus-logs", "6", "n"])

        assert resultado.directory == "meus-logs"
        assert resultado.keep_logs == 6
        assert resultado.compress is False

    def test_limpar_grava_na_raiz(self):
        resultado, _ = _configurar_logs(["-", "7", "s"])

        assert resultado.directory == ""

    def test_caminho_absoluto_volta_ao_padrao(self):
        resultado, _ = _configurar_logs(["/etc", "7", "s"])

        assert resultado.directory == "logs"

    def test_enter_mantem_a_pasta_atual(self):
        existente = LogConfig(directory="logs", keep_logs=3)

        resultado, _ = _configurar_logs(["", "n"], existente)

        assert resultado.directory == "logs"
        assert resultado.keep_logs == 3

    def test_pasta_nova_com_retencao_mantida(self):
        existente = LogConfig(directory="logs", keep_logs=3, compress=False)

        resultado, _ = _configurar_logs(["historico", "n"], existente)

        assert resultado.directory == "historico"
        assert resultado.keep_logs == 3
        assert resultado.compress is False


# ---------------------------------------------------------------------------
# Passo 1: escolha do método de autenticação
# ---------------------------------------------------------------------------


def _conta_anterior(**overrides) -> Config:
    dados = {"email": "u@e.com", "auth_method": config_mod.AUTH_ADC, "ask_reuse": True}
    dados.update(overrides)
    return Config(account=AccountConfig(**dados))


def _configurar_conta(
    entradas, anterior, conexao=(True, "Conectado como u@e.com", "u@e.com")
):
    entrada, saida = _responder(entradas)
    with (
        entrada,
        mock.patch("sys.stdout", new=saida),
        mock.patch.object(config_mod, "verify_connection", lambda *a, **k: conexao),
        mock.patch.object(config_mod, "gcloud_installed", lambda: True),
        mock.patch.object(config_mod, "gcloud_path", lambda: "/usr/bin/gcloud"),
        mock.patch.object(config_mod, "adc_present", lambda: True),
        mock.patch.object(config_mod, "adc_info", lambda: {"email": "u@e.com"}),
        mock.patch.object(config_mod, "login", lambda *a, **k: True),
        mock.patch.object(config_mod, "in_wsl", lambda: True),
    ):
        form = setup.configurar_conta(anterior)
    return form, saida.getvalue()


class TestConfigurarContaReuso:
    def test_sem_anterior_nao_pergunta_reuso(self, tmp_path):
        chave = tmp_path / "k.json"
        chave.write_text(
            '{"type": "service_account", "client_email": "x@y.iam"}', encoding="utf-8"
        )

        form, saida = _configurar_conta(["2", str(chave)], None)

        assert form.reuse_existing is True
        assert "Usar a configuracao existente?" not in saida

    def test_aceitar_reuso_e_manter_com_credenciais_validas(self):
        form, saida = _configurar_conta(["s", ""], _conta_anterior())

        assert form.reuse_existing is True
        assert form.auth_method == "manter"
        assert "Usar a configuracao existente?" in saida

    def test_recusar_reuso_ignora_config_anterior(self):
        form, saida = _configurar_conta(["n", "1", "n"], _conta_anterior())

        assert form.reuse_existing is False
        assert "IGNORADA" in saida

    def test_credenciais_invalidas_nao_oferecem_manter(self):
        """Se a autenticação salva falhou, 'manter' não pode ser o padrão."""
        form, saida = _configurar_conta(
            ["s", "1", "n"],
            _conta_anterior(),
            conexao=(False, "Falha na conexão: sem credenciais", ""),
        )

        assert form.auth_method == config_mod.AUTH_ADC
        assert "NAO esta funcionando" in saida
        assert "Manter a autenticacao atual" not in saida

    def test_credenciais_invalidas_rejeitam_opcao_3(self):
        form, saida = _configurar_conta(
            ["s", "3", "1", "n"],
            _conta_anterior(),
            conexao=(False, "quebrado", ""),
        )

        assert form.auth_method == config_mod.AUTH_ADC
        assert "Responda com 1, 2 ou 3." in saida

    def test_ask_reuse_desligado_pula_a_pergunta(self):
        form, saida = _configurar_conta([""], _conta_anterior(ask_reuse=False))

        assert form.reuse_existing is True
        assert form.auth_method == "manter"
        assert "Usar a configuracao existente?" not in saida
        assert "automaticamente" in saida


class TestConfigurarContaServiceAccount:
    def _chave(
        self,
        tmp_path,
        tipo="service_account",
        email="sa@projeto.iam.gserviceaccount.com",
    ):
        chave = tmp_path / "chave.json"
        chave.write_text(
            json.dumps({"type": tipo, "client_email": email}), encoding="utf-8"
        )
        return chave

    def _protegida(self, chave):
        """Caminho final da chave: cópia protegida dentro do CONFIG_DIR."""
        return config_mod.CONFIG_DIR / chave.name

    def test_service_account_valida(self, tmp_path):
        chave = self._chave(tmp_path)

        form, _ = _configurar_conta(["2", str(chave)], None)

        assert form.auth_method == config_mod.AUTH_SERVICE_ACCOUNT
        assert form.service_account_key_path == str(self._protegida(chave))
        assert form.email == "sa@projeto.iam.gserviceaccount.com"

    def test_chave_e_copiada_para_o_config_dir_com_permissao_restrita(self, tmp_path):
        chave = self._chave(tmp_path)

        form, _ = _configurar_conta(["2", str(chave)], None)

        protegida = Path(form.service_account_key_path)
        assert protegida.exists()
        assert protegida.parent == config_mod.CONFIG_DIR
        assert protegida.stat().st_mode & 0o777 == 0o600

    def test_arquivo_inexistente_repergunta(self, tmp_path):
        chave = self._chave(tmp_path)

        form, saida = _configurar_conta(["2", "/nao/existe.json", str(chave)], None)

        assert form.service_account_key_path == str(self._protegida(chave))
        assert "Arquivo nao encontrado" in saida

    def test_caminho_relativo_vira_copia_absoluta_e_protegida(
        self, tmp_path, monkeypatch
    ):
        chave = self._chave(tmp_path)
        monkeypatch.chdir(tmp_path)

        form, _ = _configurar_conta(["2", "chave.json"], None)

        protegida = Path(form.service_account_key_path)
        assert protegida.is_absolute()
        assert protegida == self._protegida(chave)

    def test_json_que_nao_e_service_account_e_rejeitado(self, tmp_path):
        ruim = self._chave(tmp_path, tipo="authorized_user")
        bom = tmp_path / "bom.json"
        bom.write_text(
            '{"type": "service_account", "client_email": "ok@x.iam"}', encoding="utf-8"
        )

        form, saida = _configurar_conta(["2", str(ruim), str(bom)], None)

        assert form.service_account_key_path == str(self._protegida(bom))
        assert "nao parece ser uma chave de Service Account" in saida

    def test_json_invalido_e_rejeitado(self, tmp_path):
        ruim = tmp_path / "quebrado.json"
        ruim.write_text("{nao eh json", encoding="utf-8")
        bom = self._chave(tmp_path)

        form, saida = _configurar_conta(["2", str(ruim), str(bom)], None)

        assert form.service_account_key_path == str(self._protegida(bom))
        assert "Nao foi possivel ler o JSON" in saida


# ---------------------------------------------------------------------------
# Passo 3/4: validação e a opção de desligar a pergunta de reuso
# ---------------------------------------------------------------------------


class TestWizardDesligaPerguntaDeReuso:
    def _rodar(self, entradas, conexao=(True, "Conectado como u@e.com", "u@e.com")):
        entrada, saida = _responder(entradas)
        with (
            entrada,
            mock.patch("sys.stdout", new=saida),
            mock.patch.object(config_mod, "verify_connection", lambda *a, **k: conexao),
            mock.patch.object(config_mod, "gcloud_installed", lambda: True),
            mock.patch.object(config_mod, "gcloud_path", lambda: "/usr/bin/gcloud"),
            mock.patch.object(config_mod, "adc_present", lambda: True),
            mock.patch.object(config_mod, "adc_info", lambda: {"email": "u@e.com"}),
            mock.patch.object(config_mod, "status", lambda: _status_fake()),
        ):
            codigo = setup.wizard()
        return codigo, saida.getvalue()

    def test_resposta_n_grava_ask_reuse_false(self):
        # 1) método ADC  2) não relogar  3-5) destino/pasta/shared
        # 6) pasta dos logs (Enter = "logs")  7) não alterar retenção
        # 8) não perguntar reuso no futuro
        codigo, _ = self._rodar(["1", "n", "", "", "n", "", "", "n"])

        assert codigo == 0
        salvo = config_mod.load()
        assert salvo.account.verified is True
        assert salvo.account.ask_reuse is False
        assert salvo.logs.directory == "logs"

    def test_resposta_s_mantem_pergunta_ligada(self):
        codigo, _ = self._rodar(["1", "n", "", "", "n", "", "", "s"])

        assert codigo == 0
        assert config_mod.load().account.ask_reuse is True

    def test_conexao_falha_mantem_pergunta_ligada(self):
        codigo, _ = self._rodar(
            ["1", "n", "", "", "n", "", ""],
            conexao=(False, "Falha na conexão: sem credenciais", ""),
        )

        assert codigo == 0
        salvo = config_mod.load()
        assert salvo.account.verified is False
        assert salvo.account.ask_reuse is True

    def test_email_da_api_sobrescreve_palpite_do_adc(self):
        """O ADC do gcloud não guarda o e-mail: a fonte é a resposta da API."""
        entrada, saida = _responder(["1", "n", "", "", "n", "", "", "s"])
        with (
            entrada,
            mock.patch("sys.stdout", new=saida),
            mock.patch.object(
                config_mod,
                "verify_connection",
                lambda *a, **k: (
                    True,
                    "Conectado como real@empresa.com",
                    "real@empresa.com",
                ),
            ),
            mock.patch.object(config_mod, "gcloud_installed", lambda: True),
            mock.patch.object(config_mod, "gcloud_path", lambda: "/usr/bin/gcloud"),
            mock.patch.object(config_mod, "adc_present", lambda: True),
            mock.patch.object(config_mod, "adc_info", lambda: {"email": ""}),
            mock.patch.object(config_mod, "status", lambda: _status_fake()),
        ):
            setup.wizard()

        assert config_mod.load().account.email == "real@empresa.com"


def _status_fake():
    return {
        "gcloud_installed": True,
        "gcloud_path": "/usr/bin/gcloud",
        "adc_present": True,
        "adc_info": {"email": "u@e.com"},
        "config_file": config_mod.CONFIG_FILE,
        "config_exists": False,
        "config": None,
        "chave_presente": False,
    }


class TestMostrarStatus:
    def _salvar_sa(self, home_isolado, caminho_chave, verified=True):
        config_mod.save(
            Config(
                account=AccountConfig(
                    auth_method=config_mod.AUTH_SERVICE_ACCOUNT,
                    email="sa@projeto.iam.gserviceaccount.com",
                    service_account_key_path=str(caminho_chave),
                    verified=verified,
                )
            )
        )

    def _capturar(self):
        saida = io.StringIO()
        with mock.patch("sys.stdout", new=saida):
            setup.mostrar_status()
        return saida.getvalue()

    def test_chave_ausente_nao_aparece_como_autenticada(self, home_isolado):
        self._salvar_sa(home_isolado, home_isolado / "sumiu.json")

        texto = self._capturar()

        assert "chave de Service Account ausente" in texto
        assert "uv run agebackup-setup" in texto

    def test_chave_presente_mostra_autenticada(self, home_isolado):
        chave = home_isolado / "chave.json"
        chave.write_text("{}", encoding="utf-8")
        self._salvar_sa(home_isolado, chave)

        texto = self._capturar()

        assert "autenticada  : sim" in texto
        assert "ausente" not in texto
