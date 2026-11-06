"""Testes da rotina full/incremental/diferencial para destinos locais."""

import errno
import json
import os
from pathlib import Path

import pytest

from agebackup import config as config_mod
from agebackup import rotina
from agebackup.config import Config, DestinoRotinaConfig, ManterRotinaConfig


def _criar(base: Path, arquivos: dict[str, bytes]) -> None:
    for rel, conteudo in arquivos.items():
        alvo = base / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(conteudo)


def _config(fonte: Path, destinos: list[tuple[str, Path]], **manter) -> Config:
    config = Config()
    config.backup.destination = str(fonte)
    config.rotina.destinos = [
        DestinoRotinaConfig(nome=nome, caminho=str(caminho))
        for nome, caminho in destinos
    ]
    if manter:
        config.rotina.manter = ManterRotinaConfig(**manter)
    return config


def _runs(destino: Path, sufixo: str) -> list[Path]:
    tipo = rotina.TIPO_POR_SUFIXO[sufixo]
    return [caminho for _, atual, caminho in rotina._runs(destino) if atual == tipo]


def _ultimo(destino: Path, sufixo: str) -> Path:
    runs = _runs(destino, sufixo)
    assert runs, f"nenhum snapshot *-{sufixo} em {destino}"
    return runs[-1]


def _mudar(caminho: Path, conteudo: bytes) -> None:
    """Altera o conteúdo e força um mtime diferente do anterior."""
    caminho.write_bytes(conteudo)
    info = caminho.stat()
    os.utime(caminho, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))


class TestVarredura:
    def test_lista_arquivos_e_pastas_relativos(self, tmp_path):
        _criar(tmp_path, {"a.txt": b"a", "sub/b.txt": b"bb"})
        (tmp_path / "vazia").mkdir()

        dados = rotina.varrer_fonte(tmp_path)

        assert dados.arquivos == {
            "a.txt": (1, (tmp_path / "a.txt").stat().st_mtime_ns),
            "sub/b.txt": (2, (tmp_path / "sub/b.txt").stat().st_mtime_ns),
        }
        assert dados.pastas == ["sub", "vazia"]

    def test_ignora_estado_da_rotina_e_temporarios(self, tmp_path):
        _criar(
            tmp_path,
            {
                "doc.txt": b"x",
                "doc.txt.tmp": b"meio",
                ".agebackup-rotina/estado-nas.json": b"{}",
                "logs/.agebackup-falhas.log": b"log",
                ".agebackup-manifest.json": b"{}",
            },
        )

        dados = rotina.varrer_fonte(tmp_path)

        assert "doc.txt" in dados.arquivos
        # Manifesto e logs entram: o snapshot deve ser restaurável e descritivo.
        assert "logs/.agebackup-falhas.log" in dados.arquivos
        assert ".agebackup-manifest.json" in dados.arquivos
        # Parcial de download: o arquivo final está ao lado, então fica de fora.
        assert "doc.txt.tmp" not in dados.arquivos
        assert not any(
            caminho.startswith(".agebackup-rotina") for caminho in dados.arquivos
        )

    def test_arquivo_legitimo_tmp_entra_no_snapshot(self, tmp_path):
        # Um arquivo vindo do Drive pode terminar em .tmp e não é resto de nada.
        _criar(tmp_path, {"notas.tmp": b"legitimo"})

        dados = rotina.varrer_fonte(tmp_path)

        assert "notas.tmp" in dados.arquivos

    def test_estado_so_e_ignorado_na_raiz(self, tmp_path):
        _criar(
            tmp_path,
            {
                ".agebackup-rotina/estado-nas.json": b"{}",
                "sub/.agebackup-rotina/nota.txt": b"oi",
            },
        )

        dados = rotina.varrer_fonte(tmp_path)

        assert ".agebackup-rotina/estado-nas.json" not in dados.arquivos
        assert "sub/.agebackup-rotina/nota.txt" in dados.arquivos

    def test_link_simbolico_de_pasta_vira_erro(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "a.txt").write_bytes(b"a")
        fonte = tmp_path / "fonte"
        fonte.mkdir()
        os.symlink(real, fonte / "atalho")

        dados = rotina.varrer_fonte(fonte)

        assert len(dados.erros) == 1
        assert "atalho" in dados.erros[0]


class TestFull:
    def test_copia_tudo_sem_compartilhar_inode_com_a_fonte(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"aaa", "sub/b.txt": b"bb"})

        codigo = rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        assert codigo == 0
        run = _ultimo(destino, "full")
        assert (run / "a.txt").read_bytes() == b"aaa"
        assert (run / "sub/b.txt").read_bytes() == b"bb"
        # Ponto no tempo independente: nem hardlink da fonte, nem de outro run.
        assert os.stat(run / "a.txt").st_ino != os.stat(fonte / "a.txt").st_ino

    def test_preserva_mtime_para_as_comparacoes_seguintes(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"aaa"})

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        copia = _ultimo(destino, "full") / "a.txt"
        assert copia.stat().st_mtime_ns == (fonte / "a.txt").stat().st_mtime_ns

    def test_recria_pasta_vazia(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        fonte.mkdir()
        (fonte / "vazia").mkdir()

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        assert (_ultimo(destino, "full") / "vazia").is_dir()


class TestIncremental:
    def test_reaproveita_intocados_e_copia_alterados(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"igual.txt": b"igual", "muda.txt": b"velho", "sai.txt": b"sai"})
        config = _config(fonte, [("nas", destino)])

        rotina.executar_rotina(config, "full")
        full = _ultimo(destino, "full")

        _mudar(fonte / "muda.txt", b"novo")
        (fonte / "sai.txt").unlink()
        _criar(fonte, {"entra.txt": b"entra"})

        rotina.executar_rotina(config, "incremental")
        inc = _ultimo(destino, "inc")

        # Inalterado: hardlink para o snapshot anterior (mesmo inode).
        assert os.stat(inc / "igual.txt").st_ino == os.stat(full / "igual.txt").st_ino
        # Alterado: conteúdo novo e inode novo.
        assert (inc / "muda.txt").read_bytes() == b"novo"
        assert os.stat(inc / "muda.txt").st_ino != os.stat(full / "muda.txt").st_ino
        # Novo entra; removido da fonte não entra no run novo (fica no antigo).
        assert (inc / "entra.txt").read_bytes() == b"entra"
        assert not (inc / "sai.txt").exists()
        assert (full / "sai.txt").read_bytes() == b"sai"

    def test_primeiro_run_sem_ancora_vira_full(self, tmp_path, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "incremental")

        assert _runs(destino, "inc") == []
        assert len(_runs(destino, "full")) == 1
        assert "primeiro snapshot" in capsys.readouterr().out


class TestDiferencial:
    def test_sem_full_anterior_vira_full(self, tmp_path, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        (destino / "2026-01-01T000000-inc").mkdir()

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "diferencial")

        assert _runs(destino, "dif") == []
        assert len(_runs(destino, "full")) == 1
        assert "sem full anterior" in capsys.readouterr().out

    def test_ancora_e_o_ultimo_full_nao_o_ultimo_run(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"})
        config = _config(fonte, [("nas", destino)])

        rotina.executar_rotina(config, "full")
        full = _ultimo(destino, "full")

        _mudar(fonte / "a.txt", b"a2")
        rotina.executar_rotina(config, "incremental")
        inc = _ultimo(destino, "inc")

        _mudar(fonte / "b.txt", b"b2")
        rotina.executar_rotina(config, "diferencial")
        dif = _ultimo(destino, "dif")

        # Inalterado desde o full: linka direto no full (não no incremental).
        assert os.stat(dif / "c.txt").st_ino == os.stat(full / "c.txt").st_ino
        assert os.stat(dif / "c.txt").st_ino == os.stat(inc / "c.txt").st_ino
        # Mudado depois do full: copiado no diferencial (inode novo).
        assert (dif / "a.txt").read_bytes() == b"a2"
        assert os.stat(dif / "a.txt").st_ino != os.stat(full / "a.txt").st_ino
        # Mudado depois do incremental: também copiado.
        assert (dif / "b.txt").read_bytes() == b"b2"
        assert os.stat(dif / "b.txt").st_ino != os.stat(full / "b.txt").st_ino


class TestFullIndependencia:
    def test_full_posterior_nao_herda_inodes(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])

        rotina.executar_rotina(config, "full")
        primeiro = _ultimo(destino, "full")
        rotina.executar_rotina(config, "full")
        segundo = _runs(destino, "full")[-1]

        assert primeiro != segundo
        assert os.stat(segundo / "a.txt").st_ino != os.stat(primeiro / "a.txt").st_ino


class TestRetencao:
    def test_mantem_mais_recentes_por_tipo(self, tmp_path):
        destino = tmp_path / "destino"
        destino.mkdir()
        for momento in ("2026-01-01T000000", "2026-01-02T000000", "2026-01-03T000000"):
            (destino / f"{momento}-full").mkdir()
        for momento in ("2026-01-04T000000", "2026-01-05T000000"):
            (destino / f"{momento}-inc").mkdir()

        removidos = rotina.aplicar_retencao(
            destino, ManterRotinaConfig(full=2, incremental=1, diferencial=0)
        )

        assert removidos == ["2026-01-01T000000-full", "2026-01-04T000000-inc"]
        assert [run.name for run in _runs(destino, "full")] == [
            "2026-01-02T000000-full",
            "2026-01-03T000000-full",
        ]

    def test_zero_guarda_todos(self, tmp_path):
        destino = tmp_path / "destino"
        destino.mkdir()
        for momento in ("2026-01-01T000000", "2026-01-02T000000"):
            (destino / f"{momento}-full").mkdir()

        removidos = rotina.aplicar_retencao(
            destino, ManterRotinaConfig(full=0, incremental=0, diferencial=0)
        )

        assert removidos == []
        assert len(_runs(destino, "full")) == 2

    def test_podar_o_full_nao_corrompe_incremental_que_linkava_nele(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"conteudo"})
        config = _config(fonte, [("nas", destino)], full=1)

        rotina.executar_rotina(config, "full")
        rotina.executar_rotina(config, "incremental")
        inc = _ultimo(destino, "inc")
        rotina.executar_rotina(config, "full")

        # O full antigo foi podado; o incremental lê o mesmo inode normalmente.
        assert len(_runs(destino, "full")) == 1
        assert (inc / "a.txt").read_bytes() == b"conteudo"

    def test_dry_run_mostra_o_que_seria_removido(self, tmp_path, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        for momento in ("2026-01-01T000000", "2026-01-02T000000"):
            (destino / f"{momento}-full").mkdir()

        codigo = rotina.executar_rotina(
            _config(fonte, [("nas", destino)], full=1), "full", dry_run=True
        )

        assert codigo == 0
        assert "retencao removeria: 2 snapshot(s)" in capsys.readouterr().out
        # Nada foi apagado nem gravado.
        assert len(_runs(destino, "full")) == 2


class TestEstado:
    def test_grava_estado_com_contadores(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"aaa"})

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        estado = rotina.carregar_estado(fonte, "nas")
        assert estado["versao"] == 1
        assert estado["ultimo_full"].endswith("-full")
        assert estado["ultimo_run"] == estado["ultimo_full"]
        assert estado["runs"][0]["arquivos"] == 1
        assert estado["runs"][0]["copiados"] == 1

    def test_estado_corrompido_e_reconstruido_do_disco(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])

        rotina.executar_rotina(config, "full")
        rotina.caminho_estado(fonte, "nas").write_text("{ruim", encoding="utf-8")
        assert rotina.carregar_estado(fonte, "nas") == {}

        rotina.executar_rotina(config, "incremental")

        estado = rotina.carregar_estado(fonte, "nas")
        assert len(estado["runs"]) == 2
        assert estado["runs"][0]["tipo"] == "full"
        assert estado["runs"][1]["tipo"] == "incremental"

    def test_dry_run_nao_grava_nada(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full", dry_run=True)

        assert list(destino.iterdir()) == []
        assert not rotina.caminho_estado(fonte, "nas").exists()

    def test_falha_ao_salvar_estado_mantem_snapshot_e_avisa(
        self, tmp_path, monkeypatch, capsys
    ):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})

        def falhar(*args, **kwargs):
            raise OSError(errno.ENOSPC, "sem espaco")

        monkeypatch.setattr(rotina, "salvar_estado", falhar)

        codigo = rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        # O snapshot é válido; o problema é só o estado — mas o exit acusa.
        assert codigo == 1
        assert len(_runs(destino, "full")) == 1
        assert "estado nao atualizado" in capsys.readouterr().err


class TestProblemas:
    def test_destino_inacessivel_nao_impede_os_outros(self, tmp_path, capsys):
        fonte, bom = tmp_path / "fonte", tmp_path / "bom"
        bom.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("bom", bom), ("fora", tmp_path / "nao-montado")])

        codigo = rotina.executar_rotina(config, "full")

        assert codigo == 1
        assert len(_runs(bom, "full")) == 1
        assert "destino inacessivel" in capsys.readouterr().err

    def test_destino_dentro_da_fonte_e_recusado(self, tmp_path):
        fonte = tmp_path / "fonte"
        _criar(fonte, {"a.txt": b"a"})
        destino = fonte / "rotina"
        destino.mkdir()

        codigo = rotina.executar_rotina(_config(fonte, [("ruim", destino)]), "full")

        assert codigo == 1
        assert list(destino.iterdir()) == []

    def test_sem_destinos_configurados(self, tmp_path, capsys):
        fonte = tmp_path / "fonte"
        _criar(fonte, {"a.txt": b"a"})

        codigo = rotina.executar_rotina(_config(fonte, []), "full")

        assert codigo == 1
        assert "nenhum destino" in capsys.readouterr().err

    def test_destino_inativo_e_ignorado(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])
        config.rotina.destinos[0].ativo = False

        codigo = rotina.executar_rotina(config, "full")

        assert codigo == 1
        assert list(destino.iterdir()) == []

    def test_nome_de_destino_desconhecido(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})

        codigo = rotina.executar_rotina(
            _config(fonte, [("nas", destino)]), "full", "outro"
        )

        assert codigo == 1
        assert list(destino.iterdir()) == []

    def test_destinos_com_mesmo_nome_sao_recusados(self, tmp_path, capsys):
        fonte, a, b = tmp_path / "fonte", tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        _criar(fonte, {"a.txt": b"a"})

        codigo = rotina.executar_rotina(
            _config(fonte, [("nas", a), ("nas", b)]), "full"
        )

        # Estado seria sobrescrito por ambos: recusa antes de gravar qualquer um.
        assert codigo == 1
        assert "mesmo nome" in capsys.readouterr().err
        assert list(a.iterdir()) == []
        assert list(b.iterdir()) == []

    def test_nome_de_destino_filtra_so_um(self, tmp_path):
        fonte, a, b = tmp_path / "fonte", tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        _criar(fonte, {"a.txt": b"a"})

        codigo = rotina.executar_rotina(
            _config(fonte, [("nas", a), ("off", b)]), "full", "nas"
        )

        assert codigo == 0
        assert len(_runs(a, "full")) == 1
        assert _runs(b, "full") == []

    def test_item_ilegivel_na_fonte_aborta_sem_gravar(self, tmp_path, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        # Link quebrado: stat falha e o snapshot ficaria incompleto em silêncio.
        os.symlink(tmp_path / "fora", fonte / "atalho")

        codigo = rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        assert codigo == 1
        assert list(destino.iterdir()) == []
        assert "nao foi possivel ler" in capsys.readouterr().err


class TestHardlink:
    def test_sem_suporte_a_hardlink_copia_os_inalterados(
        self, tmp_path, monkeypatch, capsys
    ):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])
        rotina.executar_rotina(config, "full")

        def sem_link(origem, alvo):
            raise OSError(errno.EXDEV, "cross-device link")

        monkeypatch.setattr(rotina.os, "link", sem_link)

        codigo = rotina.executar_rotina(config, "incremental")

        assert codigo == 0
        inc = _ultimo(destino, "inc")
        full = _ultimo(destino, "full")
        assert (inc / "a.txt").read_bytes() == b"a"
        assert os.stat(inc / "a.txt").st_ino != os.stat(full / "a.txt").st_ino
        assert "sem hardlink" in capsys.readouterr().out


class TestTemporarios:
    def test_restos_de_run_interrompido_sao_limpos(self, tmp_path):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        resto = destino / ".2026-01-01T000000-full.tmp"
        resto.mkdir()
        (resto / "lixo").write_bytes(b"x")

        rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        assert not resto.exists()

    def test_falha_nao_promove_snapshot_parcial(self, tmp_path, monkeypatch, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a", "b.txt": b"b"})

        def falhar(origem, alvo):
            raise OSError(errno.ENOSPC, "disco cheio")

        monkeypatch.setattr(rotina, "_copiar", falhar)

        codigo = rotina.executar_rotina(_config(fonte, [("nas", destino)]), "full")

        assert codigo == 1
        assert _runs(destino, "full") == []
        assert "falha ao gravar" in capsys.readouterr().err
        assert not rotina.caminho_estado(fonte, "nas").exists()


class TestCli:
    def test_main_full(self, tmp_path, monkeypatch):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])
        monkeypatch.setattr(rotina, "carregar_configuracao", lambda: config)

        assert rotina.main(["--full"]) == 0
        assert len(_runs(destino, "full")) == 1

    def test_main_padrao_e_incremental(self, tmp_path, monkeypatch):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])
        monkeypatch.setattr(rotina, "carregar_configuracao", lambda: config)

        rotina.main(["--full"])
        assert rotina.main([]) == 0

        assert len(_runs(destino, "inc")) == 1

    def test_main_dry_run(self, tmp_path, monkeypatch, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])
        monkeypatch.setattr(rotina, "carregar_configuracao", lambda: config)

        assert rotina.main(["--full", "--dry-run"]) == 0

        assert list(destino.iterdir()) == []
        assert "Simulacao" in capsys.readouterr().out

    def test_main_status(self, tmp_path, monkeypatch, capsys):
        fonte, destino = tmp_path / "fonte", tmp_path / "destino"
        destino.mkdir()
        _criar(fonte, {"a.txt": b"a"})
        config = _config(fonte, [("nas", destino)])
        monkeypatch.setattr(rotina, "carregar_configuracao", lambda: config)
        rotina.main(["--full"])

        assert rotina.main(["--status"]) == 0

        saida = capsys.readouterr().out
        assert "Rotina - status" in saida
        assert "nas (ativo)" in saida
        assert "1 snapshot(s): 1 full" in saida

    def test_acao_exclusiva_vira_erro_de_uso(self):
        with pytest.raises(SystemExit) as erro:
            rotina.main(["--full", "--incremental"])

        assert erro.value.code == 2


class TestConfig:
    def test_le_destinos_e_normaliza_retencao(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
        (tmp_path / "config.json").write_text(
            json.dumps(
                {
                    "rotina": {
                        "destinos": [
                            {"nome": "nas", "caminho": "/mnt/nas/bkps"},
                            {"nome": "off", "caminho": "/mnt/off", "ativo": False},
                            {"nome": "", "caminho": "/ignorado"},
                            {"nome": "semcaminho"},
                        ],
                        "manter": {
                            "full": 999,
                            "incremental": -5,
                            "diferencial": "muitos",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        config = config_mod.load()

        assert [(d.nome, d.ativo) for d in config.rotina.destinos] == [
            ("nas", True),
            ("off", False),
        ]
        assert config.rotina.manter.full == config_mod.ROTINA_MANTER_MAXIMO
        assert config.rotina.manter.incremental == 0
        assert config.rotina.manter.diferencial == config_mod.ROTINA_DIFERENCIAL_PADRAO

    def test_config_antiga_ganha_rotina_vazia(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")

        config = config_mod.load()

        assert config.rotina.destinos == []
        assert config.rotina.manter.full == config_mod.ROTINA_FULL_PADRAO

    def test_salva_e_carrega_rotina(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "agebackup.json")

        config = Config()
        config.rotina.destinos = [
            DestinoRotinaConfig(nome="nas", caminho="/mnt/nas"),
            DestinoRotinaConfig(nome="off", caminho="/mnt/off", ativo=False),
        ]
        config.rotina.manter = ManterRotinaConfig(full=2, incremental=3, diferencial=4)

        config_mod.save(config)
        carregada = config_mod.load()

        assert [
            (destino.nome, destino.caminho, destino.ativo)
            for destino in carregada.rotina.destinos
        ] == [("nas", "/mnt/nas", True), ("off", "/mnt/off", False)]
        assert carregada.rotina.manter == ManterRotinaConfig(
            full=2, incremental=3, diferencial=4
        )
