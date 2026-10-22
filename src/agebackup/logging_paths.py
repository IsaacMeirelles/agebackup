"""Utilitários para normalizar caminhos com caminho completo nos logs."""

from __future__ import annotations

from pathlib import Path


def caminho_completo(caminho: str | Path | None) -> str:
    """Retorna o caminho absoluto como string."""
    if caminho is None:
        return ""
    try:
        return str(Path(caminho).expanduser().resolve())
    except OSError, RuntimeError, ValueError:
        return str(caminho)
