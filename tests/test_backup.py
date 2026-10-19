"""Testes do motor de backup contra um servidor HTTP local."""

import http.server
import json
import os
import re
import threading
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from agebackup import falhas as falhas_mod
from agebackup import manifest as manifest_mod
from agebackup import reconstruir as reconstruir_mod
from agebackup.backup import (
    EXPORTABLE,
    FileEntry,
    Stats,
    _destino_existente,
    _eh_pasta,
    _formatar_bytes,
    _mover_arquivo,
    executar_backup,
    listar_arquivos,
)
from agebackup.config import AccountConfig, BackupConfig, Config
from agebackup.drive import DownloadRestrictedError, DriveError, TransientDriveError

CONTEUDO = b"conteudo do backup"


def _quando(segundos: int = 0) -> str:
    momento = datetime.fromtimestamp(1_700_000_000 + segundos, tz=UTC)
    return momento.isoformat().replace("+00:00", "Z")


class _FakeDrive(http.server.BaseHTTPRequestHandler):
    """Emula a Drive API para listagem e download."""

    arquivos: ClassVar[list[dict]] = []
    paginas: ClassVar[list[dict]] = []
    paginar: ClassVar[int] = 0
    falhar_com: int | None = None
    sumidos: ClassVar[set[str]] = set()
    # mimeTypes de export que respondem 403 exportSizeLimitExceeded (grande demais).
    exportar_grande: ClassVar[set[str]] = set()

    @classmethod
    def arquivos_page(cls, pagina_atual: int = 0) -> dict:
        """Devolve uma página; inclui token enquanto houver páginas restantes."""
        if pagina_atual == 0:
            dados: dict = {"files": cls.arquivos}
        else:
            dados = cls.paginas[min(pagina_atual, len(cls.paginas)) - 1]

        if pagina_atual < cls.paginar:
            dados = {**dados, "nextPageToken": str(pagina_atual + 1)}
        return dados

    def log_message(self, *args: object) -> None:
        pass

    def _json(self, dados: dict, status: int = 200) -> None:
        body = json.dumps(dados).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # nome exigido pelo BaseHTTPRequestHandler
        if "alt=media" in self.path:
            # Export de documento do Workspace: simula o limite de 10 MB quando o
            # mimeType pedido está marcado, para exercitar o fallback para PDF.
            consulta = urllib.parse.unquote_plus(self.path.split("?", 1)[-1])
            mime = urllib.parse.parse_qs(consulta).get("mimeType", [""])[0]
            if mime and mime in self.exportar_grande:
                self._json(
                    {
                        "error": {
                            "code": 403,
                            "message": "This file is too large to be exported.",
                            "errors": [
                                {
                                    "reason": "exportSizeLimitExceeded",
                                    "message": "This file is too large to be exported.",
                                }
                            ],
                        }
                    },
                    403,
                )
                return

        if self.falhar_com and "alt=media" in self.path:
            motivo = "rateLimitExceeded" if self.falhar_com == 429 else "notFound"
            self._json(
                {
                    "error": {
                        "code": self.falhar_com,
                        "message": "erro",
                        "errors": [{"reason": motivo, "message": "erro"}],
                    }
                },
                self.falhar_com,
            )
            return

        if "alt=media" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(CONTEUDO)))
            self.end_headers()
            self.wfile.write(CONTEUDO)
            return

        sem_query = self.path.split("?")[0]
        query = urllib.parse.unquote_plus(self.path.split("?")[-1])

        if sem_query.endswith("/files"):
            filtro = re.search(r"'([^']+)' in parents", query)
            if filtro:
                pai = filtro.group(1)
                filhos = [
                    item for item in self.arquivos if pai in (item.get("parents") or [])
                ]
                self._json({"files": filhos})
            elif "pageToken=" in query:
                token = query.split("pageToken=")[-1].split("&")[0]
                self._json(self.arquivos_page(int(token)))
            else:
                self._json(self.arquivos_page(0))
            return

        file_id = sem_query.rsplit("/", 1)[-1]
        if file_id in self.sumidos:
            self._json(
                {
                    "error": {
                        "code": 404,
                        "message": "File not found",
                        "errors": [{"reason": "notFound", "message": "File not found"}],
                    }
                },
                404,
            )
            return
        item = next((a for a in self.arquivos if a["id"] == file_id), {})
        self._json(item)


@pytest.fixture
def service():
    _FakeDrive.arquivos = []
    _FakeDrive.paginas = [{"files": []}]
    _FakeDrive.paginar = 0
    _FakeDrive.falhar_com = None
    _FakeDrive.sumidos = set()
    _FakeDrive.exportar_grande = set()

    srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeDrive)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    svc = build(
        "drive", "v3", credentials=Credentials(token="fake"), cache_discovery=False
    )
    svc._baseUrl = f"http://127.0.0.1:{srv.server_address[1]}/"
    yield svc
    srv.shutdown()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        account=AccountConfig(email="u@e.com"),
        backup=BackupConfig(destination=str(tmp_path / "backup")),
    )


@pytest.fixture(autouse=True)
def sem_reconstrucao(monkeypatch):
    """Impede que os testes de backup chamem as APIs nativas de verdade.

    Por padrão a reconstrução se comporta como API indisponível (falha silenciosa)
    e o download assíncrono (`files.download`) também. Testes que querem exercitar
    qualquer um dos dois substituem este patch.
    """

    def indisponivel(*args, **kwargs):
        raise reconstruir_mod.ReconstrucaoIndisponivel("API nativa indisponível")

    def sem_lro(*args, **kwargs):
        raise DriveError("files.download indisponível no teste")

    monkeypatch.setattr(reconstruir_mod, "reconstruir", indisponivel)
    monkeypatch.setattr("agebackup.backup.download_document_async", sem_lro)


def _arquivo(file_id: str = "F1", nome: str = "doc.txt", **extra) -> dict:
    return {
        "id": file_id,
        "name": nome,
        "mimeType": "text/plain",
        "size": str(len(CONTEUDO)),
        "modifiedTime": _quando(),
        "trashed": False,
        **extra,
    }


def _pasta(file_id: str = "P1", nome: str = "pasta", **extra) -> dict:
    return {
        "id": file_id,
        "name": nome,
        "mimeType": "application/vnd.google-apps.folder",
        "trashed": False,
        **extra,
    }


def test_listar_arquivos_basico(service):
    _FakeDrive.arquivos = [_arquivo()]

    itens = list(listar_arquivos(service))

    assert len(itens) == 1
    assert itens[0].file_id == "F1"
    assert itens[0].size == len(CONTEUDO)


def test_listar_arquivos_percorre_paginacao(service):
    _FakeDrive.arquivos = [_arquivo()]
    _FakeDrive.paginas = [{"files": [_arquivo("F2", "b.txt")]}]
    _FakeDrive.paginar = 1

    ids = [item.file_id for item in listar_arquivos(service)]
    assert ids == ["F1", "F2"]


def test_listar_filtra_pasta_do_drive(service):
    _FakeDrive.arquivos = [
        _pasta("PASTA", "Minha Pasta"),
        _arquivo(parents=["PASTA"]),
        _arquivo("F9", "fora.txt"),
    ]

    itens = list(listar_arquivos(service, folder_id="PASTA"))

    assert len(itens) == 1
    assert itens[0].file_id == "F1"
    assert itens[0].pastas == ("Minha Pasta",)


def test_listar_desce_nas_subpastas(service):
    _FakeDrive.arquivos = [
        _arquivo("F1", "raiz.txt"),
        _pasta("P1", "Fotos"),
        _arquivo("F2", "gato.jpg", parents=["P1"]),
        _pasta("P2", "2026", parents=["P1"]),
        _arquivo("F3", "praia.jpg", parents=["P2"]),
    ]

    itens = {item.file_id: item for item in listar_arquivos(service)}

    assert itens["F1"].pastas == ()
    assert itens["F2"].pastas == ("Fotos",)
    assert itens["F3"].pastas == ("Fotos", "2026")


def test_listar_nunca_devolve_pastas(service):
    _FakeDrive.arquivos = [
        _pasta("P1", "Vazia"),
        _pasta("P2", "Cheia", parents=["P1"]),
        _arquivo("F1", "dentro.txt", parents=["P2"]),
    ]

    itens = list(listar_arquivos(service))

    assert [item.file_id for item in itens] == ["F1"]


def test_listar_recursivo_a_partir_de_pasta(service):
    _FakeDrive.arquivos = [
        _pasta("P1", "Fotos"),
        _arquivo("F2", "gato.jpg", parents=["P1"]),
        _pasta("P2", "2026", parents=["P1"]),
        _arquivo("F3", "praia.jpg", parents=["P2"]),
        _arquivo("F9", "fora.txt"),
    ]

    itens = {item.file_id: item for item in listar_arquivos(service, folder_id="P1")}

    assert set(itens) == {"F2", "F3"}
    assert itens["F2"].pastas == ("Fotos",)
    assert itens["F3"].pastas == ("Fotos", "2026")


def test_listar_ignora_lixeira(service):
    _FakeDrive.arquivos = [_arquivo(nome="apagado.txt")]

    itens = list(listar_arquivos(service))

    # A query trashed=false ja filtra no servidor; o filtro local e uma garantia extra.
    assert all(not item.trashed for item in itens)


def test_backup_baixa_arquivo(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 1
    assert stats.falhas == 0
    assert (destino / "doc.txt").read_bytes() == CONTEUDO


def test_backup_ignora_arquivo_inalterado(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)
    stats = executar_backup(service, config, destino)

    assert stats.ignorados == 1
    assert stats.baixados == 0


def test_backup_redownload_quando_modificado(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo(modifiedTime=_quando(600))]
    stats = executar_backup(service, config, destino)

    assert stats.baixados == 1


def test_backup_move_quando_renomeado_no_drive(service, config, tmp_path, capsys):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo(nome="renomeado.txt")]
    stats = executar_backup(service, config, destino)

    assert stats.renomeados == 1
    assert stats.baixados == 0
    assert not (destino / "doc.txt").exists()
    assert (destino / "renomeado.txt").read_bytes() == CONTEUDO
    assert list(manifest_mod.carregar(destino)) == ["renomeado.txt"]
    assert "movido" in capsys.readouterr().out


def test_backup_move_quando_mudou_de_pasta(service, config, tmp_path):
    _FakeDrive.arquivos = [_pasta("P1", "Docs"), _arquivo(parents=["P1"])]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_pasta("P1", "Arquivos"), _arquivo(parents=["P1"])]
    stats = executar_backup(service, config, destino)

    assert stats.renomeados == 1
    assert stats.baixados == 0
    assert not (destino / "Docs" / "doc.txt").exists()
    assert (destino / "Arquivos" / "doc.txt").read_bytes() == CONTEUDO
    assert list(manifest_mod.carregar(destino)) == ["Arquivos/doc.txt"]


def test_backup_dry_run_move_so_reporta(service, config, tmp_path, capsys):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo(nome="renomeado.txt")]
    stats = executar_backup(service, config, destino, dry_run=True)

    assert stats.renomeados == 1
    assert stats.baixados == 0
    # Simulacao: nada muda no disco nem no manifesto.
    assert (destino / "doc.txt").exists()
    assert not (destino / "renomeado.txt").exists()
    assert list(manifest_mod.carregar(destino)) == ["doc.txt"]
    assert "moveria" in capsys.readouterr().out


def test_backup_nao_move_quando_destino_ocupado(service, config, tmp_path, capsys):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    # Ja existe um arquivo diferente com o nome novo: nao pode ser sobrescrito
    # nem empurrado para um "(1)", que viraria vaivem a cada execucao.
    (destino / "renomeado.txt").write_bytes(b"de outra pessoa")

    _FakeDrive.arquivos = [_arquivo(nome="renomeado.txt")]
    stats = executar_backup(service, config, destino)

    assert stats.renomeados == 0
    assert stats.ignorados == 1
    assert stats.baixados == 0
    assert (destino / "renomeado.txt").read_bytes() == b"de outra pessoa"
    assert (destino / "doc.txt").read_bytes() == CONTEUDO
    assert list(manifest_mod.carregar(destino)) == ["doc.txt"]
    assert "ocupado" in capsys.readouterr().out

    # Estavel: repetir nao muda nada.
    terceira = executar_backup(service, config, destino)
    assert terceira.renomeados == 0
    assert terceira.baixados == 0


def test_backup_renome_conteudo_mudou_baixa_e_deixa_orfao(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo(nome="novo.txt", modifiedTime=_quando(600))]
    stats = executar_backup(service, config, destino)

    # Conteudo mudou: nao da para so mover; baixa de novo. Filosofia "nunca
    # apaga": a copia antiga fica onde esta (o --check a lista como informativa).
    assert stats.baixados == 1
    assert stats.renomeados == 0
    assert (destino / "novo.txt").exists()
    assert (destino / "doc.txt").exists()
    assert list(manifest_mod.carregar(destino)) == ["novo.txt"]


def test_backup_move_grande_em_pdf_mantendo_reserva(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(15 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {EXPORTABLE["application/vnd.google-apps.spreadsheet"]}
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)
    assert (destino / "planilha.pdf").exists()

    # Renomeou no Drive: move, mas continua em PDF (e o registro nao vira .xlsx).
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha-renomeada",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(15 * 1024 * 1024),
        )
    ]
    stats = executar_backup(service, config, destino)

    assert stats.renomeados == 1
    assert stats.baixados == 0
    assert (destino / "planilha-renomeada.pdf").exists()
    assert not (destino / "planilha.pdf").exists()
    assert not (destino / "planilha-renomeada.xlsx").exists()
    assert list(manifest_mod.carregar(destino)) == ["planilha-renomeada.pdf"]

    # Terceira execucao: estavel, sem mover nada de novo.
    terceira = executar_backup(service, config, destino)
    assert terceira.ignorados == 1
    assert terceira.renomeados == 0


def test_mover_arquivo_move_sidecars_com_novo_stem(tmp_path):
    destino = tmp_path / "backup"
    (destino / "sub").mkdir(parents=True)
    (destino / "sub" / "Grande.pdf").write_bytes(b"%PDF")
    (destino / "sub" / "Grande.reconstruido.pptx").write_bytes(b"PK")

    final = _mover_arquivo(
        destino,
        "sub/Grande.pdf",
        destino / "sub" / "Apresentacao.pdf",
        registros={},
    )

    assert final == "sub/Apresentacao.pdf"
    assert (destino / "sub" / "Apresentacao.pdf").read_bytes() == b"%PDF"
    # Ganha o stem novo, para original_recuperado continuar casando.
    assert (destino / "sub" / "Apresentacao.reconstruido.pptx").read_bytes() == b"PK"
    assert not (destino / "sub" / "Grande.pdf").exists()
    assert not (destino / "sub" / "Grande.reconstruido.pptx").exists()


def test_mover_arquivo_nao_arrasta_sidecar_registrado(tmp_path):
    destino = tmp_path / "backup"
    destino.mkdir(parents=True)
    (destino / "Grande.pdf").write_bytes(b"%PDF")
    (destino / "Grande.reconstruido.pptx").write_bytes(b"meu")
    # Nome igual, mas e outro arquivo do Drive (consta no manifesto).
    (destino / "Grande.pptx").write_bytes(b"outro")
    registros = {
        "Grande.pdf": manifest_mod.Registro(
            drive_id="G1",
            nome="Grande",
            tamanho=4,
            modificado="2026-01-01T10:00:00Z",
            baixado_em="2026-01-01T10:00:00Z",
        ),
        "Grande.pptx": manifest_mod.Registro(
            drive_id="O1",
            nome="Grande.pptx",
            tamanho=5,
            modificado="2026-01-01T10:00:00Z",
            baixado_em="2026-01-01T10:00:00Z",
        ),
    }

    final = _mover_arquivo(destino, "Grande.pdf", destino / "Nova.pdf", registros)

    assert final == "Nova.pdf"
    assert (destino / "Nova.pdf").read_bytes() == b"%PDF"
    assert (destino / "Nova.reconstruido.pptx").read_bytes() == b"meu"
    assert (destino / "Grande.pptx").read_bytes() == b"outro"


def test_backup_pula_pastas(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo(nome="minha-pasta", mimeType="application/vnd.google-apps.folder")
    ]

    stats = executar_backup(service, config, tmp_path / "backup")

    assert stats.total == 0


def test_backup_espelha_arvore_de_pastas(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _pasta("P1", "Fotos"),
        _arquivo("F2", "gato.jpg", parents=["P1"]),
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 1
    assert (destino / "Fotos" / "gato.jpg").read_bytes() == CONTEUDO


def test_backup_nao_rebaixa_aninhado_na_segunda_vez(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _pasta("P1", "Fotos"),
        _arquivo("F2", "gato.jpg", parents=["P1"]),
    ]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 0
    assert stats.ignorados == 1


def test_backup_de_pasta_configurada_espelha_subpastas(service, tmp_path):
    config = Config(
        account=AccountConfig(email="u@e.com"),
        backup=BackupConfig(destination=str(tmp_path / "backup"), folder_id="P1"),
    )
    _FakeDrive.arquivos = [
        _pasta("P1", "Fotos"),
        _arquivo("F2", "gato.jpg", parents=["P1"]),
        _pasta("P2", "2026", parents=["P1"]),
        _arquivo("F3", "praia.jpg", parents=["P2"]),
        _arquivo("F9", "fora.txt"),
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 2
    assert (destino / "Fotos" / "gato.jpg").exists()
    assert (destino / "Fotos" / "2026" / "praia.jpg").exists()
    assert not (destino / "fora.txt").exists()


def test_backup_exporta_documento_google(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo(nome="planilha", mimeType="application/vnd.google-apps.spreadsheet")
    ]

    stats = executar_backup(service, config, tmp_path / "backup")

    assert stats.baixados == 1


def test_backup_dry_run_nao_grava(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino, dry_run=True)

    assert stats.baixados == 1
    assert not (destino / "doc.txt").exists()


def test_backup_contabiliza_falha_sem_parar(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]
    _FakeDrive.falhar_com = 403

    stats = executar_backup(service, config, tmp_path / "backup")

    assert stats.falhas == 2
    assert len(stats.erros) == 2


def test_backup_erro_local_e_registrado(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo()]
    destino = tmp_path / "backup"
    destino.mkdir(parents=True)
    destino.chmod(0o500)

    try:
        stats = executar_backup(service, config, destino)
        assert stats.falhas == 1
    finally:
        destino.chmod(0o700)


def test_stats_resumo_sem_falhas():
    assert Stats(total=3, baixados=2, ignorados=1).resumo() == (
        "3 arquivos, 2 baixados, 1 inalterados"
    )


def test_stats_resumo_inclui_falhas():
    assert "1 falhas" in Stats(total=1, falhas=1).resumo()


def test_stats_resumo_inclui_movidos():
    assert "2 movidos" in Stats(total=5, renomeados=2).resumo()


def test_stats_resumo_movidos_no_dry_run():
    assert "1 a mover" in Stats(total=1, renomeados=1, dry_run=True).resumo()


def test_formatar_bytes():
    assert _formatar_bytes(512) == "512B"
    assert _formatar_bytes(2048) == "2.0KB"
    assert _formatar_bytes(5 * 1024 * 1024) == "5.0MB"


def test_eh_pasta():
    assert _eh_pasta("application/vnd.google-apps.folder") is True
    assert _eh_pasta("text/plain") is False


def test_exportable_tem_mapeamento_completo():
    assert (
        EXPORTABLE["application/vnd.google-apps.document"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert (
        EXPORTABLE["application/vnd.google-apps.spreadsheet"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert (
        EXPORTABLE["application/vnd.google-apps.presentation"]
        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert all(chave.startswith("application/vnd.google-apps.") for chave in EXPORTABLE)


def test_destino_existente_detecta_inalterado(tmp_path):
    arquivo = tmp_path / "doc.txt"
    arquivo.write_bytes(b"x")
    os.utime(arquivo, (1_700_000_000, 1_700_000_000))
    entrada = FileEntry("F", "doc.txt", "text/plain", 1, _quando())

    assert _destino_existente(arquivo, entrada) == arquivo


def test_destino_existente_ausente(tmp_path):
    entrada = FileEntry("F", "novo.txt", "text/plain", 1, _quando())

    assert _destino_existente(tmp_path / "novo.txt", entrada) is None


def test_destino_existente_sem_timestamp_nao_confia(tmp_path):
    arquivo = tmp_path / "doc.txt"
    arquivo.write_bytes(b"x")
    entrada = FileEntry("F", "doc.txt", "text/plain", 1, "")

    assert _destino_existente(arquivo, entrada) is None


def test_transient_e_reexportado():
    assert issubclass(TransientDriveError, Exception)
    assert issubclass(DownloadRestrictedError, Exception)


def test_backup_registra_removido_na_origem(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    stats = executar_backup(service, config, destino)

    assert stats.removidos_na_origem == 1
    log = destino / "logs" / ".agebackup-removidos.log"
    assert "b.txt" in log.read_text(encoding="utf-8")


def test_backup_classifica_remocao_sem_acesso(service, config, tmp_path):
    """Arquivo que sumiu da listagem e dá 404 vira 'sem acesso', não removido."""
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.sumidos = {"F2"}
    stats = executar_backup(service, config, destino)

    assert stats.removidos_sem_acesso == 1
    assert stats.removidos_na_origem == 0
    assert "1 sem acesso (fora do escopo)" in stats.resumo()
    log = destino / "logs" / ".agebackup-removidos.log"
    assert "sem_acesso\tb.txt" in log.read_text(encoding="utf-8")
    # Não apaga o arquivo local: ele pode voltar ao escopo.
    assert (destino / "b.txt").exists()


def test_backup_classifica_remocao_excluido(service, config, tmp_path):
    """Arquivo na lixeira do Drive é registrado como excluído."""
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [
        _arquivo("F1", "a.txt"),
        _arquivo("F2", "b.txt", trashed=True),
    ]
    stats = executar_backup(service, config, destino)

    assert stats.removidos_na_origem == 1
    assert stats.removidos_sem_acesso == 0
    log = destino / "logs" / ".agebackup-removidos.log"
    assert "excluido\tb.txt" in log.read_text(encoding="utf-8")


def test_backup_nao_apaga_arquivo_removido(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = []
    executar_backup(service, config, destino)

    assert (destino / "b.txt").exists()


def test_backup_nao_reporta_removido_na_segunda_vez(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = []
    executar_backup(service, config, destino)
    stats = executar_backup(service, config, destino)

    assert stats.removidos_na_origem == 0


def test_backup_dry_run_nao_gera_log_de_remocoes(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = []
    executar_backup(service, config, destino, dry_run=True)

    assert not (destino / "logs" / ".agebackup-removidos.log").exists()


def test_manifesto_e_gravado_apos_backup(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    manifesto = destino / ".agebackup-manifest.json"
    assert manifesto.exists()
    assert "a.txt" in manifesto.read_text(encoding="utf-8")


def test_manifesto_nao_e_listado_como_arquivo_novo(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    stats = executar_backup(service, config, destino)

    assert stats.removidos_na_origem == 0
    assert stats.total == 1


def test_backup_grava_log_de_falhas(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    log = destino / "logs" / ".agebackup-falhas.log"
    assert log.exists()
    assert "a.txt" in log.read_text(encoding="utf-8")


def test_backup_registra_categoria_da_falha(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    texto = (destino / "logs" / ".agebackup-falhas.log").read_text(encoding="utf-8")
    assert "bloqueado" in texto


def test_backup_dry_run_nao_gera_log_de_falhas(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino, dry_run=True)

    assert not (destino / "logs" / ".agebackup-falhas.log").exists()


def test_backup_sem_falhas_nao_cria_log(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert not (destino / "logs" / ".agebackup-falhas.log").exists()


def test_logs_do_agebackup_nao_sao_tratados_como_removidos(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)
    stats = executar_backup(service, config, destino)

    assert stats.removidos_na_origem == 0


def test_video_do_vids_e_baixado_por_lro(service, config, tmp_path, monkeypatch):
    """Google Vids não aceita files.export; é baixado como MP4 pelo files.download."""
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]
    destino = tmp_path / "backup"

    def lro_falso(servico, file_id, alvo, mime_type):
        assert file_id == "V1"
        assert mime_type == "video/mp4"
        assert alvo.name == "meu-video.mp4"
        alvo.write_bytes(b"mp4")
        return alvo

    monkeypatch.setattr("agebackup.backup.download_document_async", lro_falso)

    stats = executar_backup(service, config, destino)

    assert stats.falhas == 0
    assert stats.baixados == 1
    assert stats.requer_lro == 1
    assert (destino / "meu-video.mp4").read_bytes() == b"mp4"
    # Vids não tem export nem PDF de reserva.
    assert not list(destino.glob("*.pdf"))


def test_video_do_vids_falha_vira_falha_do_arquivo(service, config, tmp_path):
    """Sem o files.download, o Vids é registrado como falha e o backup segue."""
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]
    destino = tmp_path / "backup"
    # A fixture autouse `sem_reconstrucao` faz download_document_async falhar.

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 0
    assert stats.falhas == 1
    assert stats.requer_lro == 0


def test_documento_acima_do_limite_cai_para_pdf(service, config, tmp_path):
    """O formato principal estoura os 10 MB; o PDF costuma caber e é usado."""
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha-grande",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(15 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {EXPORTABLE["application/vnd.google-apps.spreadsheet"]}
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.requer_lro == 0
    assert stats.baixados == 1
    assert stats.originais_pendentes == 1
    assert (destino / "planilha-grande.pdf").read_bytes() == CONTEUDO
    assert not (destino / "planilha-grande.xlsx").exists()


def test_documento_grande_reconstroi_original_editavel(
    service, config, tmp_path, monkeypatch
):
    """Com a API nativa disponível, o original editável sai ao lado do PDF."""
    _FakeDrive.arquivos = [
        _arquivo(
            "P1",
            "apresentacao-grande",
            mimeType="application/vnd.google-apps.presentation",
            size=str(15 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {
        EXPORTABLE["application/vnd.google-apps.presentation"]
    }
    destino = tmp_path / "backup"

    def reconstruir_falso(mime_type, file_id, alvo):
        assert mime_type == "application/vnd.google-apps.presentation"
        alvo.write_bytes(b"pptx reconstruido")
        return alvo

    monkeypatch.setattr(reconstruir_mod, "reconstruir", reconstruir_falso)

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 1
    assert stats.originais_pendentes == 1
    assert (destino / "apresentacao-grande.pdf").read_bytes() == CONTEUDO
    reconstruido = destino / "apresentacao-grande.reconstruido.pptx"
    assert reconstruido.read_bytes() == b"pptx reconstruido"
    # O sidecar não entra no manifesto: o PDF é quem representa o arquivo.
    manifesto = (destino / ".agebackup-manifest.json").read_text(encoding="utf-8")
    assert "reconstruido" not in manifesto


def test_reconstrucao_indisponivel_mantem_pdf(service, config, tmp_path):
    """Sem a Docs API, o PDF permanece e um .md editável sai ao lado."""
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "documento-grande",
            mimeType="application/vnd.google-apps.document",
            size=str(15 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {EXPORTABLE["application/vnd.google-apps.document"]}
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.falhas == 0
    assert stats.originais_pendentes == 1
    assert (destino / "documento-grande.pdf").read_bytes() == CONTEUDO
    assert not (destino / "documento-grande.reconstruido.docx").exists()
    # O texto saiu como Markdown (export do Drive), que dispensa a Docs API.
    assert (destino / "documento-grande.reconstruido.md").read_bytes() == CONTEUDO
    texto = (destino / "logs" / ".agebackup-falhas.log").read_text(encoding="utf-8")
    assert "grande_demais" in texto


def test_nativo_grande_baixa_o_original_direto(service, config, tmp_path, monkeypatch):
    """O files.download (LRO) traz o próprio original, sem o limite de 10 MB.

    Melhor que o PDF: preserva o formato editável e não exige a API nativa.
    """
    _FakeDrive.arquivos = [
        _arquivo(
            "P1",
            "proposta",
            mimeType="application/vnd.google-apps.presentation",
            size=str(12 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {
        EXPORTABLE["application/vnd.google-apps.presentation"]
    }
    destino = tmp_path / "backup"

    def lro_falso(servico, file_id, alvo, mime_type):
        assert file_id == "P1"
        assert mime_type == EXPORTABLE["application/vnd.google-apps.presentation"]
        alvo.write_bytes(b"pptx original")
        return alvo

    monkeypatch.setattr("agebackup.backup.download_document_async", lro_falso)

    stats = executar_backup(service, config, destino)

    assert stats.falhas == 0
    assert stats.baixados == 1
    assert stats.originais_pendentes == 0
    assert (destino / "proposta.pptx").read_bytes() == b"pptx original"
    assert not list(destino.glob("*.pdf"))


def test_download_direto_transitorio_nao_vira_pdf(
    service, config, tmp_path, monkeypatch
):
    """Falha temporária no files.download é repetida; não degrada para PDF."""
    _FakeDrive.arquivos = [
        _arquivo(
            "P1",
            "proposta",
            mimeType="application/vnd.google-apps.presentation",
            size=str(12 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {
        EXPORTABLE["application/vnd.google-apps.presentation"]
    }
    destino = tmp_path / "backup"
    tentativas = {"n": 0}

    def lro_transitorio(servico, file_id, alvo, mime_type):
        tentativas["n"] += 1
        raise TransientDriveError("429")

    monkeypatch.setattr("agebackup.backup.download_document_async", lro_transitorio)
    monkeypatch.setattr("agebackup.backup.time.sleep", lambda *a: None)

    stats = executar_backup(service, config, destino)

    assert stats.falhas == 1
    assert tentativas["n"] == config.retry.attempts + 1
    assert not list(destino.glob("*.pdf"))


def test_overflow_e_idempotente_na_segunda_execucao(service, config, tmp_path):
    """O PDF é rastreado no manifesto: a 2ª execução não rebaixa nem reconstrói."""
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha-grande",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(15 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {EXPORTABLE["application/vnd.google-apps.spreadsheet"]}
    destino = tmp_path / "backup"

    primeira = executar_backup(service, config, destino)
    segunda = executar_backup(service, config, destino)

    assert primeira.baixados == 1
    assert primeira.originais_pendentes == 1
    assert segunda.ignorados == 1
    assert segunda.baixados == 0
    assert segunda.originais_pendentes == 0


def test_documento_grande_demais_ate_para_pdf_e_registrado(service, config, tmp_path):
    """Se nem o PDF couber, aí sim vira pendente, com categoria própria."""
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha-gigante",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(15 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {
        EXPORTABLE["application/vnd.google-apps.spreadsheet"],
        "application/pdf",
    }
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.falhas == 1
    texto = (destino / "logs" / ".agebackup-falhas.log").read_text(encoding="utf-8")
    assert "grande_demais" in texto


def test_pdf_grande_demais_usa_o_editavel(service, config, tmp_path, monkeypatch):
    """Se nem o PDF couber, o editável reconstruído vira o próprio arquivo.

    Assim um nativo enorme não fica sem nenhuma cópia local.
    """
    _FakeDrive.arquivos = [
        _arquivo(
            "P1",
            "apresentacao-gigante",
            mimeType="application/vnd.google-apps.presentation",
            size=str(30 * 1024 * 1024),
        )
    ]
    _FakeDrive.exportar_grande = {
        EXPORTABLE["application/vnd.google-apps.presentation"],
        "application/pdf",
    }
    destino = tmp_path / "backup"

    def reconstruir_falso(mime_type, file_id, alvo):
        alvo.write_bytes(b"pptx reconstruido")
        return alvo

    monkeypatch.setattr(reconstruir_mod, "reconstruir", reconstruir_falso)

    stats = executar_backup(service, config, destino)

    assert stats.falhas == 0
    assert stats.baixados == 1
    assert not list(destino.glob("*.pdf"))
    editavel = destino / "apresentacao-gigante.reconstruido.pptx"
    assert editavel.read_bytes() == b"pptx reconstruido"


def test_documento_texto_grande_e_baixado_inteiro(service, config, tmp_path):
    """Um .md/.txt enviado (>10MB) é blob: baixa inteiro, sem export nem PDF."""
    _FakeDrive.arquivos = [
        _arquivo(
            "M1",
            "anotacoes.md",
            mimeType="text/markdown",
            size=str(20 * 1024 * 1024),
        )
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 1
    assert stats.originais_pendentes == 0
    assert (destino / "anotacoes.md").read_bytes() == CONTEUDO
    assert not list(destino.glob("*.pdf"))


def test_baixar_com_retry_repete_erro_de_rede(monkeypatch, tmp_path):
    """Uma queda de rede no download é repetida até dar certo."""
    from agebackup.backup import FileEntry, _baixar_com_retry

    entrada = FileEntry(
        file_id="F1",
        name="licao09.mp3",
        mime_type="audio/mpeg",
        size=10,
        modified_time=_quando(),
    )
    destino = tmp_path / "licao09.mp3"
    tentativas = {"n": 0}

    def uma_vez(service, entrada, destino):
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            raise TransientDriveError("Falha de rede no download")
        destino.write_bytes(CONTEUDO)
        return destino

    monkeypatch.setattr("agebackup.backup._baixar_uma_vez", uma_vez)
    monkeypatch.setattr("agebackup.backup.time.sleep", lambda *a: None)

    gravado = _baixar_com_retry(None, entrada, destino, max_retries=5)

    assert tentativas["n"] == 3
    assert gravado.read_bytes() == CONTEUDO


def test_baixar_com_retry_desiste_apos_o_limite(monkeypatch, tmp_path):
    """Passado o limite de tentativas, a falha sobe para ser registrada."""
    from agebackup.backup import FileEntry, _baixar_com_retry

    entrada = FileEntry(
        file_id="F1",
        name="licao09.mp3",
        mime_type="audio/mpeg",
        size=10,
        modified_time=_quando(),
    )
    tentativas = {"n": 0}

    def sempre_falha(service, entrada, destino):
        tentativas["n"] += 1
        raise TransientDriveError("Falha de rede no download")

    monkeypatch.setattr("agebackup.backup._baixar_uma_vez", sempre_falha)
    monkeypatch.setattr("agebackup.backup.time.sleep", lambda *a: None)

    with pytest.raises(TransientDriveError):
        _baixar_com_retry(None, entrada, tmp_path / "licao09.mp3", max_retries=2)

    assert tentativas["n"] == 3, "1 tentativa + 2 repetições"


def test_export_recebe_extensao_do_formato(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo("D1", "relatorio", mimeType="application/vnd.google-apps.document"),
        _arquivo("S1", "planilha", mimeType="application/vnd.google-apps.spreadsheet"),
        _arquivo("P1", "slides", mimeType="application/vnd.google-apps.presentation"),
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.baixados == 3
    assert (destino / "relatorio.docx").read_bytes() == CONTEUDO
    assert (destino / "planilha.xlsx").read_bytes() == CONTEUDO
    assert (destino / "slides.pptx").read_bytes() == CONTEUDO


def test_export_com_extensao_nao_duplica(service, config, tmp_path):
    """Um doc já exportado com a extensão é reconhecido como inalterado."""
    _FakeDrive.arquivos = [
        _arquivo("D1", "relatorio", mimeType="application/vnd.google-apps.document")
    ]
    destino = tmp_path / "backup"

    primeiro = executar_backup(service, config, destino)
    segundo = executar_backup(service, config, destino)

    assert primeiro.baixados == 1
    assert segundo.baixados == 0
    assert segundo.ignorados == 1


def test_documento_no_limite_e_exportado(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(9 * 1024 * 1024),
        )
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.requer_lro == 0
    assert stats.baixados == 1


def test_vids_lro_transitorio_e_repetido(service, config, tmp_path, monkeypatch):
    """Falha temporária no files.download do Vids é repetida, não vira falha."""
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]
    tentativas = {"n": 0}

    def lro_transitorio(servico, file_id, alvo, mime_type):
        tentativas["n"] += 1
        if tentativas["n"] == 1:
            raise TransientDriveError("429")
        alvo.write_bytes(b"mp4")
        return alvo

    monkeypatch.setattr("agebackup.backup.download_document_async", lro_transitorio)
    monkeypatch.setattr("agebackup.backup.time.sleep", lambda *args: None)

    stats = executar_backup(service, config, tmp_path / "backup")

    assert stats.falhas == 0
    assert stats.baixados == 1
    assert tentativas["n"] == 2


def test_lro_e_reportado_no_resumo(service, config, tmp_path, monkeypatch):
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]

    def lro_falso(servico, file_id, alvo, mime_type):
        alvo.write_bytes(b"mp4")
        return alvo

    monkeypatch.setattr("agebackup.backup.download_document_async", lro_falso)

    stats = executar_backup(service, config, tmp_path / "backup")

    assert "por operação longa" in stats.resumo()


def test_rotacao_desativada_nao_comprime(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    config.logs.enabled = False
    destino = tmp_path / "backup"
    (destino / "logs" / ".agebackup-mes").parent.mkdir(parents=True, exist_ok=True)
    (destino / "logs" / ".agebackup-mes").write_text("2026-09")
    (destino / "logs" / ".agebackup-falhas.log").write_text(
        "antigo\n", encoding="utf-8"
    )

    executar_backup(service, config, destino)

    assert not list(destino.rglob("*.gz"))
    assert (
        destino / "logs" / ".agebackup-falhas.log"
    ).exists(), "log deve ficar intacto"


def test_resumo_do_dry_run_nao_diz_baixados(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]

    stats = executar_backup(service, config, tmp_path / "backup", dry_run=True)

    assert "2 a baixar" in stats.resumo()
    assert "baixados" not in stats.resumo()


def test_resumo_real_diz_baixados(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]

    stats = executar_backup(service, config, tmp_path / "backup")

    assert "1 baixados" in stats.resumo()


def test_logs_ficam_na_subpasta_logs(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / "logs" / ".agebackup-falhas.log").exists()
    assert not (destino / ".agebackup-falhas.log").exists()


def test_pasta_de_logs_e_configuravel(service, config, tmp_path):
    config.logs.directory = "historico"
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / "historico" / ".agebackup-falhas.log").exists()
    assert not (destino / "logs").exists()


def test_pasta_de_logs_vazia_grava_na_raiz(service, config, tmp_path):
    config.logs.directory = ""
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / ".agebackup-falhas.log").exists()
    assert not (destino / "logs").exists()


def test_log_de_remocoes_fica_na_subpasta(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    executar_backup(service, config, destino)

    assert (destino / "logs" / ".agebackup-removidos.log").exists()
    assert not (destino / ".agebackup-removidos.log").exists()


def test_manifesto_continua_na_raiz_do_backup(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / ".agebackup-manifest.json").exists()
    assert not (destino / "logs" / ".agebackup-manifest.json").exists()


def test_rotacao_comprime_dentro_da_subpasta(service, config, tmp_path):
    config.logs.keep_months = 0
    pasta_logs = tmp_path / "backup" / "logs"
    pasta_logs.mkdir(parents=True)
    (pasta_logs / ".agebackup-falhas.log").write_text("antigo\n", encoding="utf-8")
    (pasta_logs / ".agebackup-mes").write_text("2020-01", encoding="utf-8")
    _FakeDrive.arquivos = []

    executar_backup(service, config, tmp_path / "backup")

    assert list(pasta_logs.glob("*.gz")), "o mês anterior deve ser comprimido ali"


def test_reconstruir_pendentes_usa_log_e_manifesto(
    service, config, tmp_path, monkeypatch
):
    """Reconstrói um PDF já baixado, usando o log como lista de trabalho."""
    from agebackup import manifest as manifest_mod
    from agebackup.backup import reconstruir_pendentes
    from agebackup.falhas import Falha

    destino = tmp_path / "backup"
    destino.mkdir()
    _FakeDrive.arquivos = [
        _arquivo(
            "P1",
            "apresentacao",
            mimeType="application/vnd.google-apps.presentation",
        )
    ]
    (destino / "apresentacao.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    manifest_mod.registrar(
        registros, "apresentacao.pdf", "P1", "apresentacao", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)
    falhas_mod.registrar(
        config.logs.pasta(destino),
        [Falha(nome="apresentacao", categoria=falhas_mod.CAT_GRANDE, drive_id="P1")],
    )

    def reconstruir_falso(mime_type, file_id, alvo):
        alvo.write_bytes(b"pptx")
        return alvo

    monkeypatch.setattr(reconstruir_mod, "reconstruir", reconstruir_falso)

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    assert (reconstruidos, falhas) == (1, 0)
    assert (destino / "apresentacao.reconstruido.pptx").read_bytes() == b"pptx"


def test_reconstruir_pendentes_baixa_o_original_direto(
    service, config, tmp_path, monkeypatch
):
    """Com o files.download disponível, o pendente vira o original (.pptx) limpo.

    Sem o sufixo `.reconstruido`: é o export fiel, não uma reconstrução.
    """
    from agebackup import manifest as manifest_mod
    from agebackup.backup import reconstruir_pendentes
    from agebackup.falhas import Falha

    destino = tmp_path / "backup"
    destino.mkdir()
    _FakeDrive.arquivos = [
        _arquivo("P1", "proposta", mimeType="application/vnd.google-apps.presentation")
    ]
    (destino / "proposta.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    manifest_mod.registrar(
        registros, "proposta.pdf", "P1", "proposta", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)
    falhas_mod.registrar(
        config.logs.pasta(destino),
        [Falha(nome="proposta", categoria=falhas_mod.CAT_GRANDE, drive_id="P1")],
    )

    def lro_falso(servico, file_id, alvo, mime_type):
        alvo.write_bytes(b"pptx original")
        return alvo

    monkeypatch.setattr("agebackup.backup.download_document_async", lro_falso)

    chamou_reconstruir = {"sim": False}
    monkeypatch.setattr(
        reconstruir_mod,
        "reconstruir",
        lambda *a, **k: chamou_reconstruir.__setitem__("sim", True),
    )

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    assert (reconstruidos, falhas) == (1, 0)
    assert (destino / "proposta.pptx").read_bytes() == b"pptx original"
    # Não precisou da API nativa quando o original veio direto.
    assert chamou_reconstruir["sim"] is False


def test_reconstruir_pendentes_salva_md_quando_api_nativa_falha(
    service, config, tmp_path
):
    """Sem a Docs API, um Doc pendente é reconstruído como .md (export do Drive)."""
    from agebackup import manifest as manifest_mod
    from agebackup.backup import reconstruir_pendentes
    from agebackup.falhas import Falha

    destino = tmp_path / "backup"
    destino.mkdir()
    _FakeDrive.arquivos = [
        _arquivo("D1", "documento", mimeType="application/vnd.google-apps.document")
    ]
    (destino / "documento.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    manifest_mod.registrar(
        registros, "documento.pdf", "D1", "documento", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)
    falhas_mod.registrar(
        config.logs.pasta(destino),
        [Falha(nome="documento", categoria=falhas_mod.CAT_GRANDE, drive_id="D1")],
    )
    # O autouse `sem_reconstrucao` faz a API nativa falhar.

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    assert (reconstruidos, falhas) == (1, 0)
    assert (destino / "documento.reconstruido.md").read_bytes() == CONTEUDO


def test_reconstruir_pendentes_ignora_tipo_sem_reconstrutor(
    service, config, tmp_path, monkeypatch
):
    from agebackup import manifest as manifest_mod
    from agebackup.backup import reconstruir_pendentes
    from agebackup.falhas import Falha

    destino = tmp_path / "backup"
    destino.mkdir()
    _FakeDrive.arquivos = [
        _arquivo("D1", "desenho", mimeType="application/vnd.google-apps.drawing")
    ]
    (destino / "desenho.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    manifest_mod.registrar(
        registros, "desenho.pdf", "D1", "desenho", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)
    falhas_mod.registrar(
        config.logs.pasta(destino),
        [Falha(nome="desenho", categoria=falhas_mod.CAT_GRANDE, drive_id="D1")],
    )

    chamou = {"sim": False}
    monkeypatch.setattr(
        reconstruir_mod,
        "reconstruir",
        lambda *a, **k: chamou.__setitem__("sim", True),
    )

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    assert (reconstruidos, falhas) == (0, 0)
    assert chamou["sim"] is False


def test_reconstruir_pendentes_sem_log_nao_faz_nada(service, config, tmp_path):
    from agebackup.backup import reconstruir_pendentes

    reconstruidos, falhas = reconstruir_pendentes(service, config, tmp_path / "backup")

    assert (reconstruidos, falhas) == (0, 0)


def test_reconstruir_pendentes_pega_pdf_sem_log(service, config, tmp_path, monkeypatch):
    """Um PDF de nativo baixado antes desta função (sem log) ainda é reconstruído."""
    from agebackup import manifest as manifest_mod
    from agebackup.backup import reconstruir_pendentes

    destino = tmp_path / "backup"
    destino.mkdir()
    _FakeDrive.arquivos = [
        _arquivo("P1", "proposta", mimeType="application/vnd.google-apps.presentation")
    ]
    (destino / "proposta.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    # O nome no Drive de um nativo não traz extensão.
    manifest_mod.registrar(
        registros, "proposta.pdf", "P1", "proposta", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)
    # Sem nenhum registro no log de falhas.

    def reconstruir_falso(mime_type, file_id, alvo):
        alvo.write_bytes(b"pptx")
        return alvo

    monkeypatch.setattr(reconstruir_mod, "reconstruir", reconstruir_falso)

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    assert (reconstruidos, falhas) == (1, 0)
    assert (destino / "proposta.reconstruido.pptx").read_bytes() == b"pptx"


def test_reconstruir_pendentes_ignora_pdf_enviado(
    service, config, tmp_path, monkeypatch
):
    """PDF enviado (nome no Drive termina em .pdf) não é candidato a reconstrução."""
    from agebackup import manifest as manifest_mod
    from agebackup.backup import reconstruir_pendentes

    destino = tmp_path / "backup"
    destino.mkdir()
    (destino / "manual.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    manifest_mod.registrar(
        registros, "manual.pdf", "M1", "manual.pdf", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)

    def nao_pode(*args, **kwargs):  # pragma: no cover - só falha se for chamado
        raise AssertionError("não deveria consultar o tipo de um PDF enviado")

    monkeypatch.setattr("agebackup.backup._mime_do_drive", nao_pode)

    reconstruidos, falhas = reconstruir_pendentes(service, config, destino)

    assert (reconstruidos, falhas) == (0, 0)


def test_original_recuperado_reconhece_export_fiel(tmp_path):
    from agebackup.backup import original_recuperado

    pdf = tmp_path / "proposta.pdf"
    pdf.write_bytes(CONTEUDO)

    assert original_recuperado(pdf) is False
    (tmp_path / "proposta.pptx").write_bytes(b"pptx")
    assert original_recuperado(pdf) is True


def test_original_recuperado_reconhece_reconstrucao(tmp_path):
    from agebackup.backup import original_recuperado

    pdf = tmp_path / "documento.pdf"
    pdf.write_bytes(CONTEUDO)

    assert original_recuperado(pdf) is False
    (tmp_path / "documento.reconstruido.md").write_bytes(b"# doc")
    assert original_recuperado(pdf) is True


def test_original_recuperado_nao_confunde_com_vizinho(tmp_path):
    from agebackup.backup import original_recuperado

    pdf = tmp_path / "proposta.pdf"
    pdf.write_bytes(CONTEUDO)
    (tmp_path / "outro.pdf").write_bytes(CONTEUDO)
    (tmp_path / "outro.pptx").write_bytes(b"pptx")

    assert original_recuperado(pdf) is False


def test_pendentes_de_original_esconde_recuperado(service, config, tmp_path):
    from agebackup import manifest as manifest_mod
    from agebackup.backup import pendentes_de_original
    from agebackup.falhas import Falha

    destino = tmp_path / "backup"
    destino.mkdir()
    (destino / "proposta.pdf").write_bytes(CONTEUDO)
    registros: dict = {}
    manifest_mod.registrar(
        registros, "proposta.pdf", "P1", "proposta", len(CONTEUDO), _quando()
    )
    manifest_mod.salvar(destino, registros)
    falhas_mod.registrar(
        config.logs.pasta(destino),
        [
            Falha(nome="proposta", categoria=falhas_mod.CAT_GRANDE, drive_id="P1"),
            Falha(nome="outra", categoria=falhas_mod.CAT_GRANDE, drive_id="P2"),
        ],
    )

    # P1 ainda está só em PDF; P2 nem no manifesto está.
    assert pendentes_de_original(destino, config.logs.pasta(destino)) == {"P1", "P2"}

    (destino / "proposta.pptx").write_bytes(b"pptx")

    assert pendentes_de_original(destino, config.logs.pasta(destino)) == {"P2"}
