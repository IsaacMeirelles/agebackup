"""Testes do manifesto e da detecção de remoções na origem."""

import json

from agebackup import manifest
from agebackup.manifest import Registro


def _registro(drive_id: str = "F1", nome: str = "a.pdf") -> Registro:
    return Registro(
        drive_id=drive_id,
        nome=nome,
        tamanho=100,
        modificado="2026-01-01T10:00:00Z",
        baixado_em="2026-01-01T10:00:00Z",
    )


def test_manifesto_vazio_sem_arquivo(tmp_path):
    assert manifest.carregar(tmp_path) == {}


def test_salvar_e_carregar_roundtrip(tmp_path):
    registros = {"a.pdf": _registro()}

    assert manifest.salvar(tmp_path, registros) is True

    assert manifest.carregar(tmp_path)["a.pdf"].drive_id == "F1"


def test_manifesto_ignora_versao_desconhecida(tmp_path):
    caminho = manifest.caminho_manifesto(tmp_path)
    caminho.write_text(json.dumps({"version": 99, "arquivos": {}}), encoding="utf-8")

    assert manifest.carregar(tmp_path) == {}


def test_manifesto_ignora_json_corrompido(tmp_path):
    caminho = manifest.caminho_manifesto(tmp_path)
    caminho.write_text("{quebrado", encoding="utf-8")

    assert manifest.carregar(tmp_path) == {}


def test_manifesto_ignora_entrada_invalida(tmp_path):
    caminho = manifest.caminho_manifesto(tmp_path)
    caminho.write_text(
        json.dumps(
            {
                "version": manifest.MANIFEST_VERSION,
                "arquivos": {
                    "a.pdf": {"drive_id": "F1"},
                    "b.pdf": {"campo": "fantasma"},
                },
            }
        ),
        encoding="utf-8",
    )

    # Só a entrada completa é aproveitada.
    assert manifest.carregar(tmp_path) == {}


def test_salvar_e_atomico(tmp_path):
    manifest.salvar(tmp_path, {"a.pdf": _registro()})

    # Nenhum .tmp deve sobrar.
    assert not list(tmp_path.glob("*.tmp"))


def test_registrar_cria_entrada(tmp_path):
    registros: dict = {}
    manifest.registrar(
        registros, "sub/a.pdf", "F1", "a.pdf", 100, "2026-01-01T10:00:00Z"
    )

    assert registros["sub/a.pdf"].drive_id == "F1"


def test_reenquadrar_move_a_entrada_preservando_historico():
    registros: dict = {}
    manifest.registrar(
        registros, "velho/a.pdf", "F1", "a.pdf", 100, "2026-01-01T10:00:00Z"
    )
    baixado_em = registros["velho/a.pdf"].baixado_em

    manifest.reenquadrar(
        registros,
        "velho/a.pdf",
        "novo/b.pdf",
        nome="b.pdf",
        modificado="2026-02-02T10:00:00Z",
    )

    assert "velho/a.pdf" not in registros
    registro = registros["novo/b.pdf"]
    assert registro.drive_id == "F1"
    assert registro.tamanho == 100
    # A data do primeiro download é história: não se perde no renome.
    assert registro.baixado_em == baixado_em
    assert registro.nome == "b.pdf"
    assert registro.modificado == "2026-02-02T10:00:00Z"


def test_reenquadrar_sem_entrada_antiga_nao_faz_nada():
    registros: dict = {}

    manifest.reenquadrar(
        registros, "nao/existe.pdf", "novo.pdf", nome="x", modificado="y"
    )

    assert registros == {}


def test_reenquadrar_substitui_entrada_obsoleta_no_destino():
    registros = {"antigo.pdf": _registro("F1"), "novo.pdf": _registro("F2")}

    manifest.reenquadrar(registros, "antigo.pdf", "novo.pdf", nome="n", modificado="m")

    # O arquivo de F2 não existe mais no destino; a entrada de F1 assume o lugar.
    assert list(registros) == ["novo.pdf"]
    assert registros["novo.pdf"].drive_id == "F1"


def test_detecta_removido(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    registros = {"a.pdf": _registro("F1")}

    removidos = manifest.detectar_removidos(tmp_path, registros, {"F2"}, True)

    assert removidos == ["a.pdf"]


def test_nao_detecta_arquivo_ainda_no_drive(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    registros = {"a.pdf": _registro("F1")}

    assert manifest.detectar_removidos(tmp_path, registros, {"F1"}, True) == []


def test_arquivo_local_alheio_nao_e_removido(tmp_path):
    # Colocado por outra pessoa, nunca baixado pelo agebackup.
    (tmp_path / "nota.txt").write_text("anotacao")
    registros = {"a.pdf": _registro("F1")}

    assert manifest.detectar_removidos(tmp_path, registros, set(), True) == []


def test_arquivos_do_agebackup_sao_ignorados(tmp_path):
    registros = {".agebackup-manifest.json": _registro("F1")}
    (tmp_path / ".agebackup-manifest.json").write_text("{}")

    assert manifest.detectar_removidos(tmp_path, registros, set(), True) == []


def test_arquivo_temporario_e_ignorado(tmp_path):
    (tmp_path / "a.pdf.tmp").write_bytes(b"parcial")
    registros = {"a.pdf.tmp": _registro("F1")}

    assert manifest.detectar_removidos(tmp_path, registros, set(), True) == []


def test_listagem_incompleta_nao_reporta_nada(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    registros = {"a.pdf": _registro("F1")}

    assert manifest.detectar_removidos(tmp_path, registros, set(), False) == []


def test_arquivo_removido_que_sumiu_do_disco_nao_e_reportado(tmp_path):
    # Está no manifesto mas não existe mais localmente: já foi limpo antes.
    registros = {"a.pdf": _registro("F1")}

    assert manifest.detectar_removidos(tmp_path, registros, set(), True) == []


def test_detalha_pastas(tmp_path):
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "a.pdf").write_bytes(b"x")
    registros = {"2026/a.pdf": _registro("F1")}

    assert manifest.detectar_removidos(tmp_path, registros, set(), True) == [
        "2026/a.pdf"
    ]


def test_registrar_removidos_escreve_log_e_limpa_manifesto(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    registros = {"a.pdf": _registro("F1"), "b.pdf": _registro("F2")}

    log = manifest.registrar_removidos(tmp_path, ["a.pdf"], registros)

    assert log is not None
    assert log.exists()
    assert "a.pdf" in log.read_text(encoding="utf-8")
    # Sai do manifesto para não ser reportado de novo.
    assert "a.pdf" not in registros
    assert "b.pdf" in registros


def test_registrar_removidos_acumula_execucoes(tmp_path):
    registros: dict = {}
    manifest.registrar_removidos(tmp_path, ["a.pdf"], registros)
    manifest.registrar_removidos(tmp_path, ["b.pdf"], registros)

    texto = manifest.caminho_removidos(tmp_path).read_text(encoding="utf-8")

    assert "a.pdf" in texto
    assert "b.pdf" in texto


def test_registrar_removidos_sem_nada_nao_cria_log(tmp_path):
    assert manifest.registrar_removidos(tmp_path, [], {}) is None
    assert not manifest.caminho_removidos(tmp_path).exists()


def test_registrar_removidos_nao_apaga_arquivos(tmp_path):
    arquivo = tmp_path / "a.pdf"
    arquivo.write_bytes(b"conteudo importante")
    registros = {"a.pdf": _registro("F1")}

    manifest.registrar_removidos(tmp_path, ["a.pdf"], registros)

    assert arquivo.read_bytes() == b"conteudo importante"
