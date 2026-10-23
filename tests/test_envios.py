"""Testes do log persistente de status dos envios ao FTP."""

from dataclasses import dataclass
from pathlib import Path

from agebackup import envios as envios_mod
from agebackup.envios import Envio, de_resultado, ler, registrar


@dataclass
class _Resultado:
    arquivo: Path | None = None
    enviado: bool = False
    erro: str = ""
    tamanho_local: int = 0
    tamanho_remoto: int | None = None


def test_para_linha_tem_nove_colunas():
    linha = Envio(arquivo="a.tar.gz").para_linha()

    assert len(linha.split("\t")) == 9


def test_campos_nao_quebram_o_tsv():
    linha = Envio(
        arquivo="a.tar.gz",
        caminho="/backup/linha 1\nlinha 2/a.tar.gz",
        detalhe="erro\ncom quebra\te tab",
    ).para_linha()

    assert len(linha.split("\t")) == 9
    assert "\n" not in linha


def test_status_invalido_vira_falha():
    assert Envio(arquivo="a", status="talvez").status == envios_mod.STATUS_FALHA


def test_registrar_e_ler(tmp_path):
    registrar(
        tmp_path,
        [
            Envio(
                arquivo="a.tar.gz",
                caminho="/backup/a.tar.gz",
                status=envios_mod.STATUS_OK,
                tamanho_local=10,
                tamanho_remoto=10,
                pasta_remota="/2026/10",
                conferencia="tamanho",
            )
        ],
    )

    linha = ler(tmp_path)[0]

    assert linha["arquivo"] == "a.tar.gz"
    assert linha["caminho"] == "/backup/a.tar.gz"
    assert linha["status"] == "ok"
    assert linha["tamanho_local"] == "10"
    assert linha["tamanho_remoto"] == "10"
    assert linha["pasta_remota"] == "/2026/10"
    assert linha["conferencia"] == "tamanho"


def test_registrar_acumula(tmp_path):
    registrar(tmp_path, [Envio(arquivo="a.tar.gz")])
    log = registrar(tmp_path, [Envio(arquivo="b.tar.gz")])

    assert log is not None
    assert [linha["arquivo"] for linha in ler(tmp_path)] == ["a.tar.gz", "b.tar.gz"]


def test_registrar_sem_itens_nao_cria_log(tmp_path):
    assert registrar(tmp_path, []) is None
    assert not envios_mod.caminho_log(tmp_path).exists()


def test_ler_log_antigo_com_colunas_faltando(tmp_path):
    envios_mod.caminho_log(tmp_path).write_text(
        "2026-10-22T10:00:00+00:00\tok\ta.tar.gz\n", encoding="utf-8"
    )

    linha = ler(tmp_path)[0]

    assert linha["arquivo"] == "a.tar.gz"
    assert linha["pasta_remota"] == ""
    assert linha["detalhe"] == ""


def test_de_resultado_ok():
    resultado = _Resultado(
        arquivo=Path("/backup/a.tar.gz"),
        enviado=True,
        tamanho_local=10,
        tamanho_remoto=10,
    )

    registro = de_resultado(resultado, "/2026/10")

    assert registro.status == envios_mod.STATUS_OK
    assert registro.caminho == "/backup/a.tar.gz"
    assert registro.conferencia == "tamanho"


def test_de_resultado_falha():
    resultado = _Resultado(
        arquivo=Path("/backup/a.tar.gz"),
        enviado=True,
        erro="tamanho diferente no servidor",
        tamanho_local=10,
        tamanho_remoto=None,
    )

    registro = de_resultado(resultado, "/2026/10")

    assert registro.status == envios_mod.STATUS_FALHA
    assert "diferente" in registro.detalhe


def test_de_resultado_sem_arquivo_usa_fallback():
    registro = de_resultado(_Resultado(), pasta_remota="/x", arquivo="/tmp/a.log")

    assert registro.arquivo == "a.log"
    assert registro.caminho == "/tmp/a.log"
