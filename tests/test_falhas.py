"""Testes do log persistente de falhas."""

from datetime import UTC, datetime
from pathlib import Path

from agebackup import falhas as falhas_mod
from agebackup.drive import (
    DownloadRestrictedError,
    ExportTooLargeError,
    FileNotFoundInDriveError,
    TransientDriveError,
)
from agebackup.falhas import Falha, categorizar, contar_por_categoria, ler, registrar

AGORA = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def _falha(nome="a.pdf", **kwargs):
    return Falha(nome=nome, **kwargs)


def test_falha_tem_horario_automatico():
    assert _falha().quando != ""


def test_categoria_desconhecida_vira_desconhecida():
    assert (
        Falha(nome="x", categoria="inventada").categoria == falhas_mod.CAT_DESCONHECIDO
    )


def test_para_linha_tem_seis_colunas():
    linha = _falha(detalhe="algo quebrou").para_linha()

    assert len(linha.split("\t")) == 6


def test_detalhe_nao_quebra_o_tsv():
    linha = _falha(detalhe="linha 1\nlinha 2\tcom tab").para_linha()

    assert len(linha.split("\t")) == 6
    assert "\n" not in linha


def test_detalhe_longo_e_truncado():
    linha = _falha(detalhe="x" * 900).para_linha()

    assert len(linha.split("\t")[5]) <= 500


def test_registrar_cria_log(tmp_path):
    log = registrar(tmp_path, [_falha("a.pdf", categoria="bloqueado")])

    assert log is not None
    assert "a.pdf" in log.read_text(encoding="utf-8")


def test_registrar_sem_falhas_nao_cria_arquivo(tmp_path):
    assert registrar(tmp_path, []) is None
    assert not falhas_mod.caminho_log(tmp_path).exists()


def test_registrar_sobrescreve(tmp_path):
    registrar(tmp_path, [_falha("antigo.pdf")])
    log = registrar(tmp_path, [_falha("novo.pdf")], sobrescrever=True)

    texto = log.read_text(encoding="utf-8")
    assert "novo.pdf" in texto
    assert "antigo.pdf" not in texto


def test_registrar_acumula_por_padrao(tmp_path):
    registrar(tmp_path, [_falha("a.pdf")])
    log = registrar(tmp_path, [_falha("b.pdf")])

    texto = log.read_text(encoding="utf-8")
    assert "a.pdf" in texto
    assert "b.pdf" in texto


def test_registrar_nao_deixa_temporario(tmp_path):
    registrar(tmp_path, [_falha()])

    assert not list(tmp_path.glob("*.tmp"))


def test_registrar_cria_pasta_se_faltar(tmp_path):
    destino = tmp_path / "inexistente"

    log = registrar(destino, [_falha()])

    assert log is not None
    assert log.exists()


def test_registrar_devolve_none_em_erro_de_io(tmp_path, monkeypatch):
    def falha(*args, **kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr(Path, "open", falha)

    assert registrar(tmp_path, [_falha()]) is None


def test_categorizar_bloqueado():
    erro = DownloadRestrictedError("sem acesso")
    categoria, detalhe = categorizar(erro)

    assert categoria == falhas_mod.CAT_BLOQUEADO
    assert "bloqueado" in detalhe


def test_categorizar_inexistente():
    assert (
        categorizar(FileNotFoundInDriveError("sumiu"))[0] == falhas_mod.CAT_INEXISTENTE
    )


def test_categorizar_temporaria():
    assert categorizar(TransientDriveError("429"))[0] == falhas_mod.CAT_TEMPORARIA


def test_categorizar_erro_local():
    assert categorizar(OSError("disco cheio"))[0] == falhas_mod.CAT_LOCAL


def test_categorizar_grande_demais():
    categoria, detalhe = categorizar(ExportTooLargeError("não coube"))

    assert categoria == falhas_mod.CAT_GRANDE
    assert "grande" in detalhe


def test_categorizar_valor_invalido():
    assert categorizar(ValueError("data ruim"))[0] == falhas_mod.CAT_LOCAL


def test_categorizar_http():
    class Resp:
        status = 500

    erro = type("E", (Exception,), {"resp": Resp()})("explodiu")

    categoria, detalhe = categorizar(erro)
    assert categoria == falhas_mod.CAT_API
    assert "500" in detalhe


def test_categorizar_desconhecido():
    assert categorizar(RuntimeError("??"))[0] == falhas_mod.CAT_DESCONHECIDO


def test_ler_log_vazio(tmp_path):
    assert ler(tmp_path) == []


def test_ler_devolve_colunas(tmp_path):
    registrar(
        tmp_path,
        [_falha("a.pdf", categoria="bloqueado", detalhe="motivo", drive_id="F1")],
    )

    linhas = ler(tmp_path)

    assert len(linhas) == 1
    assert linhas[0]["nome"] == "a.pdf"
    assert linhas[0]["categoria"] == "bloqueado"
    assert linhas[0]["drive_id"] == "F1"
    assert linhas[0]["detalhe"] == "motivo"


def test_ler_ignora_comentarios(tmp_path):
    log = falhas_mod.caminho_log(tmp_path)
    log.write_text("# cabecalho\na.pdf\tbloqueado\t1\tF1\tmotivo\n", encoding="utf-8")

    linhas = ler(tmp_path)

    assert len(linhas) == 1


def test_ler_ultimas_n(tmp_path):
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        registrar(tmp_path, [_falha(nome)])

    linhas = ler(tmp_path, ultimas=2)

    assert [linha["nome"] for linha in linhas] == ["b.pdf", "c.pdf"]


def test_contar_por_categoria_ordenado(tmp_path):
    registrar(tmp_path, [_falha("a", categoria="bloqueado")])
    registrar(tmp_path, [_falha("b", categoria="bloqueado")])
    registrar(tmp_path, [_falha("c", categoria="temporaria")])

    contagem = contar_por_categoria(ler(tmp_path))

    assert contagem == {"bloqueado": 2, "temporaria": 1}
    assert next(iter(contagem)) == "bloqueado"


def test_linha_com_colunas_faltando(tmp_path):
    log = falhas_mod.caminho_log(tmp_path)
    # Linha truncada: sobram "quando" e "nome", as demais ficam vazias.
    log.write_text("2026-10-12T09:00:00\taqui\n", encoding="utf-8")

    linhas = ler(tmp_path)

    assert linhas[0]["nome"] == "aqui"
    assert linhas[0]["categoria"] == ""
    assert linhas[0]["drive_id"] == ""


def _http(reason: str, status: int):
    erro = type("E", (Exception,), {})("mensagem")
    erro.resp = type("R", (), {"status": status})()
    erro.error_details = [{"reason": reason}]
    return erro


def test_file_not_exportable_e_operacao_longa():
    categoria, detalhe = categorizar(_http("fileNotExportable", 403))

    assert categoria == falhas_mod.CAT_OPERACAO_LONGA
    assert "files.download" in detalhe


def test_file_not_downloadable_e_operacao_longa():
    assert categorizar(_http("fileNotDownloadable", 403))[0] == (
        falhas_mod.CAT_OPERACAO_LONGA
    )


def test_rate_limit_e_cota():
    assert categorizar(_http("rateLimitExceeded", 403))[0] == falhas_mod.CAT_COTA


def test_rate_limit_de_usuario_e_cota():
    assert categorizar(_http("userRateLimitExceeded", 403))[0] == falhas_mod.CAT_COTA


def test_motivo_comum_continua_erro_api():
    assert categorizar(_http("backendError", 500))[0] == falhas_mod.CAT_API


def test_erro_http_sem_motivo_mostra_status():
    erro = type("E", (Exception,), {})("x")
    erro.resp = type("R", (), {"status": 500})()
    erro.error_details = ""

    assert categorizar(erro) == (falhas_mod.CAT_API, "HTTP 500")


def test_operacao_longa_esta_registrada_no_log(tmp_path):
    registrar(tmp_path, [Falha(nome="v.mp4", categoria=falhas_mod.CAT_OPERACAO_LONGA)])

    assert ler(tmp_path)[0]["categoria"] == "operacao_longa"


def test_contagem_por_categoria_inclui_lro(tmp_path):
    registrar(tmp_path, [Falha(nome="v.mp4", categoria=falhas_mod.CAT_OPERACAO_LONGA)])
    registrar(tmp_path, [Falha(nome="a.pdf", categoria=falhas_mod.CAT_BLOQUEADO)])

    assert contar_por_categoria(ler(tmp_path)) == {
        "operacao_longa": 1,
        "bloqueado": 1,
    }
