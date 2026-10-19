"""Testes da compactação do backup em arquivo .tar.gz."""

import tarfile

from agebackup import compactacao
from agebackup.compactacao import compactar
from agebackup.config import (
    BackupConfig,
    CompactacaoConfig,
    Config,
    ConfigError,
)


def _backup(tmp_path):
    """Monta uma pasta de backup pequena e representativa."""
    origem = tmp_path / "bkps"
    (origem / "Didaticos" / "Temp").mkdir(parents=True)
    (origem / "Didaticos" / "a.txt").write_bytes(b"a" * 10)
    (origem / "Didaticos" / "Temp" / "b.txt").write_bytes(b"b" * 20)
    (origem / ".agebackup-manifest.json").write_bytes(b"{}")
    return origem


def _config(destino, destino_arquivos="", manter=0) -> Config:
    return Config(
        backup=BackupConfig(destination=str(destino)),
        compactacao=CompactacaoConfig(destino=destino_arquivos, manter=manter),
    )


class TestCompactar:
    def test_cria_arquivo_tar_gz(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"

        resultado = compactar(origem, destino_dir)

        assert resultado.erro == ""
        assert resultado.arquivo is not None
        assert resultado.arquivo.parent == destino_dir
        assert resultado.arquivo.name.startswith("bkps-")
        assert resultado.arquivo.suffixes == [".tar", ".gz"]
        assert resultado.arquivo.exists()
        assert resultado.itens == 3

    def test_conteudo_confere_com_a_origem(self, tmp_path):
        origem = _backup(tmp_path)

        resultado = compactar(origem, tmp_path / "arquivos")

        with tarfile.open(resultado.arquivo) as pacote:
            pacote.extractall(tmp_path / "extraido", filter="data")

        extraido = tmp_path / "extraido" / "bkps"
        assert (extraido / "Didaticos" / "a.txt").read_bytes() == b"a" * 10
        assert (extraido / "Didaticos" / "Temp" / "b.txt").read_bytes() == b"b" * 20
        assert (extraido / ".agebackup-manifest.json").read_bytes() == b"{}"

    def test_nome_customizado(self, tmp_path):
        origem = _backup(tmp_path)

        resultado = compactar(origem, tmp_path / "arquivos", nome="retrato")

        assert resultado.arquivo.name.startswith("retrato-")

    def test_exclui_temporarios(self, tmp_path):
        origem = _backup(tmp_path)
        (origem / "Didaticos" / "parcial.txt.tmp").write_bytes(b"lixo")

        resultado = compactar(origem, tmp_path / "arquivos")

        with tarfile.open(resultado.arquivo) as pacote:
            nomes = pacote.getnames()

        assert not any(nome.endswith(".tmp") for nome in nomes)
        assert resultado.itens == 3

    def test_dry_run_nao_grava(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"

        resultado = compactar(origem, destino_dir, dry_run=True)

        assert resultado.erro == ""
        assert resultado.arquivo.parent == destino_dir
        assert resultado.itens == 3
        assert not destino_dir.exists()

    def test_origem_inexistente_da_erro(self, tmp_path):
        resultado = compactar(tmp_path / "nao_existe", tmp_path / "arquivos")

        assert resultado.erro != ""
        assert resultado.arquivo is None

    def test_destino_dentro_da_origem_da_erro(self, tmp_path):
        origem = _backup(tmp_path)

        resultado = compactar(origem, origem / "dentro")

        assert "nao pode ficar dentro" in resultado.erro
        assert resultado.arquivo is None

    def test_manter_zero_guarda_todos(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        for stamp in ("20260101-000000", "20260201-000000"):
            (destino_dir / f"bkps-{stamp}.tar.gz").write_bytes(b"x")

        compactar(origem, destino_dir, manter=0)

        assert len(list(destino_dir.glob("bkps-*.tar.gz"))) == 3

    def test_retencao_apaga_os_mais_antigos(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        for stamp in ("20260101-000000", "20260201-000000", "20260301-000000"):
            (destino_dir / f"bkps-{stamp}.tar.gz").write_bytes(b"x")

        resultado = compactar(origem, destino_dir, manter=2)

        restantes = sorted(p.name for p in destino_dir.glob("bkps-*.tar.gz"))
        assert len(restantes) == 2
        assert "bkps-20260101-000000.tar.gz" not in restantes
        assert "bkps-20260201-000000.tar.gz" not in restantes
        assert len(resultado.removidos) == 2


class TestListar:
    def test_lista_do_mais_recente_ao_mais_antigo(self, tmp_path, capsys):
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        for stamp in ("20260101-000000", "20260301-000000"):
            (destino_dir / f"bkps-{stamp}.tar.gz").write_bytes(b"x")

        compactacao._listar(
            _config(tmp_path / "bkps", str(destino_dir)), tmp_path / "bkps"
        )

        saida = capsys.readouterr().out
        assert saida.index("20260301") < saida.index("20260101")

    def test_vazio_avisa(self, tmp_path, capsys):
        compactacao._listar(
            _config(tmp_path / "bkps", str(tmp_path / "arquivos")), tmp_path / "bkps"
        )

        assert "Nenhum arquivo ainda" in capsys.readouterr().out


class TestMain:
    def test_help_nao_executa(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--help"])

        codigo = compactacao.main()

        assert codigo == 0
        assert "Uso: agebackup-compactar" in capsys.readouterr().out

    def test_sem_config_avisa_e_sai_um(self, monkeypatch, capsys):
        def explode() -> Config:
            raise ConfigError("sem config")

        monkeypatch.setattr(compactacao, "carregar_configuracao", explode)
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        assert compactacao.main() == 1
        assert "sem config" in capsys.readouterr().err

    def test_compacta_com_a_configuracao(self, monkeypatch, tmp_path, capsys):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir)),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        codigo = compactacao.main()

        assert codigo == 0
        assert "Compactar backup" in capsys.readouterr().out
        assert list(destino_dir.glob("bkps-*.tar.gz"))

    def test_destino_padrao_e_a_pasta_acima(self, monkeypatch, tmp_path):
        origem = _backup(tmp_path)  # tmp_path/bkps
        monkeypatch.setattr(
            compactacao, "carregar_configuracao", lambda: _config(origem)
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        assert compactacao.main() == 0
        assert list(tmp_path.glob("bkps-*.tar.gz"))

    def test_destino_por_opcao(self, monkeypatch, tmp_path):
        origem = _backup(tmp_path)
        outro = tmp_path / "outro"
        monkeypatch.setattr(
            compactacao, "carregar_configuracao", lambda: _config(origem)
        )
        monkeypatch.setattr(
            "sys.argv", ["agebackup-compactar", "--destino", str(outro)]
        )

        assert compactacao.main() == 0
        assert list(outro.glob("bkps-*.tar.gz"))

    def test_dry_run_nao_grava(self, monkeypatch, tmp_path, capsys):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir)),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--dry-run"])

        assert compactacao.main() == 0
        assert not destino_dir.exists()
        assert "Simulacao" in capsys.readouterr().out

    def test_manter_invalido_avisa(self, monkeypatch, tmp_path, capsys):
        origem = _backup(tmp_path)
        monkeypatch.setattr(
            compactacao, "carregar_configuracao", lambda: _config(origem)
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--manter", "muitos"])

        assert compactacao.main() == 1
        assert "--manter" in capsys.readouterr().err

    def test_listar_por_opcao(self, monkeypatch, tmp_path, capsys):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        (destino_dir / "bkps-20260101-000000.tar.gz").write_bytes(b"x")
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir)),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--listar"])

        assert compactacao.main() == 0
        assert "bkps-20260101-000000.tar.gz" in capsys.readouterr().out

    def test_backup_ausente_avisa(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(tmp_path / "nao_existe"),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        assert compactacao.main() == 1
        assert "backup nao encontrado" in capsys.readouterr().err
