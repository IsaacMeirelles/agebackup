"""Testes de download contra um servidor HTTP local, sem chamar a API real."""

import http.client
import http.server
import json
import threading
from collections.abc import Iterator
from typing import ClassVar, Self

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from agebackup import drive
from agebackup.drive import (
    DownloadRestrictedError,
    ExportTooLargeError,
    FileNotFoundInDriveError,
    TransientDriveError,
    _unique_path,
    download_blob,
    export_document,
    resolve_destination,
)

PAYLOAD = b"conteudo do arquivo de teste" * 5000

recorded: list[str] = []


class _FakeDrive(http.server.BaseHTTPRequestHandler):
    """Serve respostas configuradas por teste, registrando as requisições."""

    payload = PAYLOAD
    metadata: ClassVar[dict[str, dict]] = {}
    status = 200
    # motivo do erro devolvido quando status != 200; vazio usa o padrão por código
    motivo: ClassVar[str] = ""

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # nome exigido pelo BaseHTTPRequestHandler
        recorded.append(self.path)

        if self.status != 200:
            reason = (
                self.motivo
                or {
                    403: "insufficientFilePermissions",
                    404: "notFound",
                    429: "rateLimitExceeded",
                }[self.status]
            )
            self._send(
                self.status,
                json.dumps(
                    {
                        "error": {
                            "code": self.status,
                            "message": "erro",
                            "errors": [{"reason": reason, "message": "erro"}],
                        }
                    }
                ).encode(),
                "application/json",
            )
            return

        # Conteúdo devolvido pela URL de uma operação de longa duração.
        if self.path.startswith("/conteudo"):
            self._send(200, _FakeDrive.payload, "application/octet-stream")
            return

        if "alt=media" not in self.path:
            file_id = self.path.rsplit("/", 1)[-1].split("?")[0]
            meta = _FakeDrive.metadata.get(
                file_id, {"name": "arquivo.txt", "parents": []}
            )
            self._send(200, json.dumps(meta).encode(), "application/json")
            return

        self._send(200, _FakeDrive.payload, "application/octet-stream")

    def do_POST(self) -> None:  # nome exigido pelo BaseHTTPRequestHandler
        recorded.append("POST " + self.path)
        # Emula `files.download`: devolve uma operação já concluída, apontando
        # para a URL onde o conteúdo está (o próprio servidor de teste).
        porta = self.server.server_address[1]
        corpo = {
            "done": True,
            "response": {"downloadUri": f"http://127.0.0.1:{porta}/conteudo"},
        }
        self._send(200, json.dumps(corpo).encode(), "application/json")


@pytest.fixture
def server() -> Iterator[http.server.HTTPServer]:
    recorded.clear()
    _FakeDrive.payload = PAYLOAD
    _FakeDrive.metadata = {}
    _FakeDrive.status = 200
    _FakeDrive.motivo = ""

    srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeDrive)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def service(server: http.server.HTTPServer):
    svc = build(
        "drive", "v3", credentials=Credentials(token="fake"), cache_discovery=False
    )
    svc._baseUrl = f"http://127.0.0.1:{server.server_address[1]}/"
    return svc


def test_download_blob_grava_o_conteudo(service, tmp_path):
    destino = tmp_path / "saida.bin"

    resultado = download_blob(service, "FILE_ID", destino, check_permissions=False)

    assert resultado == destino
    assert destino.read_bytes() == PAYLOAD


def test_download_nao_deixa_arquivo_temporario(service, tmp_path):
    destino = tmp_path / "saida.bin"

    download_blob(service, "FILE_ID", destino, check_permissions=False)

    assert list(tmp_path.iterdir()) == [destino]


def test_download_remove_parcial_quando_falha(service, tmp_path):
    _FakeDrive.status = 429
    destino = tmp_path / "saida.bin"

    with pytest.raises(TransientDriveError):
        download_blob(service, "FILE_ID", destino, check_permissions=False)

    assert not destino.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_403_vira_erro_de_permissao(service, tmp_path):
    _FakeDrive.status = 403

    with pytest.raises(DownloadRestrictedError):
        download_blob(
            service, "FILE_ID", tmp_path / "saida.bin", check_permissions=False
        )


def test_download_404_vira_nao_encontrado(service, tmp_path):
    _FakeDrive.status = 404

    with pytest.raises(FileNotFoundInDriveError):
        download_blob(
            service, "FILE_ID", tmp_path / "saida.bin", check_permissions=False
        )


def test_sobrescreve_arquivo_existente(service, tmp_path):
    destino = tmp_path / "saida.bin"
    destino.write_bytes(b"antigo")

    download_blob(service, "FILE_ID", destino, check_permissions=False)

    assert destino.read_bytes() == PAYLOAD


def test_export_usa_o_mimetype(service, tmp_path):
    export_document(service, "FILE_ID", tmp_path / "doc.pdf", "application/pdf")

    assert any(
        "export" in path and "mimeType=application%2Fpdf" in path for path in recorded
    )


def test_export_grande_demais_vira_erro_proprio(service, tmp_path):
    """O 403 de export grande demais não é confundido com falta de permissão."""
    _FakeDrive.status = 403
    _FakeDrive.motivo = "exportSizeLimitExceeded"

    with pytest.raises(ExportTooLargeError):
        export_document(service, "FILE_ID", tmp_path / "doc.pptx", "application/pdf")


def test_export_403_de_permissao_continua_restrito(service, tmp_path):
    _FakeDrive.status = 403

    with pytest.raises(DownloadRestrictedError):
        export_document(service, "FILE_ID", tmp_path / "doc.pdf", "application/pdf")


def test_export_usa_endpoint_diferente_do_download(service, tmp_path):
    download_blob(service, "FILE_ID", tmp_path / "a.bin", check_permissions=False)
    export_document(service, "FILE_ID", tmp_path / "b.pdf")

    assert any(
        path.endswith("/export?mimeType=application%2Fpdf&alt=media")
        for path in recorded
    )


def test_download_document_async_grava_o_original(service, tmp_path):
    """O files.download (LRO) publica a URL e o conteúdo é gravado dali."""
    destino = tmp_path / "saida.pptx"

    resultado = drive.download_document_async(
        service, "FILE_ID", destino, "application/pdf"
    )

    assert resultado == destino
    assert destino.read_bytes() == PAYLOAD
    # Passou pelo POST de /download (a operação longa), não pelo export.
    assert any(linha.startswith("POST ") and "/download" in linha for linha in recorded)
    assert any(linha.startswith("/conteudo") for linha in recorded)


def test_download_document_async_sem_url_falha(monkeypatch, tmp_path):
    """Operação concluída sem downloadUri vira erro de domínio, não silêncio."""

    class _Req:
        uri = "http://exemplo/download"
        http = object()

        def execute(self):
            return {"done": True, "response": {}}

    class _Files:
        def download(self, **kwargs):
            return _Req()

    class _Service:
        def files(self):
            return _Files()

    with pytest.raises(drive.AsyncDownloadError, match="não devolveu URL"):
        drive.download_document_async(
            _Service(), "FILE_ID", tmp_path / "x.pptx", "application/pdf"
        )


def test_aguardar_operacao_faz_polling(monkeypatch):
    """Uma operação pendente é consultada até concluir."""
    estados = [{"done": True, "response": {"downloadUri": "http://x/y"}}]
    chamadas: list[str] = []

    def consultar(http, nome):
        chamadas.append(nome)
        return estados.pop(0)

    monkeypatch.setattr(drive, "_consultar_operacao", consultar)
    monkeypatch.setattr(drive.time, "sleep", lambda *a: None)

    resultado = drive._aguardar_operacao(
        object(), {"done": False, "name": "op1"}, 5, 0.0
    )

    assert resultado["done"] is True
    assert chamadas == ["op1"]


def test_aguardar_operacao_propaga_erro(monkeypatch):
    operacao = {"done": True, "error": {"message": "falhou feio"}}

    with pytest.raises(drive.AsyncDownloadError, match="falhou feio"):
        drive._aguardar_operacao(object(), operacao, 5, 0.0)


def test_consulta_can_download_antes_de_baixar(service, tmp_path):
    _FakeDrive.metadata = {
        "FILE_ID": {"name": "a.txt", "capabilities": {"canDownload": True}}
    }

    download_blob(service, "FILE_ID", tmp_path / "a.txt")

    assert any("capabilities" in path for path in recorded)


def test_bloqueio_de_download_e_detectado(service, tmp_path):
    _FakeDrive.metadata = {
        "FILE_ID": {"name": "a.txt", "capabilities": {"canDownload": False}}
    }

    with pytest.raises(DownloadRestrictedError):
        download_blob(service, "FILE_ID", tmp_path / "a.txt")

    assert not (tmp_path / "a.txt").exists()


def test_unique_path_nao_sobrescreve(tmp_path):
    (tmp_path / "a.txt").write_text("x")

    caminho = _unique_path(tmp_path / "a.txt")

    assert caminho.name == "a (1).txt"


def test_unique_path_mantem_ponto_ausente(tmp_path):
    caminho = _unique_path(tmp_path / "Makefile")

    assert caminho.name == "Makefile"


def test_unique_path_incrementa_sufixo(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "a (1).txt").write_text("x")

    assert _unique_path(tmp_path / "a.txt").name == "a (2).txt"


def test_resolve_destination_preserva_hierarquia(service, tmp_path):
    _FakeDrive.metadata = {
        "FILE_ID": {"name": "relatorio.pdf", "parents": ["PASTA_ID"]},
        "PASTA_ID": {"name": "2026", "parents": ["root"]},
    }

    caminho = resolve_destination(service, "FILE_ID", tmp_path)

    assert caminho == tmp_path / "2026" / "relatorio.pdf"


def test_resolve_destination_para_na_raiz(service, tmp_path):
    _FakeDrive.metadata = {"FILE_ID": {"name": "notas.txt", "parents": ["root"]}}

    assert resolve_destination(service, "FILE_ID", tmp_path) == tmp_path / "notas.txt"


def test_get_service_traduz_credenciais_ausentes(monkeypatch):
    import google.auth.exceptions

    from agebackup import config as config_mod

    def falha(*args: object, **kwargs: object) -> None:
        raise google.auth.exceptions.DefaultCredentialsError("nenhuma credencial")

    monkeypatch.setattr(config_mod, "build_credentials", falha)

    with pytest.raises(drive.DriveError, match="Credenciais"):
        drive.get_service()


class _DownloaderQuebrado:
    """Simula um downloader que estoura o erro informado no meio da transferência."""

    def __init__(self, erro: Exception) -> None:
        self.erro = erro

    def __call__(self, *args: object, **kwargs: object) -> Self:
        return self

    def next_chunk(self):
        raise self.erro


@pytest.mark.parametrize(
    "erro",
    [
        ConnectionResetError(104, "Connection reset by peer"),
        BrokenPipeError(32, "Broken pipe"),
        TimeoutError("timed out"),
        http.client.IncompleteRead(b"parcial"),
    ],
)
def test_download_erro_de_rede_vira_temporario(erro, tmp_path, monkeypatch):
    """Quedas de rede no meio do download são repetíveis, não erro local."""
    monkeypatch.setattr(drive, "MediaIoBaseDownload", _DownloaderQuebrado(erro))
    destino = tmp_path / "saida.bin"

    with pytest.raises(TransientDriveError):
        drive._download(object(), destino)

    assert not destino.exists()
    assert list(tmp_path.iterdir()) == [], "não deixa o .tmp para trás"


def test_download_erro_de_disco_nao_vira_temporario(tmp_path, monkeypatch):
    """Disco cheio não melhora repetindo: continua sendo OSError comum."""
    erro = OSError(28, "No space left on device")
    monkeypatch.setattr(drive, "MediaIoBaseDownload", _DownloaderQuebrado(erro))

    with pytest.raises(OSError) as excinfo:
        drive._download(object(), tmp_path / "saida.bin")

    assert not isinstance(excinfo.value, TransientDriveError)
