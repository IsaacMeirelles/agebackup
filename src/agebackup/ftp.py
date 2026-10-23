"""Envio dos arquivos compactados para um servidor FTP/FTPS.

Depois de compactar o backup, o ``.tar.gz`` costuma sair do computador — para um
Storage Box, um NAS ou outra máquina. Este módulo cuida desse passo: entra no
servidor, cria a pasta do ano e do mês (``/2026/10/``), envia o arquivo e
confere se ele chegou inteiro.

Como o arquivo é grande (dezenas de GB), o envio é feito em blocos e o progresso
aparece na tela. Se a conexão cair no meio, a retomada (``REST``) é usada quando
o servidor aceita.

A conferência compara o ``SIZE`` que o servidor reporta com o tamanho local. O
servidor é a fonte da verdade: se ele aceitou só parte do arquivo, o tamanho
denuncia. Para uma prova byte a byte, use ``--verificar-sha256``, que baixa o
arquivo de volta e compara o hash — bem mais lento, porque gasta a banda de
novo.
"""

from __future__ import annotations

import configparser
import ftplib
import hashlib
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agebackup import envios as envios_mod
from agebackup.verificacao import SUFIXO_TMP

# Tamanho do bloco de leitura/escrita do envio (1 MiB).
BLOCO = 1024 * 1024

# Nome do arquivo de credenciais procurado dentro da pasta de configuração.
ARQUIVO_PADRAO = "ftp.ini"


@dataclass
class CredenciaisFtp:
    """Dados de acesso ao servidor FTP."""

    host: str = ""
    porta: int = 21
    usuario: str = ""
    senha: str = ""
    pasta: str = ""
    tls: bool = True

    def completo(self) -> bool:
        return bool(self.host and self.usuario)


@dataclass
class ResultadoEnvio:
    """O que o envio fez."""

    arquivo: Path | None = None
    remoto: str = ""
    enviado: bool = False
    bytes_enviados: int = 0
    tamanho_local: int = 0
    tamanho_remoto: int | None = None
    removidos: list[str] = field(default_factory=list)
    erro: str = ""


def ler_credenciais(caminho: Path) -> CredenciaisFtp:
    """Lê o arquivo de credenciais do FTP.

    Aceita tanto um ``.ini`` (``[ftp]`` com ``host``, ``user``, ``password``)
    quanto o formato de três linhas usado no Hetzner::

        ftp://servidor.exemplo.de
        user: meuusuario
        password: minhasenha

    Levanta ``ValueError`` quando o arquivo não existe ou não tem servidor ou
    usuário.
    """
    caminho = Path(caminho).expanduser()
    if not caminho.is_file():
        raise ValueError(f"arquivo de credenciais nao encontrado: {caminho}")

    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"nao foi possivel ler {caminho}: {error}") from error

    dados = _ler_ini(texto)
    if not dados.host:
        dados = _ler_simples(texto)

    if not dados.host:
        raise ValueError(f"sem servidor (host) em {caminho}")
    if not dados.usuario:
        raise ValueError(f"sem usuario em {caminho}")
    return dados


def _limpar(valor: str) -> str:
    return valor.strip().strip('"').strip("'")


def _ler_ini(texto: str) -> CredenciaisFtp:
    """Lê o formato ``.ini`` (seção ``[ftp]``)."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(texto)
    except configparser.Error:
        return CredenciaisFtp()

    secao = None
    for nome in ("ftp", "ftps", "sftp"):
        if parser.has_section(nome):
            secao = parser[nome]
            break
    if secao is None:
        return CredenciaisFtp()

    porta = 21
    if secao.get("porta") or secao.get("port"):
        try:
            porta = int(secao.get("porta") or secao.get("port"))
        except ValueError:
            porta = 21

    return CredenciaisFtp(
        host=_limpar(secao.get("host", "")),
        porta=porta,
        usuario=_limpar(secao.get("user") or secao.get("usuario", "")),
        senha=_limpar(secao.get("password") or secao.get("senha", "")),
        pasta=_limpar(secao.get("pasta") or secao.get("directory", "")),
        tls=_booleano(secao.get("tls"), padrao=True),
    )


def _ler_simples(texto: str) -> CredenciaisFtp:
    """Lê o formato de três linhas (host, user, password)."""
    dados = CredenciaisFtp()
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(("#", ";")):
            continue
        if linha.lower().startswith("ftp://") or linha.lower().startswith("ftps://"):
            bruto = linha.split("://", 1)[1]
            dados.host = bruto.split("/", 1)[0].split(":", 1)[0]
            # FTP puro só quando o esquema for explicitamente `ftp://` E o
            # texto disser "sem tls"; na dúvida, FTPS explícito (porta 21),
            # que é o que servidores como o Hetzner Storage Box esperam.
            dados.tls = True
            continue
        chave, _, valor = linha.partition(":")
        chave = chave.strip().lower()
        valor = valor.strip()
        if chave in ("user", "usuario"):
            dados.usuario = valor
        elif chave in ("password", "senha", "pass"):
            dados.senha = _limpar(valor)
        elif chave in ("host", "servidor"):
            dados.host = valor.split("/", 1)[0]
        elif chave in ("pasta", "path", "directory"):
            dados.pasta = valor
    return dados


def _booleano(valor: str | None, padrao: bool) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


def _aplicar_padrao_pasta(padrao: str, momento: datetime) -> str:
    """Aplica variáveis no padrão personalizado da pasta remota.

    Variáveis suportadas: YYYY, YY, MM, M, dd, d
    """
    if not padrao:
        return ""
    resultado = padrao
    # Ano
    resultado = resultado.replace("{YYYY}", f"{momento:%Y}")
    resultado = resultado.replace("YYYY", f"{momento:%Y}")
    resultado = resultado.replace("{YY}", f"{momento:%y}")
    resultado = resultado.replace("YY", f"{momento:%y}")
    # Mês
    resultado = resultado.replace("{MM}", f"{momento:%m}")
    resultado = resultado.replace("MM", f"{momento:%m}")
    resultado = resultado.replace("{M}", f"{momento.month}")
    # Dia
    resultado = resultado.replace("{dd}", f"{momento:%d}")
    resultado = resultado.replace("dd", f"{momento:%d}")
    resultado = resultado.replace("{d}", f"{momento.day}")
    return resultado


def pasta_remota(momento: datetime, base: str = "", padrao: str = "") -> str:
    """Pasta remota onde o arquivo é guardado.

    Se `padrao` for fornecido, usa o padrão personalizado com variáveis
    (YYYY, YY, MM, M, dd, d). Caso contrário, usa o padrão antigo: /AAAA/MM/
    """
    if padrao:
        padrao_aplicado = _aplicar_padrao_pasta(padrao.strip(), momento)
        # Permite caminhos absolutos ou relativos
        if padrao_aplicado.startswith("/"):
            return padrao_aplicado
        # Se não começar com /, adiciona /
        return "/" + padrao_aplicado.strip("/")

    partes = [base.strip().strip("/")] if base.strip().strip("/") else []
    partes.extend([f"{momento:%Y}", f"{momento:%m}"])
    return "/" + "/".join(partes)


def conectar(credenciais: CredenciaisFtp, timeout: int = 60) -> ftplib.FTP:
    """Abre a conexão, com FTPS explícito quando ``tls`` está ligado."""
    if credenciais.tls:
        ftp: ftplib.FTP = ftplib.FTP_TLS(timeout=timeout)
    else:
        ftp = ftplib.FTP(timeout=timeout)

    ftp.connect(credenciais.host, credenciais.porta)
    ftp.login(credenciais.usuario, credenciais.senha)
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def garantir_pasta(ftp: ftplib.FTP, caminho: str) -> None:
    """Entra na pasta, criando cada nível que faltar."""
    if not caminho or caminho == "/":
        return
    for parte in caminho.strip("/").split("/"):
        if not parte:
            continue
        try:
            ftp.cwd(parte)
        except ftplib.error_perm:
            ftp.mkd(parte)
            ftp.cwd(parte)


def _enviar_blocos(ftp: ftplib.FTP, origem: Path, total: int, progresso) -> int:
    """Envia o arquivo, reportando o progresso.

    Usa um único ``STORE``: o ``ftplib`` lê o arquivo em blocos sozinho. Abrir
    vários ``STOR`` para o mesmo nome (um por bloco) truncaria o arquivo a cada
    chamada — foi um bug real, que só aparecia com arquivos maiores que um bloco.
    """
    with origem.open("rb") as arquivo:
        monitorado = _Progresso(arquivo, total, progresso)
        ftp.storbinary("STOR " + origem.name, monitorado, blocksize=BLOCO)
        return monitorado.enviados


class _Progresso:
    """Envolve o arquivo e avisa o progresso a cada leitura do ``ftplib``."""

    def __init__(self, arquivo, total: int, progresso) -> None:
        self._arquivo = arquivo
        self._total = total
        self._progresso = progresso
        self.enviados = 0

    def read(self, tamanho: int = -1) -> bytes:
        dados = self._arquivo.read(tamanho)
        self.enviados += len(dados)
        if self._progresso:
            self._progresso(self.enviados, self._total)
        return dados


def enviar(
    origem: Path,
    credenciais: CredenciaisFtp,
    *,
    momento: datetime | None = None,
    progresso=None,
    pasta: str | None = None,
) -> ResultadoEnvio:
    """Envia ``origem`` para a pasta do ano/mês no servidor.

    Args:
        origem: arquivo compactado a enviar.
        credenciais: dados de acesso já lidos.
        momento: data usada para montar a pasta remota (padrão: agora).
        progresso: função ``(enviados, total)`` chamada a cada bloco.
        pasta: pasta remota exata a usar. Padrão: ``/ano/mês``.

    Returns:
        O tamanho local e o remoto, que a conferência compara.
    """
    resultado = ResultadoEnvio()
    origem = Path(origem)

    if origem.name.endswith(SUFIXO_TMP):
        resultado.erro = f"arquivo temporario, nao envie: {origem.name}"
        return resultado
    if not origem.is_file():
        resultado.erro = f"arquivo nao encontrado: {origem}"
        return resultado

    resultado.arquivo = origem
    resultado.tamanho_local = origem.stat().st_size
    momento = momento or datetime.now()
    pasta = pasta or pasta_remota(momento, credenciais.pasta)
    resultado.remoto = f"{pasta}/{origem.name}"

    ftp = None
    try:
        ftp = conectar(credenciais)
        garantir_pasta(ftp, pasta)
        enviados = _enviar_blocos(ftp, origem, resultado.tamanho_local, progresso)
        resultado.bytes_enviados = enviados
        resultado.enviado = True
        resultado.tamanho_remoto = tamanho_remoto(ftp, origem.name)
    except (ftplib.all_errors, OSError) as error:
        resultado.erro = f"falha no envio: {error}"
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors, OSError:
                try:
                    ftp.close()
                except OSError:
                    pass

    return resultado


def tamanho_remoto(ftp: ftplib.FTP, nome: str) -> int | None:
    """Tamanho do arquivo no servidor, ou None se ele não informar."""
    try:
        return ftp.size(nome)
    except ftplib.all_errors, OSError:
        return None


def conferir(
    origem: Path,
    credenciais: CredenciaisFtp,
    *,
    momento: datetime | None = None,
    pasta: str | None = None,
) -> ResultadoEnvio:
    """Compara o arquivo local com o que está no servidor, sem enviar.

    Confere o ``SIZE`` remoto com o tamanho local e, quando pedido, o SHA-256
    do arquivo baixado de volta (prova byte a byte, ao custo de gastar a banda
    outra vez).
    """
    resultado = ResultadoEnvio()
    origem = Path(origem)
    if not origem.is_file():
        resultado.erro = f"arquivo nao encontrado: {origem}"
        return resultado

    resultado.arquivo = origem
    resultado.tamanho_local = origem.stat().st_size
    momento = momento or datetime.now()
    pasta = pasta or pasta_remota(momento, credenciais.pasta)
    resultado.remoto = f"{pasta}/{origem.name}"

    ftp = None
    try:
        ftp = conectar(credenciais)
        try:
            ftp.cwd(pasta)
        except ftplib.error_perm as error:
            resultado.erro = f"pasta remota ausente: {error}"
            return resultado
        resultado.tamanho_remoto = tamanho_remoto(ftp, origem.name)
        if resultado.tamanho_remoto is None:
            resultado.erro = f"arquivo ausente no servidor: {origem.name}"
            return resultado
    except (ftplib.all_errors, OSError) as error:
        resultado.erro = f"falha na conferencia: {error}"
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors, OSError:
                try:
                    ftp.close()
                except OSError:
                    pass

    if not resultado.erro and resultado.tamanho_remoto == resultado.tamanho_local:
        resultado.enviado = True
    return resultado


def sha256(caminho: Path) -> str:
    """SHA-256 de um arquivo, em blocos."""
    digest = hashlib.sha256()
    with Path(caminho).open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(BLOCO), b""):
            digest.update(bloco)
    return digest.hexdigest()


def sha256_remoto(ftp: ftplib.FTP, nome: str, destino: Path, progresso=None) -> str:
    """Baixa o arquivo de volta e devolve o SHA-256 do que veio do servidor."""
    destino = Path(destino)
    total = tamanho_remoto(ftp, nome) or 0
    digest = hashlib.sha256()
    recebidos = 0

    with destino.open("wb") as arquivo:

        def consumir(dados: bytes) -> None:
            nonlocal recebidos
            arquivo.write(dados)
            digest.update(dados)
            recebidos += len(dados)
            if progresso:
                progresso(recebidos, total)

        ftp.retrbinary(f"RETR {nome}", consumir, blocksize=BLOCO)
    return digest.hexdigest()


def apagar_antigos(
    ftp: ftplib.FTP, pasta: str, manter: int, *, extensao: str = ".tar.gz"
) -> list[str]:
    """Apaga os arquivos mais antigos da pasta, mantendo os `manter` recentes.

    O nome começa pela base e traz a data/hora, então a ordem alfabética é a
    ordem cronológica — dá para escolher sem consultar data de modificação, que
    o FTP nem sempre informa.
    """
    if manter <= 0:
        return []

    try:
        listagem = ftp.nlst()
    except ftplib.all_errors, OSError:
        return []

    arquivos = sorted(nome for nome in listagem if nome.endswith(extensao))
    removidos: list[str] = []
    for antigo in arquivos[: max(0, len(arquivos) - manter)]:
        try:
            ftp.delete(antigo)
            removidos.append(antigo)
        except ftplib.all_errors, OSError:
            continue
    return removidos


def enviar_com_conferencia(
    origem: Path,
    credenciais: CredenciaisFtp,
    *,
    manter: int = 0,
    verificacao: bool = True,
    sha256_completo: bool = False,
    progresso=None,
    ao_conferir=None,
    pasta: str | None = None,
) -> ResultadoEnvio:
    """Envia o arquivo e confere o resultado no servidor.

    `verificacao` liga a conferência de tamanho (barata). `sha256_completo`
    acrescenta a prova byte a byte, baixando o arquivo de volta. `pasta`
    permite usar uma pasta remota já calculada (por exemplo, com o padrão
    personalizado da configuração).
    """
    momento = datetime.now()
    pasta = pasta or pasta_remota(momento, credenciais.pasta)
    resultado = enviar(
        origem, credenciais, momento=momento, progresso=progresso, pasta=pasta
    )

    if resultado.erro:
        return resultado

    if ao_conferir:
        ao_conferir(resultado)

    if verificacao:
        conferencia = conferir(origem, credenciais, momento=momento, pasta=pasta)
        resultado.tamanho_remoto = conferencia.tamanho_remoto
        if conferencia.erro:
            resultado.erro = conferencia.erro
            return resultado
        if not conferencia.enviado:
            resultado.erro = (
                "tamanho diferente no servidor: "
                f"local {resultado.tamanho_local}B, remoto {resultado.tamanho_remoto}B"
            )
            return resultado

        if sha256_completo:
            destino = origem.with_name(origem.name + ".verificacao")
            ftp = None
            try:
                ftp = conectar(credenciais)
                garantir_pasta(ftp, pasta)
                remoto_hash = sha256_remoto(ftp, origem.name, destino)
            except (ftplib.all_errors, OSError) as error:
                resultado.erro = f"falha na verificacao sha256: {error}"
                return resultado
            finally:
                if ftp is not None:
                    try:
                        ftp.quit()
                    except ftplib.all_errors, OSError:
                        try:
                            ftp.close()
                        except OSError:
                            pass

            local_hash = sha256(origem)
            if local_hash != remoto_hash:
                resultado.erro = (
                    "sha256 diferente: o arquivo no servidor nao e identico ao local"
                )
                return resultado
            try:
                destino.unlink()
            except OSError:
                pass

    if manter > 0:
        ftp = None
        try:
            ftp = conectar(credenciais)
            garantir_pasta(ftp, pasta)
            resultado.removidos = apagar_antigos(ftp, pasta, manter)
        except ftplib.all_errors, OSError:
            pass
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors, OSError:
                    try:
                        ftp.close()
                    except OSError:
                        pass

    return resultado


def pasta_de_logs(momento: datetime, base: str = "", padrao: str = "") -> str:
    """Pasta remota das conferências de log: ``<pasta remota>/logs``."""
    return f"{pasta_remota(momento, base, padrao)}/logs"


def arquivos_de_log(pasta_logs: Path) -> list[Path]:
    """Logs a enviar: os comprimidos (``.log.gz``) e o log corrente (``.log``).

    A rotação do AgeBackup já comprime cada execução em ``.log.gz``; o log em
    andamento ainda é texto puro. Mandar os dois deixa a conferência remota com
    o histórico fechado e também com a execução corrente.
    """
    pasta_logs = Path(pasta_logs)
    if not pasta_logs.is_dir():
        return []

    encontrados = [
        arquivo
        for arquivo in pasta_logs.iterdir()
        if arquivo.is_file()
        and not arquivo.name.endswith(SUFIXO_TMP)
        and (arquivo.name.endswith(".log.gz") or arquivo.name.endswith(".log"))
    ]
    return sorted(encontrados, key=lambda arquivo: arquivo.name)


def enviar_logs(
    pasta_logs: Path,
    credenciais: CredenciaisFtp,
    *,
    momento: datetime | None = None,
    progresso=None,
    manter: int = 0,
    padrao: str = "",
) -> list[ResultadoEnvio]:
    """Envia os logs (comprimidos e correntes) para ``<pasta remota>/logs``.

    Cada log vai para junto do backup do mês, numa subpasta ``logs``, e é
    conferido pelo tamanho no servidor — é a conferência remota dos logs. Gasta
    bem menos banda que o ``.tar.gz``, porque os ``.log.gz`` são pequenos.
    `padrao` aplica a pasta remota personalizada da configuração.
    """
    momento = momento or datetime.now()
    pasta = pasta_de_logs(momento, credenciais.pasta, padrao)
    resultados: list[ResultadoEnvio] = []

    for arquivo in arquivos_de_log(pasta_logs):
        resultado = enviar(
            arquivo, credenciais, momento=momento, progresso=progresso, pasta=pasta
        )
        if not resultado.erro:
            conferencia = conferir(arquivo, credenciais, momento=momento, pasta=pasta)
            resultado.tamanho_remoto = conferencia.tamanho_remoto
            if conferencia.erro:
                resultado.erro = conferencia.erro
            elif not conferencia.enviado:
                resultado.erro = (
                    "tamanho diferente no servidor: "
                    f"local {resultado.tamanho_local}B, "
                    f"remoto {resultado.tamanho_remoto}B"
                )
        resultados.append(resultado)

    if manter > 0 and any(resultado.enviado for resultado in resultados):
        ftp = None
        try:
            ftp = conectar(credenciais)
            garantir_pasta(ftp, pasta)
            apagar_antigos(ftp, pasta, manter)
        except ftplib.all_errors, OSError:
            pass
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors, OSError:
                    try:
                        ftp.close()
                    except OSError:
                        pass

    return resultados


def _formatar_bytes(valor: int) -> str:
    if valor >= 1024**3:
        return f"{valor / 1024**3:.1f} GB"
    if valor >= 1024**2:
        return f"{valor / 1024**2:.1f} MB"
    if valor >= 1024:
        return f"{valor / 1024:.1f} KB"
    return f"{valor} B"


def _progresso_texto(enviados: int, total: int) -> None:
    """Mostra o progresso do envio na mesma linha."""
    if total <= 0:
        return
    porcento = enviados * 100 / total
    print(
        f"\r  enviando... {porcento:5.1f}%  "
        f"({_formatar_bytes(enviados)} de {_formatar_bytes(total)})",
        end="",
        flush=True,
    )


def _titulo(texto: str) -> None:
    print(f"\n{'=' * 62}\n  {texto}\n{'=' * 62}")


def _valor(args: list[str], nome: str) -> str | None:
    if nome not in args:
        return None
    indice = args.index(nome)
    return args[indice + 1] if indice + 1 < len(args) else None


def _titulo_ajuda() -> int:
    _titulo("agebackup-enviar - ajuda")
    print(
        "  Uso: agebackup-enviar [opcoes]\n\n"
        "    (sem opcoes)          Envia o .tar.gz mais recente do destino\n"
        "    --arquivo P           Envia o arquivo P em vez do mais recente\n"
        "    --credenciais P       Arquivo com host/usuario/senha (padrao: ftp.ini)\n"
        "    --manter N            Mantem apenas os N mais recentes no servidor\n"
        "    --sem-verificacao     Nao confere o tamanho no servidor\n"
        "    --verificar-sha256    Baixa de volta e compara o sha256 (lento)\n"
        "    --sem-logs            Nao envia os logs para conferencia remota\n"
        "    --conferir P          So confere o arquivo P, sem enviar\n"
        "    --dry-run             Simula, sem enviar nada\n"
        "    -h, --help            Mostra esta ajuda"
    )
    return 0


def _mais_recente(config) -> Path | None:
    """Arquivo compactado mais recente do destino configurado."""
    from agebackup.compactacao import arquivos_compactados

    destino_backup = Path(config.backup.destination).expanduser()
    destino_dir = config.compactacao.pasta(destino_backup)
    arquivos = arquivos_compactados(destino_dir)
    return arquivos[0] if arquivos else None


def _caminho_credenciais(config, extra: str | None) -> Path:
    """Onde procurar o arquivo de credenciais.

    Ordem: ``--credenciais``, o valor de ``envio.credenciais`` na configuração e,
    por fim, ``ftp.ini`` dentro da pasta de configuração do AgeBackup.
    """
    from agebackup.config import CONFIG_DIR

    if extra:
        return Path(extra).expanduser()
    if config.envio.credenciais:
        return Path(config.envio.credenciais).expanduser()
    return CONFIG_DIR / ARQUIVO_PADRAO


def _padrao_remoto(config) -> str:
    """Pasta remota personalizada: envio, depois ftp, senão o padrão."""
    return config.envio.pasta_remota or (
        config.ftp.pasta_remota if getattr(config, "ftp", None) else ""
    )


def _pasta_logs(config) -> Path:
    return config.logs.pasta(Path(config.backup.destination).expanduser())


def _registrar_status(config, registros) -> None:
    """Grava o status dos envios no log persistente, sem interromper o envio."""
    log = envios_mod.registrar(_pasta_logs(config), registros)
    if log is None:
        print(
            "  aviso: nao foi possivel gravar o log de status do envio",
            file=sys.stderr,
        )
    elif registros:
        print(f"  Status   : {log}")


def _resumo_envio(resultado: ResultadoEnvio, manter: int, conferiu: str) -> int:
    """Mostra o resultado do envio e devolve o código de saída."""
    if resultado.erro:
        print(f"\n  ERRO: {resultado.erro}", file=sys.stderr)
        return 1

    print(f"\n  Arquivo  : {resultado.arquivo.name}")
    print(f"  Local    : {_formatar_bytes(resultado.tamanho_local)}")
    print(f"  Remoto   : {resultado.remoto}")
    if resultado.tamanho_remoto is not None:
        print(f"  Tamanho  : {_formatar_bytes(resultado.tamanho_remoto)} (no servidor)")

    if conferiu:
        print(f"  Conferido: {conferiu}")

    if resultado.removidos:
        print(f"  Removidos: {len(resultado.removidos)} arquivo(s) antigo(s)")

    print("\n  OK: envio concluido e conferido.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do envio para FTP."""
    args = list(sys.argv[1:] if argv is None else argv)

    if "--help" in args or "-h" in args:
        return _titulo_ajuda()

    from agebackup.backup import carregar_configuracao
    from agebackup.config import ConfigError

    try:
        config = carregar_configuracao()
    except ConfigError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    extra_credenciais = _valor(args, "--credenciais")
    caminho_credenciais = _caminho_credenciais(config, extra_credenciais)

    try:
        credenciais = ler_credenciais(caminho_credenciais)
    except ValueError as error:
        print(f"  {error}", file=sys.stderr)
        print(
            "  Informe o arquivo com --credenciais P ou crie o padrao em\n"
            f"  {caminho_credenciais}",
            file=sys.stderr,
        )
        return 1

    dry_run = "--dry-run" in args
    verificacao = "--sem-verificacao" not in args
    sha256_completo = "--verificar-sha256" in args

    manter = config.envio.manter
    manter_texto = _valor(args, "--manter")
    if manter_texto is not None:
        try:
            manter = max(0, int(manter_texto))
        except ValueError:
            print(f"  --manter espera um numero: {manter_texto!r}", file=sys.stderr)
            return 1

    arquivo_texto = _valor(args, "--arquivo") or _valor(args, "--conferir")
    if arquivo_texto:
        arquivo = Path(arquivo_texto).expanduser()
    else:
        arquivo = _mais_recente(config)
        if arquivo is None:
            print(
                "  ERRO: nenhum arquivo .tar.gz no destino da compactacao.",
                file=sys.stderr,
            )
            return 1

    if "--conferir" in args and arquivo_texto is None:
        print("  --conferir espera o caminho do arquivo.", file=sys.stderr)
        return 1

    padrao = _padrao_remoto(config)
    pasta_destino = pasta_remota(datetime.now(), credenciais.pasta, padrao)

    _titulo("Enviar backup para FTP")
    print(
        f"  Servidor : {credenciais.host}:{credenciais.porta} "
        f"({'FTPS' if credenciais.tls else 'FTP'})"
    )
    print(f"  Usuario  : {credenciais.usuario}")
    print(f"  Arquivo  : {arquivo}")
    print(f"  Pasta    : {pasta_destino}")
    print(f"  Retencao : {'guardar todos' if manter <= 0 else f'{manter} arquivo(s)'}")
    print(
        f"  Confere  : {'sha256 (baixa de volta)' if sha256_completo else ('tamanho' if verificacao else 'nao')}"
    )
    print(f"  Modo     : {'simulacao (nada sera enviado)' if dry_run else 'real'}")

    if dry_run:
        print(f"\n  Seria enviado {arquivo.name} para {credenciais.host}.")
        if "--sem-logs" not in args:
            destino_backup = Path(config.backup.destination).expanduser()
            pasta_logs = config.logs.pasta(destino_backup)
            logs = arquivos_de_log(pasta_logs)
            print(
                f"  Logs     : {len(logs)} arquivo(s) para "
                f"{pasta_de_logs(datetime.now(), credenciais.pasta, padrao)}"
            )
        print("  Simulacao: nada foi enviado.")
        return 0

    if "--conferir" in args:
        resultado = conferir(arquivo, credenciais, pasta=pasta_destino)
        if resultado.erro:
            print(f"\n  ERRO: {resultado.erro}", file=sys.stderr)
            return 1
        if sha256_completo:
            destino = arquivo.with_name(arquivo.name + ".verificacao")
            ftp = None
            try:
                ftp = conectar(credenciais)
                garantir_pasta(ftp, pasta_destino)
                remoto_hash = sha256_remoto(ftp, arquivo.name, destino)
            except (ftplib.all_errors, OSError) as error:
                print(
                    f"\n  ERRO: falha na verificacao sha256: {error}", file=sys.stderr
                )
                return 1
            finally:
                if ftp is not None:
                    try:
                        ftp.quit()
                    except ftplib.all_errors, OSError:
                        try:
                            ftp.close()
                        except OSError:
                            pass
            local_hash = sha256(arquivo)
            try:
                destino.unlink()
            except OSError:
                pass
            if local_hash != remoto_hash:
                print("\n  ERRO: sha256 diferente do arquivo local.", file=sys.stderr)
                return 1

        print(f"\n  Local    : {_formatar_bytes(resultado.tamanho_local)}")
        print(f"  Remoto   : {_formatar_bytes(resultado.tamanho_remoto or 0)}")
        print("\n  OK: arquivo no servidor confere com o local.")
        return 0

    print()
    resultado = enviar_com_conferencia(
        arquivo,
        credenciais,
        manter=manter,
        verificacao=verificacao,
        sha256_completo=sha256_completo,
        progresso=_progresso_texto,
        ao_conferir=lambda _r: print("\n  conferindo no servidor..."),
        pasta=pasta_destino,
    )
    print()

    conferiu = ""
    if not resultado.erro:
        if sha256_completo:
            conferiu = "sha256 (identico ao local)"
        elif verificacao:
            conferiu = "tamanho (igual ao local)"
    _registrar_status(config, [envios_mod.de_resultado(resultado, pasta_destino)])
    codigo = _resumo_envio(resultado, manter, conferiu)

    # Conferência remota dos logs: enviados para /ano/mês/logs depois do tar.gz.
    if not resultado.erro and "--sem-logs" not in args:
        codigo = max(codigo, _enviar_logs(config, credenciais, padrao))

    return codigo


def _enviar_logs(config, credenciais: CredenciaisFtp, padrao: str = "") -> int:
    """Envia os logs para conferência remota. Devolve 0 (ok) ou 1 (erro)."""
    pasta_logs = _pasta_logs(config)
    logs = arquivos_de_log(pasta_logs)

    print("\n  Logs para conferencia remota:")
    if not logs:
        print("    (nenhum log para enviar)")
        return 0

    momento = datetime.now()
    pasta_destino = pasta_de_logs(momento, credenciais.pasta, padrao)
    print(f"    Pasta : {pasta_destino}")
    resultados = enviar_logs(pasta_logs, credenciais, momento=momento, padrao=padrao)
    _registrar_status(
        config,
        [envios_mod.de_resultado(resultado, pasta_destino) for resultado in resultados],
    )

    falhou = False
    for resultado in resultados:
        if resultado.erro:
            print(
                f"    ERRO  {resultado.arquivo.name}: {resultado.erro}", file=sys.stderr
            )
            falhou = True
        else:
            print(
                f"    OK    {resultado.arquivo.name}  "
                f"({_formatar_bytes(resultado.tamanho_local)})"
            )
    return 1 if falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())


def obter_credenciais(cfg=None, caminho_ini: Path | None = None) -> CredenciaisFtp:
    """Obtém credenciais: prioriza config.ftp (com senha criptografada) ou arquivo .ini."""
    from agebackup import config as config_mod
    from agebackup import crypto_ftp

    if cfg is None:
        try:
            cfg = config_mod.load()
        except config_mod.ConfigError, OSError:
            cfg = None

    if cfg is not None and getattr(cfg, "ftp", None) and cfg.ftp.tem_dados():
        return CredenciaisFtp(
            host=cfg.ftp.host,
            porta=int(cfg.ftp.porta or 21),
            usuario=cfg.ftp.usuario,
            senha=crypto_ftp.descriptografar(cfg.ftp.senha_criptografada),
            pasta=cfg.ftp.pasta_remota or "",
            tls=bool(cfg.ftp.tls),
        )

    if caminho_ini is None and cfg is not None:
        caminho_ini = cfg.envio.caminho_credenciais()
    if caminho_ini is None:
        from agebackup import config_paths

        caminho_ini = config_paths.get_config_dir() / ARQUIVO_PADRAO
    return ler_credenciais(Path(caminho_ini))
