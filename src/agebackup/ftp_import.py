"""Importa credenciais FTP do arquivo .ini para o config.json com senha criptografada."""

from __future__ import annotations

from pathlib import Path

from agebackup import config as config_mod
from agebackup import crypto_ftp, ftp


def importar_do_ini(caminho_ini: Path | None = None) -> bool:
    cfg = config_mod.load()
    if cfg is None:
        cfg = config_mod.Config()
    if caminho_ini is None:
        caminho_ini = cfg.envio.caminho_credenciais()
    caminho_ini = Path(caminho_ini).expanduser()
    if not caminho_ini.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_ini}")
    cred = ftp.ler_credenciais(caminho_ini)
    cfg.ftp = config_mod.FtpConfig(
        host=cred.host,
        porta=cred.porta,
        usuario=cred.usuario,
        senha_criptografada=crypto_ftp.criptografar(cred.senha),
        pasta_remota=cred.pasta or "",
        tls=cred.tls,
    )
    # Também atualiza envio.credenciais para manter compatibilidade
    cfg.envio.credenciais = str(caminho_ini)
    config_mod.save(cfg)
    return True
