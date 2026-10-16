"""Testes da rotação mensal dos logs.

A fronteira entre meses é decidida pelo arquivo de marca `.agebackup-mes`, não
pelo mtime do log. Os testes simulam a virada escrevendo a marca do mês
anterior e chamando a rotação com uma data no mês seguinte.
"""

import gzip
from datetime import UTC, datetime

from agebackup import rotacao

LOG = ".agebackup-falhas.log"
MES_ANTERIOR = "2026-09"
MES_ATUAL = "2026-10"
AGORA = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def _caminho(tmp_path):
    return tmp_path / LOG


def _marcar(tmp_path, mes: str):
    rotacao.caminho_marca(tmp_path).write_text(mes, encoding="utf-8")


def _escrever(caminho, texto="linha\n"):
    caminho.write_text(texto, encoding="utf-8")


def _gz(tmp_path, mes: str):
    return tmp_path / f"{LOG}.{mes}.log.gz"


def test_primeira_execucao_cria_marca(tmp_path):
    rotacao.rotacionar(_caminho(tmp_path), AGORA)

    assert rotacao.caminho_marca(tmp_path).read_text(encoding="utf-8") == MES_ATUAL


def test_primeira_execucao_nao_move_nada(tmp_path):
    log = _caminho(tmp_path)
    _escrever(log, "primeira vez\n")

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == []
    assert log.read_text(encoding="utf-8") == "primeira vez\n"


def test_mes_igual_nao_rotaciona(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    _escrever(log, "ainda neste mes\n")

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == []
    assert log.exists()


def test_virada_comprime_mes_anterior(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    _escrever(log, "falha de setembro\n")

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == [_gz(tmp_path, MES_ANTERIOR)]
    assert _gz(tmp_path, MES_ANTERIOR).exists()
    assert not log.exists(), "o log corrente deve sumir na virada"


def test_conteudo_sobrevive_a_compressao(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    original = "a\nb\nc\n"
    _escrever(log, original)

    rotacao.rotacionar(log, AGORA)

    assert (
        gzip.decompress(_gz(tmp_path, MES_ANTERIOR).read_bytes()).decode() == original
    )


def test_accentos_sobrevremem(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    original = "ação, coração, três\n"
    _escrever(log, original)

    rotacao.rotacionar(log, AGORA)

    compactado = gzip.decompress(_gz(tmp_path, MES_ANTERIOR).read_bytes())
    assert compactado.decode("utf-8") == original


def test_marca_avanca_apos_virada(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    _escrever(log)

    rotacao.rotacionar(log, AGORA)

    assert rotacao.caminho_marca(tmp_path).read_text(encoding="utf-8") == MES_ATUAL


def test_rotacao_e_idempotente(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    _escrever(log, "antigo\n")

    rotacao.rotacionar(log, AGORA)
    segundo = rotacao.rotacionar(log, AGORA)

    assert segundo.comprimidos == []
    assert len(list(tmp_path.glob(f"{LOG}.*.gz"))) == 1


def test_escrever_no_log_nao_impede_a_virada(tmp_path):
    """Regressão: gravar no mês corrente não pode esconder o log antigo."""
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    _escrever(log, "setembro\n")

    # Simula gravação no mês corrente: muda o mtime para "hoje".
    import os

    os.utime(log, (AGORA.timestamp(), AGORA.timestamp()))

    resultado = rotacao.rotacionar(log, AGORA)

    assert resultado.comprimidos == [_gz(tmp_path, MES_ANTERIOR)]


def test_varios_meses_soltos_sao_comprimidos(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    for mes in ("2026-07", "2026-08", "2026-09"):
        (tmp_path / f"{LOG}.{mes}.log").write_text("antigo\n", encoding="utf-8")

    resultado = rotacao.rotacionar(log, AGORA)

    assert len(resultado.comprimidos) == 3
    assert not list(tmp_path.glob(f"{LOG}.2026-0[789].log"))


def test_mes_corrente_solto_nao_e_comprimido(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    do_mes = tmp_path / f"{LOG}.{MES_ATUAL}.log"
    do_mes.write_text("ainda\n", encoding="utf-8")

    resultado = rotacao.rotacionar(log, AGORA)

    assert do_mes.exists()
    assert resultado.comprimidos == []


def test_nome_invalido_e_ignorado(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    invalido = tmp_path / f"{LOG}.nao-e-data.log"
    invalido.write_text("?\n", encoding="utf-8")

    rotacao.rotacionar(log, AGORA)

    assert invalido.exists(), "não deve apagar arquivo de nome inesperado"


def test_log_do_mes_anterior_e_acrescentado(tmp_path):
    """Se existir arquivo do mês, o conteúdo é somado, não sobrescrito."""
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    alvo = tmp_path / f"{LOG}.{MES_ANTERIOR}.log"
    alvo.write_text("primeira parte\n", encoding="utf-8")
    _escrever(log, "segunda parte\n")

    rotacao.rotacionar(log, AGORA)

    texto = gzip.decompress(_gz(tmp_path, MES_ANTERIOR).read_bytes()).decode()
    assert "primeira parte" in texto
    assert "segunda parte" in texto


def test_sem_log_nao_falha(tmp_path):
    _marcar(tmp_path, MES_ANTERIOR)

    resultado = rotacao.rotacionar(_caminho(tmp_path), AGORA)

    assert resultado.comprimidos == []
    assert resultado.erro == ""


def test_arquivados_ordenados(tmp_path):
    log = _caminho(tmp_path)
    for mes in ("2026-07", "2026-09", "2026-08"):
        (tmp_path / f"{LOG}.{mes}.log.gz").write_bytes(b"x")

    lista = [p.name for p in rotacao.arquivados(log)]

    assert lista[0].endswith("2026-09.log.gz")


def test_mes_do_arquivo():
    assert rotacao.mes_do_arquivo(f"{LOG}.2026-09.log.gz", LOG) == "2026-09"
    assert rotacao.mes_do_arquivo(f"{LOG}.2026-09.log", LOG) == "2026-09"
    assert rotacao.mes_do_arquivo(LOG, LOG) is None
    assert rotacao.mes_do_arquivo("outro.log", LOG) is None


def test_retencao_apaga_meses_antigos(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    gz_antigo = tmp_path / f"{LOG}.2026-06.log.gz"
    gz_antigo.write_bytes(b"antigo")
    gz_limite = tmp_path / f"{LOG}.2026-07.log.gz"
    gz_limite.write_bytes(b"no limite")

    resultado = rotacao.rotacionar(log, AGORA, meses=3)

    # Em outubro, 3 meses de histórico = jul, ago, set. Junho sai.
    assert gz_antigo in resultado.removidos
    assert not gz_antigo.exists()
    assert gz_limite.exists(), "o mês no limite exato deve ser mantido"


def test_retencao_zero_guarda_tudo(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    velho = tmp_path / f"{LOG}.2020-01.log.gz"
    velho.write_bytes(b"muito antigo")

    resultado = rotacao.rotacionar(log, AGORA, meses=0)

    assert velho.exists()
    assert resultado.removidos == []


def test_retencao_um_apaga_tudo_antereo_anterior(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    passado = tmp_path / f"{LOG}.2026-08.log.gz"
    passado.write_bytes(b"passado")
    limite = tmp_path / f"{LOG}.2026-09.log.gz"
    limite.write_bytes(b"limite")

    rotacao.rotacionar(log, AGORA, meses=1)

    # Em outubro, 1 mês de histórico = setembro. Agosto sai.
    assert not passado.exists()
    assert limite.exists()


def test_retencao_nao_apaga_log_textual(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    log.write_text("mes corrente\n", encoding="utf-8")

    rotacao.rotacionar(log, AGORA, meses=1)

    assert log.exists()


def test_retencao_ignora_nome_invalido(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ATUAL)
    invalido = tmp_path / f"{LOG}.lixo.log.gz"
    invalido.write_bytes(b"?")

    rotacao.rotacionar(log, AGORA, meses=1)

    assert invalido.exists()


def test_retencao_vazia_sem_log(tmp_path):
    resultado = rotacao.rotacionar(_caminho(tmp_path), AGORA, meses=6)

    assert resultado.removidos == []


def test_sem_compressao_move_mas_nao_comprime(tmp_path):
    log = _caminho(tmp_path)
    _marcar(tmp_path, MES_ANTERIOR)
    log.write_text("setembro\n", encoding="utf-8")

    resultado = rotacao.rotacionar(log, AGORA, comprimir=False)

    assert resultado.comprimidos == []
    assert (tmp_path / f"{LOG}.{MES_ANTERIOR}.log").exists()
    assert not list(tmp_path.glob("*.gz"))


def test_mes_para_numero_ordena():
    assert rotacao._mes_para_numero("2026-10") > rotacao._mes_para_numero("2026-09")
    assert rotacao._mes_para_numero("2027-01") > rotacao._mes_para_numero("2026-12")
