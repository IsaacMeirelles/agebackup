"""Testes da compactação do backup em arquivo .tar.gz."""

import tarfile
from datetime import datetime

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


def _quando(ano, mes, dia, hora=0, minuto=0):
    """Momento fixo, em hora local, para as decisões de full/incremental."""
    return datetime(ano, mes, dia, hora, minuto)


def _envelhecer(arquivo, segundos):
    """Recua o mtime de um arquivo, simulando tempo passado desde a criação."""
    import os

    quando = arquivo.stat().st_mtime + segundos
    os.utime(arquivo, (quando, quando))


def _config(destino, destino_arquivos="", manter=0, prefixo="") -> Config:
    return Config(
        backup=BackupConfig(destination=str(destino)),
        compactacao=CompactacaoConfig(
            destino=destino_arquivos, manter=manter, prefixo=prefixo
        ),
    )


class TestCompactar:
    def test_cria_arquivo_tar_gz(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"

        resultado = compactar(origem, destino_dir)

        assert resultado.erro == ""
        assert resultado.arquivo is not None
        assert resultado.arquivo.parent == destino_dir
        assert resultado.arquivo.name.startswith("bkps_")
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

        assert resultado.arquivo.name.startswith("retrato_")

    def test_prefixo_entra_entre_o_nome_e_a_data(self, tmp_path):
        origem = _backup(tmp_path)

        resultado = compactar(origem, tmp_path / "arquivos", prefixo="nuvem")

        nome = resultado.arquivo.name
        assert nome.startswith("bkps_nuvem_")
        assert nome.endswith(".tar.gz")

    def test_sem_prefixo_mantem_o_padrao(self, tmp_path):
        origem = _backup(tmp_path)

        resultado = compactar(origem, tmp_path / "arquivos", prefixo="")

        assert resultado.arquivo.name.startswith("bkps_")
        assert "nuvem" not in resultado.arquivo.name

    def test_prefixo_invalido_e_ignorado(self, tmp_path):
        origem = _backup(tmp_path)

        resultado = compactar(origem, tmp_path / "arquivos", prefixo="a/b")

        assert resultado.arquivo.name.startswith("bkps_")
        assert "a/b" not in resultado.arquivo.name

    def test_nome_carrega_data_e_hora(self, tmp_path):
        """O sufixo final é AAAAMMDD-HHMM (ex.: bkps_RSKO_20261020-2151.tar.gz)."""
        origem = _backup(tmp_path)

        resultado = compactar(origem, tmp_path / "arquivos", prefixo="RSKO")

        nome = resultado.arquivo.name
        assert nome.startswith("bkps_RSKO_")
        sufixo = nome[len("bkps_RSKO_") : -len(".tar.gz")]
        assert len(sufixo) == 13
        assert sufixo[8] == "-"
        assert sufixo[:8].isdigit()
        assert sufixo[9:].isdigit()
        assert resultado.arquivo.suffixes == [".tar", ".gz"]

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
        for data in ("20200101", "20200201"):
            (destino_dir / f"bkps_{data}.tar.gz").write_bytes(b"x")

        compactar(origem, destino_dir, manter=0)

        assert len(list(destino_dir.glob("bkps_*.tar.gz"))) == 3

    def test_retencao_apaga_os_mais_antigos(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        for data in ("20200101", "20200201", "20200301"):
            (destino_dir / f"bkps_{data}.tar.gz").write_bytes(b"x")

        resultado = compactar(origem, destino_dir, manter=2)

        restantes = sorted(p.name for p in destino_dir.glob("bkps_*.tar.gz"))
        assert len(restantes) == 2
        assert "bkps_20200101.tar.gz" not in restantes
        assert "bkps_20200201.tar.gz" not in restantes
        assert len(resultado.removidos) == 2

    def test_retencao_considera_o_prefixo(self, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        for data in ("20200101", "20200201", "20200301"):
            (destino_dir / f"bkps_nuvem_{data}.tar.gz").write_bytes(b"x")

        resultado = compactar(origem, destino_dir, manter=2, prefixo="nuvem")

        restantes = sorted(p.name for p in destino_dir.glob("bkps_*.tar.gz"))
        assert len(restantes) == 2
        assert "bkps_nuvem_20200101.tar.gz" not in restantes
        assert len(resultado.removidos) == 2


class TestListar:
    def test_lista_do_mais_recente_ao_mais_antigo(self, tmp_path, capsys):
        destino_dir = tmp_path / "arquivos"
        destino_dir.mkdir()
        for data in ("20200101", "20200301"):
            (destino_dir / f"bkps_{data}.tar.gz").write_bytes(b"x")

        compactacao._listar(
            _config(tmp_path / "bkps", str(destino_dir)), tmp_path / "bkps"
        )

        saida = capsys.readouterr().out
        assert saida.index("20200301") < saida.index("20200101")

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
        assert list(destino_dir.glob("bkps_*.tar.gz"))

    def test_destino_padrao_e_a_pasta_acima(self, monkeypatch, tmp_path):
        origem = _backup(tmp_path)  # tmp_path/bkps
        monkeypatch.setattr(
            compactacao, "carregar_configuracao", lambda: _config(origem)
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        assert compactacao.main() == 0
        assert list(tmp_path.glob("bkps_*.tar.gz"))

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
        assert list(outro.glob("bkps_*.tar.gz"))

    def test_prefixo_por_config(self, monkeypatch, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir), prefixo="nuvem"),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        assert compactacao.main() == 0
        assert list(destino_dir.glob("bkps_nuvem_*.tar.gz"))

    def test_prefixo_por_opcao_sobrepoe_o_config(self, monkeypatch, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir), prefixo="antigo"),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--prefixo", "nuvem"])

        assert compactacao.main() == 0
        assert list(destino_dir.glob("bkps_nuvem_*.tar.gz"))
        assert not list(destino_dir.glob("bkps_antigo_*.tar.gz"))

    def test_prefixo_vazio_na_opcao_limpa_o_config(self, monkeypatch, tmp_path):
        origem = _backup(tmp_path)
        destino_dir = tmp_path / "arquivos"
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir), prefixo="nuvem"),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--prefixo", ""])

        assert compactacao.main() == 0
        arquivos = list(destino_dir.glob("bkps_*.tar.gz"))
        assert len(arquivos) == 1
        assert "nuvem" not in arquivos[0].name

    def test_prefixo_invalido_na_opcao_avisa(self, monkeypatch, tmp_path, capsys):
        origem = _backup(tmp_path)
        monkeypatch.setattr(
            compactacao, "carregar_configuracao", lambda: _config(origem)
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--prefixo", "a/b"])

        assert compactacao.main() == 1
        assert "--prefixo" in capsys.readouterr().err

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
        (destino_dir / "bkps_20200101.tar.gz").write_bytes(b"x")
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(origem, str(destino_dir)),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar", "--listar"])

        assert compactacao.main() == 0
        assert "bkps_20200101.tar.gz" in capsys.readouterr().out

    def test_backup_ausente_avisa(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            compactacao,
            "carregar_configuracao",
            lambda: _config(tmp_path / "nao_existe"),
        )
        monkeypatch.setattr("sys.argv", ["agebackup-compactar"])

        assert compactacao.main() == 1
        assert "backup nao encontrado" in capsys.readouterr().err


class TestFullEIncremental:
    """A primeira compactação da semana é full; as demais, incrementais."""

    def _src(self, tmp_path, nome="bkps"):
        origem = tmp_path / nome
        origem.mkdir()
        (origem / "a.txt").write_bytes(b"a" * 10)
        return origem

    def test_sem_estado_decide_full(self, tmp_path):
        tipo, base = compactacao.decidir_tipo(tmp_path / "out", _quando(2026, 10, 21))

        assert tipo == compactacao.TIPO_FULL
        assert base is None

    def test_full_grava_estado_e_incremental_usa_a_base(self, tmp_path):
        origem = self._src(tmp_path)
        destino = tmp_path / "out"
        dia = _quando(2026, 10, 21, 22)

        full = compactar(origem, destino, prefixo="RSKO", tipo="full", agora=dia)
        assert full.tipo == compactacao.TIPO_FULL

        (origem / "b.txt").write_bytes(b"b" * 10)
        _envelhecer(full.arquivo, -60)  # full "antes" do novo arquivo

        tipo, base = compactacao.decidir_tipo(destino, _quando(2026, 10, 21, 23))
        assert tipo == compactacao.TIPO_INCREMENTAL
        assert base == full.arquivo

    def test_incremental_leva_so_o_que_mudou(self, tmp_path):
        origem = self._src(tmp_path)
        destino = tmp_path / "out"
        _envelhecer(origem / "a.txt", -3600)  # a.txt é anterior ao full

        full = compactar(origem, destino, tipo="full", agora=_quando(2026, 10, 21, 22))
        _envelhecer(full.arquivo, -60)
        (origem / "b.txt").write_bytes(b"b" * 10)

        inc = compactar(
            origem,
            destino,
            tipo="incremental",
            base=full.arquivo,
            agora=_quando(2026, 10, 21, 23),
        )

        with tarfile.open(inc.arquivo) as pacote:
            nomes = pacote.getnames()

        assert "bkps/b.txt" in nomes
        assert "bkps/a.txt" not in nomes
        assert inc.itens == 1

    def test_nome_incremental_tem_marca_e_data(self, tmp_path):
        origem = self._src(tmp_path)
        destino = tmp_path / "out"

        full = compactar(origem, destino, tipo="full", agora=_quando(2026, 10, 21, 22))
        _envelhecer(full.arquivo, -60)
        (origem / "b.txt").write_bytes(b"b")

        inc = compactar(
            origem,
            destino,
            tipo="incremental",
            base=full.arquivo,
            agora=_quando(2026, 10, 21, 23, 15),
        )

        assert inc.arquivo.name == "bkps_inc_20261021-2315.tar.gz"

    def test_semana_nova_decide_full(self, tmp_path):
        origem = self._src(tmp_path)
        destino = tmp_path / "out"
        compactar(origem, destino, tipo="full", agora=_quando(2026, 10, 21, 22))

        tipo, base = compactacao.decidir_tipo(destino, _quando(2026, 10, 28, 22))

        assert tipo == compactacao.TIPO_FULL
        assert base is None

    def test_full_apagado_pela_retencao_forca_novo_full(self, tmp_path):
        origem = self._src(tmp_path)
        destino = tmp_path / "out"
        full = compactar(origem, destino, tipo="full", agora=_quando(2026, 10, 21, 22))
        full.arquivo.unlink()

        tipo, _base = compactacao.decidir_tipo(destino, _quando(2026, 10, 21, 23))

        assert tipo == compactacao.TIPO_FULL

    def test_incremental_sem_base_da_erro(self, tmp_path):
        origem = self._src(tmp_path)

        resultado = compactar(origem, tmp_path / "out", tipo="incremental", base=None)

        assert resultado.erro
        assert resultado.arquivo is None

    def test_retencao_alcanca_full_e_incremental(self, tmp_path):
        origem = self._src(tmp_path)
        destino = tmp_path / "out"

        for indice, hora in enumerate([10, 11, 12, 13, 14, 15, 16]):
            compactar(
                origem,
                destino,
                tipo="full",
                manter=7,
                agora=_quando(2026, 10, 21, hora),
            )
            _envelhecer(max(destino.glob("bkps_*.tar.gz")), -60)

        assert len(list(destino.glob("bkps_*.tar.gz"))) == 7
