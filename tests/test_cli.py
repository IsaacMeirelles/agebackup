"""Testes do comando de backup e das telas de ajuda."""

from pathlib import Path

from agebackup import cli, setup
from agebackup.config import AccountConfig, BackupConfig, Config


def _config(destino) -> Config:
    return Config(
        account=AccountConfig(email="u@e.com"),
        backup=BackupConfig(destination=str(destino)),
    )


class TestAjuda:
    def test_backup_help_mostra_uso_e_nao_executa(self, monkeypatch, capsys):
        executou = {"sim": False}
        monkeypatch.setattr(
            cli, "executar_backup", lambda *a, **k: executou.__setitem__("sim", True)
        )
        monkeypatch.setattr("sys.argv", ["agebackup-backup", "--help"])

        codigo = cli.main()

        assert codigo == 0
        assert executou["sim"] is False
        assert "Uso: agebackup-backup" in capsys.readouterr().out

    def test_setup_help_mostra_uso_e_nao_roda_wizard(self, monkeypatch, capsys):
        rodou = {"sim": False}
        monkeypatch.setattr(
            setup, "wizard", lambda: rodou.__setitem__("sim", True) or 0
        )
        monkeypatch.setattr("sys.argv", ["agebackup-setup", "--help"])

        codigo = setup.main()

        assert codigo == 0
        assert rodou["sim"] is False
        assert "Uso: agebackup-setup" in capsys.readouterr().out


class TestDestinoInacessivel:
    def test_erro_amigavel_em_vez_de_traceback(self, monkeypatch, tmp_path, capsys):
        destino = tmp_path / "sem" / "permissao"
        monkeypatch.setattr(cli, "carregar_configuracao", lambda: _config(destino))
        monkeypatch.setattr("sys.argv", ["agebackup-backup"])

        def falha_mkdir(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "mkdir", falha_mkdir)

        codigo = cli.main()

        assert codigo == 1
        erro = capsys.readouterr().err
        assert "nao foi possivel usar o destino" in erro
        assert "uv run agebackup-setup" in erro
