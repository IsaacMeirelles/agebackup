"""gback — backup do Google Drive."""

from gback import config, falhas, rotacao
from gback.backup import FileEntry, Stats, executar_backup, listar_arquivos
from gback.config import AccountConfig, BackupConfig, Config, ConfigError
from gback.drive import (
    DownloadRestrictedError,
    DriveError,
    FileNotFoundInDriveError,
    TransientDriveError,
    can_download,
    download_blob,
    download_to,
    export_document,
    get_service,
    resolve_destination,
)
from gback.falhas import Falha

__all__ = [
    "AccountConfig",
    "BackupConfig",
    "Config",
    "ConfigError",
    "DownloadRestrictedError",
    "DriveError",
    "Falha",
    "FileEntry",
    "FileNotFoundInDriveError",
    "Stats",
    "TransientDriveError",
    "can_download",
    "config",
    "download_blob",
    "download_to",
    "executar_backup",
    "export_document",
    "falhas",
    "get_service",
    "listar_arquivos",
    "resolve_destination",
    "rotacao",
]


def main() -> None:
    print("Hello from gback!")
