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


class TestListarGrandes:
    def _log(self, tmp_path):
        from agebackup import falhas as falhas_mod

        pasta = tmp_path / "logs"
        pasta.mkdir()
        falhas_mod.registrar(
            pasta,
            [
                falhas_mod.Falha(
                    nome="Apresentacao grande",
                    categoria=falhas_mod.CAT_GRANDE,
                    drive_id="ABC123",
                ),
                falhas_mod.Falha(
                    nome="Bloqueado",
                    categoria=falhas_mod.CAT_BLOQUEADO,
                    drive_id="XYZ",
                ),
            ],
        )
        return pasta

    def _manifesto(self, tmp_path, drive_id="ABC123"):
        from agebackup import manifest as manifest_mod

        manifest_mod.salvar(
            tmp_path,
            {
                "Apresentacao grande.pdf": manifest_mod.Registro(
                    drive_id=drive_id,
                    nome="Apresentacao grande",
                    tamanho=1,
                    modificado="2026-01-01T00:00:00+00:00",
                    baixado_em="2026-01-01T00:00:00+00:00",
                )
            },
        )

    def test_lista_apenas_grandes_com_link(self, tmp_path, capsys):
        self._log(tmp_path)

        cli.listar_grandes(_config(tmp_path), tmp_path)

        saida = capsys.readouterr().out
        assert "Apresentacao grande" in saida
        assert "https://drive.google.com/file/d/ABC123/view" in saida
        assert "Bloqueado" not in saida

    def test_esconde_original_ja_recuperado(self, tmp_path, capsys):
        self._log(tmp_path)
        self._manifesto(tmp_path)
        (tmp_path / "Apresentacao grande.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "Apresentacao grande.pptx").write_bytes(b"PK")

        cli.listar_grandes(_config(tmp_path), tmp_path)

        saida = capsys.readouterr().out
        assert "ABC123" not in saida
        assert "já foram recuperados" in saida

    def test_mostra_pendente_sem_original(self, tmp_path, capsys):
        self._log(tmp_path)
        self._manifesto(tmp_path)
        (tmp_path / "Apresentacao grande.pdf").write_bytes(b"%PDF-1.4")

        cli.listar_grandes(_config(tmp_path), tmp_path)

        saida = capsys.readouterr().out
        assert "Apresentacao grande" in saida
        assert "https://drive.google.com/file/d/ABC123/view" in saida

    def test_lista_vazia_avisa(self, tmp_path, capsys):
        (tmp_path / "logs").mkdir()

        cli.listar_grandes(_config(tmp_path), tmp_path)

        assert "Nenhum arquivo pendente" in capsys.readouterr().out

    def test_main_despacha_listar_grandes(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            cli, "carregar_configuracao", lambda: _config(tmp_path / "backup")
        )
        monkeypatch.setattr("sys.argv", ["agebackup-backup", "--listar-grandes"])

        codigo = cli.main()

        assert codigo == 0
        assert "Originais grandes" in capsys.readouterr().out

    def test_ajuda_mostra_listar_grandes(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["agebackup-backup", "--help"])

        cli.main()

        assert "--listar-grandes" in capsys.readouterr().out


class TestMostrarPendentes:
    def test_separa_grandes_das_falhas(self, capsys):
        from agebackup import falhas as falhas_mod

        registros = [
            falhas_mod.Falha(
                nome="Grande", categoria=falhas_mod.CAT_GRANDE, drive_id="ABC"
            ),
            falhas_mod.Falha(nome="Quebrado", categoria=falhas_mod.CAT_BLOQUEADO),
        ]

        cli.mostrar_erros(registros)
        cli.mostrar_pendentes(registros)

        saida = capsys.readouterr().out
        # A falha real aparece na seção de falhas; o grande, na de pendentes.
        assert "Falhas (1)" in saida
        assert "Quebrado" in saida
        assert "Originais grandes, guardados em PDF (1)" in saida
        assert "https://drive.google.com/file/d/ABC/view" in saida


class TestReconstruirGrandes:
    def test_despacha_e_reporta(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            cli, "carregar_configuracao", lambda: _config(tmp_path / "backup")
        )
        monkeypatch.setattr(cli, "get_service", lambda: object())
        chamadas = {}

        def fake(service, config, destino):
            chamadas["destino"] = destino
            print("  reconstruído x.reconstruido.pptx")
            return 1, 0

        monkeypatch.setattr(cli, "reconstruir_pendentes", fake)
        monkeypatch.setattr("sys.argv", ["agebackup-backup", "--reconstruir-grandes"])

        codigo = cli.main()

        assert codigo == 0
        saida = capsys.readouterr().out
        assert "reconstruído x.reconstruido.pptx" in saida
        assert "1 recuperado(s), 0 falha(s)" in saida
        assert chamadas["destino"] == tmp_path / "backup"

    def test_falha_retorna_codigo_1(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            cli, "carregar_configuracao", lambda: _config(tmp_path / "backup")
        )
        monkeypatch.setattr(cli, "get_service", lambda: object())
        monkeypatch.setattr(cli, "reconstruir_pendentes", lambda *a, **k: (0, 2))
        monkeypatch.setattr("sys.argv", ["agebackup-backup", "--reconstruir-grandes"])

        codigo = cli.main()

        assert codigo == 1
        saida = capsys.readouterr().out
        assert "queda de rede" in saida or "indisponivel" in saida

    def test_ajuda_mostra_reconstruir_grandes(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["agebackup-backup", "--help"])

        cli.main()

        assert "--reconstruir-grandes" in capsys.readouterr().out
