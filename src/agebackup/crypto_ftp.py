"""Criptografia das credenciais no arquivo de configuração.

Senha FTP, JSON da Service Account e token ADC ficam cifrados com Fernet
(``cryptography``). A chave é gerada na primeira gravação e guardada em
``.agebackup-ftp.key`` (nome mantido por compatibilidade), junto ao
``agebackup.json``, com permissão restrita. Sem a biblioteca ``cryptography``
instalada, os dados são guardados com uma ofuscação XOR (útil só para não
deixá-los em texto puro, sem a mesma garantia criptográfica).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
from pathlib import Path

from agebackup import config_paths

try:
    from cryptography.fernet import Fernet, InvalidToken

    _TEM_CRYPTO = True
except ImportError:  # ambiente sem a dependência opcional
    Fernet = None  # type: ignore[assignment]
    InvalidToken = ValueError  # type: ignore[assignment,misc]
    _TEM_CRYPTO = False

# Marca do formato alternativo (sem ``cryptography``).
PREFIXO_SIMPLES = "plain:"


def _caminho_chave() -> Path:
    return config_paths.get_config_dir() / ".agebackup-ftp.key"


def _obter_chave() -> bytes:
    """Lê (ou cria) a chave usada para cifrar a senha."""
    caminho = _caminho_chave()
    if caminho.exists():
        with contextlib.suppress(OSError):
            conteudo = caminho.read_bytes().strip()
            if conteudo:
                return conteudo

    if _TEM_CRYPTO:
        chave = Fernet.generate_key()
    else:
        chave = base64.urlsafe_b64encode(hashlib.sha256(os.urandom(32)).digest())

    with contextlib.suppress(OSError):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(chave)
        os.chmod(caminho, 0o600)
    return chave


def _xor(dados: bytes, chave: bytes) -> bytes:
    return bytes(dados[i] ^ chave[i % len(chave)] for i in range(len(dados)))


def criptografar(senha: str) -> str:
    """Cifra a senha para guardar no ``agebackup.json``."""
    if not senha:
        return ""
    chave = _obter_chave()
    if _TEM_CRYPTO and Fernet is not None:
        return Fernet(chave).encrypt(senha.encode("utf-8")).decode("ascii")
    return PREFIXO_SIMPLES + base64.b64encode(
        _xor(senha.encode("utf-8"), chave)
    ).decode("ascii")


def descriptografar(valor: str) -> str:
    """Devolve a senha em texto. Vazio quando não dá para decifrar."""
    if not valor:
        return ""
    chave = _obter_chave()
    if valor.startswith(PREFIXO_SIMPLES):
        with contextlib.suppress(ValueError):
            return _xor(base64.b64decode(valor[len(PREFIXO_SIMPLES) :]), chave).decode(
                "utf-8"
            )
        return ""
    if _TEM_CRYPTO and Fernet is not None:
        with contextlib.suppress(InvalidToken, ValueError):
            return Fernet(chave).decrypt(valor.encode("utf-8")).decode("utf-8")
    return ""
