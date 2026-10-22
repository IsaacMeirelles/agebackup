"""Resolução do caminho da configuração junto à aplicação.

A partir desta versão a configuração fica junto ao executável/aplicação
(`agebackup.json`). Quando não existir, migra automaticamente do local
antigo (`~/.config/agebackup/config.json`) com backup.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

LEGACY_CONFIG_DIR = Path.home() / ".config" / "agebackup"
LEGACY_CONFIG_FILE = LEGACY_CONFIG_DIR / "config.json"


def _app_dir() -> Path:
    """Diretório da aplicação (onde fica o executável ou o pacote em dev)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return exe.parent
    # Em desenvolvimento, usa a raiz do repositório/projeto.
    # Sobe a partir deste arquivo até encontrar pyproject.toml ou usa cwd.
    aqui = Path(__file__).resolve()
    for pai in aqui.parents:
        if (pai / "pyproject.toml").exists():
            return pai
        if (pai / "src").exists() and (pai / "agebackup.json").exists():
            return pai
    return Path.cwd()


def get_config_dir() -> Path:
    """Diretório onde fica agebackup.json (junto à aplicação)."""
    return _app_dir()


def get_config_path() -> Path:
    """Caminho do arquivo de configuração junto à aplicação."""
    return get_config_dir() / "agebackup.json"


def get_legacy_config_path() -> Path:
    """Caminho legado em ~/.config/agebackup/config.json."""
    return LEGACY_CONFIG_FILE


def get_ftp_ini_path_default() -> Path:
    """Caminho padrão do arquivo de credenciais FTP junto à app."""
    return get_config_dir() / "ftp.ini"


def ensure_config_dir() -> Path:
    """Garante que o diretório da config exista e retorna o caminho."""
    diretorio = get_config_dir()
    diretorio.mkdir(parents=True, exist_ok=True)
    return diretorio


def migrar_se_necessario() -> Path:
    """Garante que a configuração esteja junto à aplicação.

    - Se agebackup.json já existe junto à app, usa ele.
    - Senão, se existir config.json legado, copia para agebackup.json junto à app
      criando um backup do legado.
    - Retorna o caminho final da configuração.
    """
    atual = get_config_path()
    if atual.exists():
        return atual

    legado = get_legacy_config_path()
    if legado.exists():
        ensure_config_dir()
        # Copia o legado para junto à app
        shutil.copy2(legado, atual)
        # Cria backup do legado para segurança
        backup_legado = legado.with_suffix(".json.bak")
        try:
            if not backup_legado.exists():
                shutil.copy2(legado, backup_legado)
        except OSError:
            pass
        return atual

    return atual
