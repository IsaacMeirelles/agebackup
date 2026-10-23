"""Testes da verificação offline de integridade (--check)."""

from agebackup import manifest as manifest_mod
from agebackup.verificacao import verificar


def _registro(drive_id: str = "F1", nome: str = "doc.txt", tamanho: int = 4):
    return manifest_mod.Registro(
        drive_id=drive_id,
        nome=nome,
        tamanho=tamanho,
        modificado="2026-01-01T10:00:00Z",
        baixado_em="2026-01-01T10:00:00Z",
    )


def _preparar(tmp_path, registros, arquivos):
    for caminho, conteudo in arquivos.items():
        alvo = tmp_path / caminho
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(conteudo)
    manifest_mod.salvar(tmp_path, registros)


def test_tudo_ok(tmp_path):
    _preparar(tmp_path, {"doc.txt": _registro()}, {"doc.txt": b"abcd"})

    resultado = verificar(tmp_path)

    assert resultado.problemas is False
    assert resultado.verificados == 1
    assert resultado.faltando == []
    assert resultado.tamanho_divergente == []
    assert resultado.fora_do_manifesto == []


def test_arquivo_faltando_e_erro(tmp_path):
    _preparar(tmp_path, {"doc.txt": _registro()}, {})

    resultado = verificar(tmp_path)

    assert resultado.problemas is True
    assert resultado.faltando == ["doc.txt"]


def test_tamanho_divergente_e_erro(tmp_path):
    _preparar(tmp_path, {"doc.txt": _registro(tamanho=4)}, {"doc.txt": b"abc"})

    resultado = verificar(tmp_path)

    assert resultado.problemas is True
    assert resultado.tamanho_divergente == [("doc.txt", 4, 3)]


def test_manifesto_ausente_e_erro(tmp_path):
    (tmp_path / "solto.txt").write_bytes(b"x")

    resultado = verificar(tmp_path)

    assert resultado.manifesto_inutilizavel is True
    assert resultado.problemas is True
    assert resultado.verificados == 0
    assert resultado.fora_do_manifesto == ["solto.txt"]


def test_manifesto_corrompido_e_erro(tmp_path):
    manifest_mod.caminho_manifesto(tmp_path).write_text("{ruim", encoding="utf-8")

    resultado = verificar(tmp_path)

    assert resultado.manifesto_inutilizavel is True
    assert resultado.problemas is True


def test_temporario_e_so_aviso(tmp_path):
    _preparar(tmp_path, {"doc.txt": _registro()}, {"doc.txt": b"abcd"})
    (tmp_path / "parcial.tmp").write_bytes(b"meio")

    resultado = verificar(tmp_path)

    assert resultado.problemas is False
    assert resultado.tmp_orfaos == ["parcial.tmp"]


def test_arquivo_alheio_e_informativo(tmp_path):
    _preparar(tmp_path, {"doc.txt": _registro()}, {"doc.txt": b"abcd"})
    (tmp_path / "meu.txt").write_text("anotacao")

    resultado = verificar(tmp_path)

    assert resultado.fora_do_manifesto == ["meu.txt"]
    assert resultado.problemas is False


def test_internos_do_agebackup_nao_contam(tmp_path):
    _preparar(tmp_path, {"doc.txt": _registro()}, {"doc.txt": b"abcd"})
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / ".agebackup-falhas.log").write_text("x", encoding="utf-8")
    (logs / ".agebackup-removidos.log").write_text("x", encoding="utf-8")
    (logs / ".agebackup-envios.log").write_text("x", encoding="utf-8")
    (logs / ".agebackup-falhas.log.2026-09.log.gz").write_bytes(b"x")
    (logs / ".agebackup-removidos.log.2026-09.log.gz").write_bytes(b"x")
    (logs / ".agebackup-envios.log.2026-09.log.gz").write_bytes(b"x")
    (logs / ".agebackup-mes").write_text("2026-10", encoding="utf-8")

    resultado = verificar(tmp_path)

    assert resultado.fora_do_manifesto == []


def test_sidecar_registrado_como_companheira_nao_conta(tmp_path):
    registros = {"Grande.pdf": _registro(drive_id="G1", nome="Grande.pdf", tamanho=4)}
    _preparar(
        tmp_path,
        registros,
        {"Grande.pdf": b"%PDF", "Grande.reconstruido.pptx": b"PK"},
    )

    resultado = verificar(tmp_path)

    # O sidecar nunca entra no manifesto, mas tambem nao e "arquivo alheio".
    assert resultado.fora_do_manifesto == []
    assert resultado.problemas is False
