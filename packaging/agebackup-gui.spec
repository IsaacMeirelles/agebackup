# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o executável autônomo ``agebackup-gui``.

Gera um binário único (onefile) com a janela única do AgeBackup, embutindo o
interpretador, o Tkinter, as dependências e os arquivos de dados.

Arquivos de dados incluídos além do que a análise estática acha sozinha:

- templates de ``python-pptx`` e ``python-docx`` (usados na reconstrução de
  nativos grandes);
- o ``cacert.pem`` do ``certifi`` (validação HTTPS);
- os documentos de *descoberta estática* da Drive API/Slides/Docs/Sheets, para
  ``googleapiclient.discovery.build`` montar o cliente sem baixar o discovery.

O ``agebackup.json`` fica **ao lado do executável** (``config_paths``). Construa
pela raiz do projeto com ``./packaging/build.sh``.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

RAIZ = Path(SPECPATH).parent  # raiz do projeto (packaging/..)

datas = []
datas += collect_data_files("pptx")  # templates de apresentação
datas += collect_data_files("docx")  # templates de documento
datas += collect_data_files("certifi")  # bundle de certificados CA
datas += collect_data_files(
    "googleapiclient",
    includes=[
        "discovery_cache/documents/drive.v3.json",
        "discovery_cache/documents/slides.v1.json",
        "discovery_cache/documents/docs.v1.json",
        "discovery_cache/documents/sheets.v4.json",
    ],
)

# Importados de forma dinâmica pelo google-auth/oauthlib e abas carregadas pela
# janela; listados para garantir que entrem no binário.
hiddenimports = [
    "google.auth.transport.requests",
    "google.oauth2.service_account",
    "google_auth_oauthlib.flow",
    "agebackup.gui.app",
    "agebackup.gui.config_tab",
    "agebackup.gui.backup_tab",
    "agebackup.gui.compact_tab",
    "agebackup.gui.upload_tab",
    "agebackup.gui.restore_tab",
    "agebackup.gui.log_tab",
    "agebackup.gui.help_dialog",
    "agebackup.gui.utils",
    "agebackup.config_paths",
    "agebackup.logging_paths",
]

a = Analysis(
    [str(Path(SPECPATH) / "entry_gui.py")],
    pathex=[str(RAIZ / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="agebackup-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
