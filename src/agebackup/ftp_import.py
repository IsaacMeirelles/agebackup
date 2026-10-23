"""Credenciais FTP: importação do ``.ini`` e gravação segura no config.json.

A partir desta versão os dados de acesso ao FTP/FTPS ficam dentro do próprio
``agebackup.json`` (seção ``ftp``), com a senha cifrada. O arquivo ``.ini``
continua aceito apenas para importar instalações antigas ou como alternativa
explícita em ``envio.credenciais``.
"""

from __future__ import annotations

from pathlib import Path

from agebackup import config as config_mod
from agebackup import crypto_ftp, ftp

PORTA_PADRAO = 21
PORTA_MINIMA = 1
PORTA_MAXIMA = 65535


def normalizar_porta(valor: object) -> int:
    """Valida e converte a porta FTP; vazio usa a porta 21."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return PORTA_PADRAO
    try:
        porta = int(valor)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Porta FTP inválida: {valor!r}") from error
    if not PORTA_MINIMA <= porta <= PORTA_MAXIMA:
        raise ValueError(
            f"Porta FTP fora da faixa permitida "
            f"({PORTA_MINIMA} a {PORTA_MAXIMA}): {porta}"
        )
    return porta


def aplicar_credenciais(
    cfg: config_mod.Config,
    *,
    host: str,
    porta: object = PORTA_PADRAO,
    usuario: str,
    senha: str = "",
    pasta: str = "",
    tls: bool = True,
    manter: int | None = None,
) -> config_mod.Config:
    """Grava as credenciais FTP no objeto de configuração.

    - ``senha`` vazia preserva a senha já cifrada (o usuário não precisa
      redigitá-la a cada salvamento).
    - Com host/usuário preenchidos, a seção ``ftp`` passa a ser a fonte das
      credenciais e ``envio.credenciais`` é limpo, para não deixar o caminho de
      um arquivo antigo como fallback enganoso.
    - Com host/usuário vazios, a seção ``ftp`` é limpa e o arquivo externo
      indicado em ``envio.credenciais`` volta a ser usado.
    """
    host = (host or "").strip()
    usuario = (usuario or "").strip()
    pasta = (pasta or "").strip()
    senha = senha or ""

    if bool(host) != bool(usuario):
        raise ValueError(
            "Preencha host e usuário do FTP juntos (ou deixe os dois vazios "
            "para usar um arquivo .ini externo)."
        )
    if not host and senha:
        raise ValueError("Informe host e usuário antes de cadastrar a senha FTP.")

    if host:
        porta_num = normalizar_porta(porta)
        if senha:
            senha_criptografada = crypto_ftp.criptografar(senha)
        else:
            senha_criptografada = cfg.ftp.senha_criptografada
        cfg.ftp = config_mod.FtpConfig(
            host=host,
            porta=porta_num,
            usuario=usuario,
            senha_criptografada=senha_criptografada,
            pasta_remota=pasta,
            tls=bool(tls),
        )
        cfg.envio.credenciais = ""
    else:
        cfg.ftp = config_mod.FtpConfig()

    cfg.envio.pasta_remota = pasta
    if manter is not None:
        cfg.envio.manter = max(0, min(config_mod.MANTER_ENVIO_MAXIMO, int(manter)))
    return cfg


def importar_do_ini(caminho_ini: Path | None = None) -> bool:
    """Importa credenciais FTP do arquivo .ini para o config.json.

    A senha é cifrada antes de ser gravada. O caminho do ``.ini`` não é mantido
    em ``envio.credenciais``: a partir da importação, os dados passam a viver
    no próprio ``agebackup.json``.
    """
    cfg = config_mod.load()
    if cfg is None:
        cfg = config_mod.Config()
    if caminho_ini is None:
        caminho_ini = cfg.envio.caminho_credenciais()
    caminho_ini = Path(caminho_ini).expanduser()
    if not caminho_ini.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_ini}")
    cred = ftp.ler_credenciais(caminho_ini)
    aplicar_credenciais(
        cfg,
        host=cred.host,
        porta=cred.porta,
        usuario=cred.usuario,
        senha=cred.senha,
        pasta=cred.pasta,
        tls=cred.tls,
    )
    config_mod.save(cfg)
    return True
