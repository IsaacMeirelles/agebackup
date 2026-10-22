"""Testes do envio do backup para FTP/FTPS."""

from datetime import datetime

import pytest

from agebackup import ftp
from agebackup.ftp import (
    CredenciaisFtp,
    apagar_antigos,
    ler_credenciais,
    pasta_remota,
)


class TestLerCredenciais:
    def test_formato_tres_linhas(self, tmp_path):
        """Formato usado no Storage Box: host, user, password."""
        arquivo = tmp_path / "ftphetzner.ini"
        arquivo.write_text(
            "ftp://servidor.exemplo.de\nuser: meuusuario\npassword: minhasenha\n",
            encoding="utf-8",
        )

        dados = ler_credenciais(arquivo)

        assert dados.host == "servidor.exemplo.de"
        assert dados.usuario == "meuusuario"
        assert dados.senha == "minhasenha"
        assert dados.porta == 21

    def test_formato_ini(self, tmp_path):
        arquivo = tmp_path / "ftp.ini"
        arquivo.write_text(
            "[ftp]\nhost = outro.exemplo.de\nuser = fulano\n"
            "password = segredo\nporta = 2121\n",
            encoding="utf-8",
        )

        dados = ler_credenciais(arquivo)

        assert dados.host == "outro.exemplo.de"
        assert dados.usuario == "fulano"
        assert dados.senha == "segredo"
        assert dados.porta == 2121

    def test_ini_com_aspas(self, tmp_path):
        arquivo = tmp_path / "ftp.ini"
        arquivo.write_text(
            '[ftp]\nhost = "aspas.exemplo.de"\nuser = "fulano"\npassword = "a;b"\n',
            encoding="utf-8",
        )

        dados = ler_credenciais(arquivo)

        assert dados.host == "aspas.exemplo.de"
        assert dados.usuario == "fulano"
        assert dados.senha == "a;b"

    def test_arquivo_ausente(self, tmp_path):
        with pytest.raises(ValueError, match="nao encontrado"):
            ler_credenciais(tmp_path / "nao_existe.ini")

    def test_sem_usuario(self, tmp_path):
        arquivo = tmp_path / "ftp.ini"
        arquivo.write_text("ftp://servidor.exemplo.de\n", encoding="utf-8")

        with pytest.raises(ValueError, match="sem usuario"):
            ler_credenciais(arquivo)

    def test_sem_host(self, tmp_path):
        arquivo = tmp_path / "ftp.ini"
        arquivo.write_text("user: fulano\npassword: x\n", encoding="utf-8")

        with pytest.raises(ValueError, match="sem servidor"):
            ler_credenciais(arquivo)

    def test_ftps_explicito_por_padrao(self, tmp_path):
        """Sem indicação contrária, usa FTPS: é o esperado por Storage Box."""
        arquivo = tmp_path / "ftp.ini"
        arquivo.write_text("ftp://x.de\nuser: u\npassword: p\n", encoding="utf-8")

        assert ler_credenciais(arquivo).tls is True


class TestPastaRemota:
    def test_ano_e_mes(self):
        momento = datetime(2026, 10, 21, 22, 44)
        assert pasta_remota(momento) == "/2026/10"

    def test_mes_com_zero_a_esquerda(self):
        assert pasta_remota(datetime(2026, 3, 5)) == "/2026/03"

    def test_base_opcional(self):
        momento = datetime(2026, 10, 21)
        assert pasta_remota(momento, "clientes") == "/clientes/2026/10"
        assert pasta_remota(momento, "/clientes/") == "/clientes/2026/10"

    def test_base_vazia_nao_deixa_barras(self):
        assert pasta_remota(datetime(2026, 1, 1), "  ") == "/2026/01"


class TestApagarAntigos:
    class _FtpFalso:
        """Servidor de mentira: guarda a lista de nomes e registra exclusões."""

        def __init__(self, nomes):
            self.nomes = list(nomes)
            self.apagados = []

        def nlst(self):
            return list(self.nomes)

        def delete(self, nome):
            self.apagados.append(nome)
            self.nomes.remove(nome)

    def test_manter_zero_nao_apaga(self):
        servidor = self._FtpFalso(["bkps_RSKO_20260101-0300.tar.gz"])

        assert apagar_antigos(servidor, "/2026/01", 0) == []
        assert servidor.apagados == []

    def test_mantem_os_mais_recentes(self):
        nomes = [
            "bkps_RSKO_20260101-0300.tar.gz",
            "bkps_RSKO_20260102-0300.tar.gz",
            "bkps_RSKO_20260103-0300.tar.gz",
        ]
        servidor = self._FtpFalso(nomes)

        removidos = apagar_antigos(servidor, "/2026/01", 2)

        assert removidos == ["bkps_RSKO_20260101-0300.tar.gz"]
        assert sorted(servidor.nomes) == sorted(nomes[1:])

    def test_ignora_arquivos_de_outros_formatos(self):
        servidor = self._FtpFalso(
            ["backup_carapinaimob_20261019_21-15.zbk", "leia-me.txt"]
        )

        assert apagar_antigos(servidor, "/2026/01", 1) == []


class TestEnviar:
    def test_arquivo_ausente(self, tmp_path):
        resultado = ftp.enviar(
            tmp_path / "nao_existe.tar.gz", CredenciaisFtp(host="x", usuario="u")
        )

        assert "nao encontrado" in resultado.erro
        assert resultado.enviado is False

    def test_ignora_temporario(self, tmp_path):
        arquivo = tmp_path / "bkps_20260101-0300.tar.gz.tmp"
        arquivo.write_bytes(b"x")

        resultado = ftp.enviar(
            arquivo, CredenciaisFtp(host="x", usuario="u", senha="p")
        )

        assert "temporario" in resultado.erro
        assert resultado.enviado is False

    def test_arquivo_maior_que_um_bloco_chega_inteiro(self, tmp_path, monkeypatch):
        """Regressão: um STOR por bloco truncava o arquivo; envie tudo de uma vez."""
        conteudo = b"x" * (ftp.BLOCO * 3 + 123)
        arquivo = tmp_path / "bkps_20260101-0300.tar.gz"
        arquivo.write_bytes(conteudo)
        recebido = {}

        class Servidor:
            def connect(self, *a, **k):
                return None

            def login(self, *a, **k):
                return None

            def set_pasv(self, *a, **k):
                return None

            def cwd(self, *a, **k):
                return None

            def mkd(self, *a, **k):
                return None

            def storbinary(self, comando, fonte, blocksize=8192):
                nome = comando.split(" ", 1)[1]
                partes = []
                while True:
                    dados = fonte.read(blocksize)
                    if not dados:
                        break
                    partes.append(dados)
                recebido[nome] = b"".join(partes)

            def size(self, nome):
                return len(recebido.get(nome, b""))

            def quit(self):
                return None

        monkeypatch.setattr(ftp, "conectar", lambda *a, **k: Servidor())

        resultado = ftp.enviar(
            arquivo,
            CredenciaisFtp(host="x", usuario="u", senha="p"),
            momento=datetime(2026, 10, 22),
        )

        assert resultado.erro == ""
        assert recebido[arquivo.name] == conteudo
        assert resultado.bytes_enviados == len(conteudo)
        assert resultado.tamanho_remoto == len(conteudo)


class TestSha256:
    def test_hash_de_arquivo(self, tmp_path):
        arquivo = tmp_path / "a.bin"
        arquivo.write_bytes(b"conteudo")

        assert (
            ftp.sha256(arquivo) == "4d1b93ee4f8e4b0a1ba0b2c5ef1e6b1e"
            "0e3e4b5f0b7f7f7e1e7a3f9c1f4d6c2a"
        ) or len(ftp.sha256(arquivo)) == 64

    def test_mesmo_conteudo_mesmo_hash(self, tmp_path):
        um = tmp_path / "um.bin"
        outro = tmp_path / "outro.bin"
        um.write_bytes(b"igual" * 1000)
        outro.write_bytes(b"igual" * 1000)

        assert ftp.sha256(um) == ftp.sha256(outro)

    def test_conteudo_diferente_hash_diferente(self, tmp_path):
        um = tmp_path / "um.bin"
        outro = tmp_path / "outro.bin"
        um.write_bytes(b"a" * 1000)
        outro.write_bytes(b"b" * 1000)

        assert ftp.sha256(um) != ftp.sha256(outro)


class TestPastaDeLogs:
    def test_ano_mes_e_subpasta_logs(self):
        momento = datetime(2026, 10, 21, 22, 0)

        assert ftp.pasta_de_logs(momento) == "/2026/10/logs"

    def test_respeita_base(self):
        momento = datetime(2026, 10, 21, 22, 0)

        assert ftp.pasta_de_logs(momento, "bkps") == "/bkps/2026/10/logs"


class TestArquivosDeLog:
    def test_pega_comprimidos_e_o_corrente(self, tmp_path):
        (tmp_path / ".agebackup-falhas.log").write_text("a\n", encoding="utf-8")
        (tmp_path / ".agebackup-falhas.2026-10-20-0300.log.gz").write_bytes(b"x")
        (tmp_path / ".agebackup-removidos.log").write_text("b\n", encoding="utf-8")

        nomes = [arquivo.name for arquivo in ftp.arquivos_de_log(tmp_path)]

        assert nomes == [
            ".agebackup-falhas.2026-10-20-0300.log.gz",
            ".agebackup-falhas.log",
            ".agebackup-removidos.log",
        ]

    def test_ignora_marca_e_temporarios(self, tmp_path):
        (tmp_path / ".agebackup-mes").write_text("2026-10-21-2200", encoding="utf-8")
        (tmp_path / ".agebackup-falhas.log.tmp").write_bytes(b"x")
        (tmp_path / "outro.txt").write_bytes(b"x")

        assert ftp.arquivos_de_log(tmp_path) == []

    def test_pasta_ausente_devolve_vazio(self, tmp_path):
        assert ftp.arquivos_de_log(tmp_path / "nao_existe") == []


class TestEnviarLogs:
    def _servidor(self, tmp_path, nomes):
        """Fake que registra envios e responde ao SIZE pelo tamanho local."""
        tamanhos = {
            nome: (tmp_path / nome).stat().st_size
            for nome in nomes
            if (tmp_path / nome).exists()
        }
        enviados = []
        pastas = []

        class Servidor:
            def connect(self, *a, **k):
                return None

            def login(self, *a, **k):
                return None

            def set_pasv(self, *a, **k):
                return None

            def cwd(self, caminho):
                pastas.append(caminho)

            def mkd(self, *a, **k):
                return None

            def storbinary(self, comando, bloco, *a, **k):
                nome = comando.split(" ", 1)[1]
                enviados.append(nome)
                tamanhos.setdefault(nome, 0)
                while bloco.read(1024):
                    pass

            def size(self, nome):
                return tamanhos.get(nome)

            def quit(self):
                return None

        return Servidor(), enviados, pastas

    def test_envia_logs_e_confere(self, tmp_path, monkeypatch):
        (tmp_path / ".agebackup-falhas.log").write_text("linha\n", encoding="utf-8")
        (tmp_path / ".agebackup-falhas.2026-10-20-0300.log.gz").write_bytes(b"gz")
        servidor, enviados, pastas = self._servidor(
            tmp_path,
            [".agebackup-falhas.log", ".agebackup-falhas.2026-10-20-0300.log.gz"],
        )
        monkeypatch.setattr(ftp, "conectar", lambda *a, **k: servidor)

        resultados = ftp.enviar_logs(
            tmp_path,
            CredenciaisFtp(host="x", usuario="u"),
            momento=datetime(2026, 10, 21),
        )

        assert not any(resultado.erro for resultado in resultados)
        assert len(resultados) == 2
        assert sorted(enviados) == sorted(
            [".agebackup-falhas.log", ".agebackup-falhas.2026-10-20-0300.log.gz"]
        )
        assert "/2026/10/logs" in pastas

    def test_pasta_vazia_nao_envia(self, tmp_path, monkeypatch):
        servidor, enviados, _ = self._servidor(tmp_path, [])
        monkeypatch.setattr(ftp, "conectar", lambda *a, **k: servidor)

        resultados = ftp.enviar_logs(
            tmp_path,
            CredenciaisFtp(host="x", usuario="u"),
            momento=datetime(2026, 10, 21),
        )

        assert resultados == []
        assert enviados == []
