"""Testes da rotação dos logs, por execução.

A fronteira entre execuções é decidida pelo arquivo de marca `.agebackup-mes`,
não pelo mtime do log. Os testes simulam a virada escrevendo o selo da execução
anterior na marca e chamando a rotação com um momento novo.
"""

import gzip
from datetime import UTC, datetime

from agebackup import rotacao

LOG = ".agebackup-falhas.log"
SELO_ANTERIOR = "2026-10-20-0300"
SELO_MES_ANTERIOR = "2026-09"
AGORA = datetime(2026, 10, 21, 18, 42, tzinfo=UTC)
SELO_ATUAL = "2026-10-21-1842"


def _caminho(tmp_path):
    return tmp_path / LOG


def _marcar(tmp_path, selo: str):
    rotacao.caminho_marca(tmp_path).write_text(selo, encoding="utf-8")


def _escrever(caminho, texto="linha\n"):
    caminho.write_text(texto, encoding="utf-8")


def _gz(tmp_path, selo: str):
    return tmp_path / f"{LOG}.{selo}.log.gz"


def test_primeira_execucao_cria_marca(tmp_path):
    rotacao.rotacionar(_caminho(tmp_path), AGORA)

    assert rotacao.caminho_marca(tmp_path).read_text(encoding="utf-8") == SELO_ATUAL


def test_primeira_execucao_nao_move_nada(tmp_path):
    log = _caminho(tmp_path)
    _escrever(log, "primeira vez\n")

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == []
    assert log.read_text(encoding="utf-8") == "primeira vez\n"


def test_selo_igual_nao_rotaciona(tmp_path):
    """Duas chamadas no mesmo minuto não criam dois arquivos."""
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    _escrever(log, "ainda nesta execucao\n")

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == []
    assert log.exists()


def test_virada_comprime_execucao_anterior(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    _escrever(log, "falha de ontem\n")

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == [_gz(tmp_path, SELO_ANTERIOR)]
    assert _gz(tmp_path, SELO_ANTERIOR).exists()
    assert not log.exists(), "o log corrente deve sumir na virada"


def test_nome_traz_data_e_hora(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    _escrever(log)

    rotacao.rotacionar(log, AGORA)

    assert (tmp_path / f"{LOG}.2026-10-20-0300.log.gz").exists()


def test_conteudo_sobrevive_a_compressao(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    original = "a\nb\nc\n"
    _escrever(log, original)

    rotacao.rotacionar(log, AGORA)

    assert (
        gzip.decompress(_gz(tmp_path, SELO_ANTERIOR).read_bytes()).decode() == original
    )


def test_accentos_sobrevremem(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    original = "ação, coração, três\n"
    _escrever(log, original)

    rotacao.rotacionar(log, AGORA)

    compactado = gzip.decompress(_gz(tmp_path, SELO_ANTERIOR).read_bytes())
    assert compactado.decode("utf-8") == original


def test_marca_avanca_apos_virada(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    _escrever(log)

    rotacao.rotacionar(log, AGORA)

    assert rotacao.caminho_marca(tmp_path).read_text(encoding="utf-8") == SELO_ATUAL


def test_rotacao_e_idempotente(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    _escrever(log, "antigo\n")

    rotacao.rotacionar(log, AGORA)
    segundo = rotacao.rotacionar(log, AGORA)

    assert segundo.comprimidos == []
    assert len(list(tmp_path.glob(f"{LOG}.*.gz"))) == 1


def test_escrever_no_log_nao_impede_a_virada(tmp_path):
    """Regressão: gravar no log corrente não pode esconder o log antigo."""
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    _escrever(log, "ontem\n")

    import os

    os.utime(log, (AGORA.timestamp(), AGORA.timestamp()))

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == [_gz(tmp_path, SELO_ANTERIOR)]


def test_varias_execucoes_soltas_sao_comprimidas(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    for selo in ("2026-10-18-0300", "2026-10-19-0300", "2026-10-20-0300"):
        (tmp_path / f"{LOG}.{selo}.log").write_text("antigo\n", encoding="utf-8")

    resultado = rotacao.rotacionar(log, AGORA)

    assert len(resultado.comprimidos) == 3
    assert not list(tmp_path.glob(f"{LOG}.2026-10-*.log"))


def test_execucao_corrente_solta_nao_e_comprimida(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    do_agora = tmp_path / f"{LOG}.{SELO_ATUAL}.log"
    do_agora.write_text("ainda\n", encoding="utf-8")

    resultado = rotacao.rotacionar(log, AGORA)

    assert do_agora.exists()
    assert resultado.comprimidos == []


def test_nome_invalido_e_ignorado(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    invalido = tmp_path / f"{LOG}.nao-e-data.log"
    invalido.write_text("?\n", encoding="utf-8")

    rotacao.rotacionar(log, AGORA)

    assert invalido.exists(), "não deve apagar arquivo de nome inesperado"


def test_log_da_execucao_anterior_e_acrescentado(tmp_path):
    """Se existir arquivo da execução, o conteúdo é somado, não sobrescrito."""
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    alvo = tmp_path / f"{LOG}.{SELO_ANTERIOR}.log"
    alvo.write_text("primeira parte\n", encoding="utf-8")
    _escrever(log, "segunda parte\n")

    rotacao.rotacionar(log, AGORA)

    texto = gzip.decompress(_gz(tmp_path, SELO_ANTERIOR).read_bytes()).decode()
    assert "primeira parte" in texto
    assert "segunda parte" in texto


def test_sem_log_nao_falha(tmp_path):
    _marcar(tmp_path, SELO_ANTERIOR)

    resultado = rotacao.rotacionar(_caminho(tmp_path), AGORA)

    assert resultado.comprimidos == []
    assert resultado.erro == ""


def test_arquivados_ordenados(tmp_path):
    log = _caminho(tmp_path)
    for selo in ("2026-10-18-0300", "2026-10-20-0300", "2026-10-19-0300"):
        (tmp_path / f"{LOG}.{selo}.log.gz").write_bytes(b"x")

    lista = [p.name for p in rotacao.arquivados(log)]

    assert lista[0].endswith("2026-10-20-0300.log.gz")
    assert lista[-1].endswith("2026-10-18-0300.log.gz")


def test_arquivados_aceitam_formato_antigo(tmp_path):
    """Histórico do formato mensal continua sendo lido e ordenado."""
    log = _caminho(tmp_path)
    for selo in ("2026-08", "2026-10-21-1842", "2026-09"):
        (tmp_path / f"{LOG}.{selo}.log.gz").write_bytes(b"x")

    lista = [p.name for p in rotacao.arquivados(log)]

    assert lista[0].endswith("2026-10-21-1842.log.gz")
    assert lista[1].endswith("2026-09.log.gz")
    assert lista[2].endswith("2026-08.log.gz")


def test_selo_do_arquivo():
    assert rotacao.selo_do_arquivo(f"{LOG}.2026-09.log.gz", LOG) == "2026-09"
    assert (
        rotacao.selo_do_arquivo(f"{LOG}.2026-10-21-1842.log.gz", LOG)
        == "2026-10-21-1842"
    )
    assert rotacao.selo_do_arquivo(f"{LOG}.2026-09.log", LOG) == "2026-09"
    assert rotacao.selo_do_arquivo(LOG, LOG) is None
    assert rotacao.selo_do_arquivo("outro.log", LOG) is None
    assert rotacao.selo_do_arquivo(f"{LOG}.lixo.log.gz", LOG) is None


def test_retencao_mantem_apenas_os_recentes(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    for selo in (
        "2026-10-15-0300",
        "2026-10-16-0300",
        "2026-10-17-0300",
        "2026-10-18-0300",
        "2026-10-19-0300",
        "2026-10-20-0300",
        "2026-10-21-0300",
    ):
        (tmp_path / f"{LOG}.{selo}.log.gz").write_bytes(b"x")

    resultado = rotacao.rotacionar(log, AGORA, manter=7)

    assert resultado.removidos == []
    assert len(rotacao.arquivados(log)) == 7


def test_retencao_apaga_os_excedentes(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    for selo in (
        "2026-10-18-0300",
        "2026-10-19-0300",
        "2026-10-20-0300",
        "2026-10-21-0300",
        "2026-10-22-0300",
    ):
        (tmp_path / f"{LOG}.{selo}.log.gz").write_bytes(b"x")

    resultado = rotacao.rotacionar(log, AGORA, manter=3)

    assert len(resultado.removidos) == 2
    assert not (tmp_path / f"{LOG}.2026-10-18-0300.log.gz").exists()
    assert not (tmp_path / f"{LOG}.2026-10-19-0300.log.gz").exists()
    assert (tmp_path / f"{LOG}.2026-10-22-0300.log.gz").exists()


def test_retencao_zero_guarda_tudo(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    velho = tmp_path / f"{LOG}.2020-01-01-0300.log.gz"
    velho.write_bytes(b"muito antigo")

    resultado = rotacao.rotacionar(log, AGORA, manter=0)

    assert velho.exists()
    assert resultado.removidos == []


def test_retencao_nao_apaga_log_textual(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    log.write_text("execucao corrente\n", encoding="utf-8")

    rotacao.rotacionar(log, AGORA, manter=1)

    assert log.exists()


def test_retencao_ignora_nome_invalido(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ATUAL)
    invalido = tmp_path / f"{LOG}.lixo.log.gz"
    invalido.write_bytes(b"?")

    rotacao.rotacionar(log, AGORA, manter=1)

    assert invalido.exists()


def test_retencao_vazia_sem_log(tmp_path):
    resultado = rotacao.rotacionar(_caminho(tmp_path), AGORA, manter=6)

    assert resultado.removidos == []


def test_sem_compressao_move_mas_nao_comprime(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, SELO_ANTERIOR)
    log.write_text("ontem\n", encoding="utf-8")

    resultado = rotacao.rotacionar(log, AGORA, comprimir=False)

    assert resultado.comprimidos == []
    assert (tmp_path / f"{LOG}.{SELO_ANTERIOR}.log").exists()
    assert not list(tmp_path.glob("*.gz"))


def test_selo_ordena_por_data():
    assert rotacao._data_do_selo("2026-10-21-1842") > rotacao._data_do_selo(
        "2026-10-20-0300"
    )
    assert rotacao._data_do_selo("2027-01") > rotacao._data_do_selo("2026-12")
    assert rotacao._data_do_selo("lixo") is None


def test_stamp_do_momento():
    assert rotacao._stamp(AGORA) == SELO_ATUAL
    assert rotacao._stamp_mes(AGORA) == "2026-10"
