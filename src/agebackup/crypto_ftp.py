"""Criptografia da senha FTP no arquivo de configuração."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from agebackup import config_paths

try:
    from cryptography.fernet import Fernet, InvalidToken

    _TEM_CRYPTO = True
except Exception:
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore
    _TEM_CRYPTO = False


def _caminho_chave() -> Path:
    return config_paths.get_config_dir() / ".agebackup-ftp.key"


def _obter_chave() -> bytes:
    caminho = _caminho_chave()
    if caminho.exists():
        try:
            return caminho.read_bytes().strip()
        except Exception:
            pass
    if _TEM_CRYPTO:
        chave = Fernet.generate_key()
    else:
        # Fallback simples (não é ideal, mas evita quebrar sem cryptography)
        import hashlib

        chave = base64.urlsafe_b64encode(hashlib.sha256(os.urandom(32)).digest())
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(chave)
        try:
            os.chmod(caminho, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return chave


def criptografar(senha: str) -> str:
    if not senha:
        return ""
    if _TEM_CRYPTO and Fernet is not None:
        try:
            f = Fernet(_obter_chave())
            return f.encrypt(senha.encode("utf-8")).decode("utf-8")
        except Exception:
            pass
    # Fallback: base64 of xor - last resort
    try:
        import hashlib

        chave = _obter_chave()
        dados = senha.encode("utf-8")
        xor = bytes([dados[i] ^ chave[i % len(chave)] for i in range(len(dados))])
        return "plain:" + base64.b64encode(xor).decode("ascii")
    except Exception:
        return senha


def descriptografar(valor: str) -> str:
    if not valor:
        return ""
    if valor.startswith("plain:"):
        try:
            import hashlib

            chave = _obter_chave()
            xor = base64.b64decode(valor[6:])
            dados = bytes([xor[i] ^ chave[i % len(chave)] for i in range(len(xor))])
            return dados.decode("utf-8")
        except Exception:
            return ""
    if _TEM_CRYPTO and Fernet is not None:
        try:
            f = Fernet(_obter_chave())
            return f.decrypt(valor.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return ""
        except Exception:
            return ""
    return ""
