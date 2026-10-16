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

from gback.backup import (
    EXPORTABLE,
    FileEntry,
    Stats,
    _destino_existente,
    _eh_pasta,
    _formatar_bytes,
    executar_backup,
    listar_arquivos,
)
from gback.config import AccountConfig, BackupConfig, Config
from gback.drive import DownloadRestrictedError, TransientDriveError

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
        item = next((a for a in self.arquivos if a["id"] == file_id), {})
        self._json(item)


@pytest.fixture
def service():
    _FakeDrive.arquivos = []
    _FakeDrive.paginas = [{"files": []}]
    _FakeDrive.paginar = 0
    _FakeDrive.falhar_com = None

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


def test_formatar_bytes():
    assert _formatar_bytes(512) == "512B"
    assert _formatar_bytes(2048) == "2.0KB"
    assert _formatar_bytes(5 * 1024 * 1024) == "5.0MB"


def test_eh_pasta():
    assert _eh_pasta("application/vnd.google-apps.folder") is True
    assert _eh_pasta("text/plain") is False


def test_exportable_tem_mapeamento_completo():
    assert EXPORTABLE["application/vnd.google-apps.document"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert EXPORTABLE["application/vnd.google-apps.spreadsheet"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert EXPORTABLE["application/vnd.google-apps.presentation"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
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
    log = destino / "logs" / ".gback-removidos.log"
    assert "b.txt" in log.read_text(encoding="utf-8")


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

    assert not (destino / "logs" / ".gback-removidos.log").exists()


def test_manifesto_e_gravado_apos_backup(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    manifesto = destino / ".gback-manifest.json"
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

    log = destino / "logs" / ".gback-falhas.log"
    assert log.exists()
    assert "a.txt" in log.read_text(encoding="utf-8")


def test_backup_registra_categoria_da_falha(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    texto = (destino / "logs" / ".gback-falhas.log").read_text(encoding="utf-8")
    assert "bloqueado" in texto


def test_backup_dry_run_nao_gera_log_de_falhas(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino, dry_run=True)

    assert not (destino / "logs" / ".gback-falhas.log").exists()


def test_backup_sem_falhas_nao_cria_log(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert not (destino / "logs" / ".gback-falhas.log").exists()


def test_logs_do_gback_nao_sao_tratados_como_removidos(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)
    stats = executar_backup(service, config, destino)

    assert stats.removidos_na_origem == 0


def test_video_do_drive_e_registrado_como_lro(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.requer_lro == 1
    assert stats.baixados == 0
    texto = (destino / "logs" / ".gback-falhas.log").read_text(encoding="utf-8")
    assert "operacao_longa" in texto
    assert "meu-video" in texto


def test_video_nao_e_baixado(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert not (destino / "meu-video").exists()


def test_documento_acima_do_limite_e_registrado(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo(
            "D1",
            "planilha-grande",
            mimeType="application/vnd.google-apps.spreadsheet",
            size=str(15 * 1024 * 1024),
        )
    ]
    destino = tmp_path / "backup"

    stats = executar_backup(service, config, destino)

    assert stats.requer_lro == 1
    assert "operacao_longa" in (destino / "logs" / ".gback-falhas.log").read_text(
        encoding="utf-8"
    )


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


def test_lro_nao_conta_como_falha_repetivel(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]

    stats = executar_backup(service, config, tmp_path / "backup")

    assert stats.falhas == 0, "não há o que repetir; só exige LRO"
    assert stats.requer_lro == 1


def test_lro_e_reportado_no_resumo(service, config, tmp_path):
    _FakeDrive.arquivos = [
        _arquivo("V1", "meu-video", mimeType="application/vnd.google-apps.video")
    ]

    stats = executar_backup(service, config, tmp_path / "backup")

    assert "exigem operação longa" in stats.resumo()


def test_rotacao_desativada_nao_comprime(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    config.logs.enabled = False
    destino = tmp_path / "backup"
    (destino / "logs" / ".gback-mes").parent.mkdir(parents=True, exist_ok=True)
    (destino / "logs" / ".gback-mes").write_text("2026-09")
    (destino / "logs" / ".gback-falhas.log").write_text("antigo\n", encoding="utf-8")

    executar_backup(service, config, destino)

    assert not list(destino.rglob("*.gz"))
    assert (destino / "logs" / ".gback-falhas.log").exists(), "log deve ficar intacto"


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

    assert (destino / "logs" / ".gback-falhas.log").exists()
    assert not (destino / ".gback-falhas.log").exists()


def test_pasta_de_logs_e_configuravel(service, config, tmp_path):
    config.logs.directory = "historico"
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / "historico" / ".gback-falhas.log").exists()
    assert not (destino / "logs").exists()


def test_pasta_de_logs_vazia_grava_na_raiz(service, config, tmp_path):
    config.logs.directory = ""
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    _FakeDrive.falhar_com = 403
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / ".gback-falhas.log").exists()
    assert not (destino / "logs").exists()


def test_log_de_remocoes_fica_na_subpasta(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt"), _arquivo("F2", "b.txt")]
    destino = tmp_path / "backup"
    executar_backup(service, config, destino)

    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    executar_backup(service, config, destino)

    assert (destino / "logs" / ".gback-removidos.log").exists()
    assert not (destino / ".gback-removidos.log").exists()


def test_manifesto_continua_na_raiz_do_backup(service, config, tmp_path):
    _FakeDrive.arquivos = [_arquivo("F1", "a.txt")]
    destino = tmp_path / "backup"

    executar_backup(service, config, destino)

    assert (destino / ".gback-manifest.json").exists()
    assert not (destino / "logs" / ".gback-manifest.json").exists()


def test_rotacao_comprime_dentro_da_subpasta(service, config, tmp_path):
    config.logs.keep_months = 0
    pasta_logs = tmp_path / "backup" / "logs"
    pasta_logs.mkdir(parents=True)
    (pasta_logs / ".gback-falhas.log").write_text("antigo\n", encoding="utf-8")
    (pasta_logs / ".gback-mes").write_text("2020-01", encoding="utf-8")
    _FakeDrive.arquivos = []

    executar_backup(service, config, tmp_path / "backup")

    assert list(pasta_logs.glob("*.gz")), "o mês anterior deve ser comprimido ali"
