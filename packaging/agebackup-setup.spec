# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o executável autônomo ``agebackup-setup``.

Gera um binário único (onefile) que embute o interpretador, as dependências e
os arquivos de dados, funcionando sem Python instalado.

Arquivos de dados incluídos além do que a análise estática acha sozinha:

- templates de ``python-pptx`` e ``python-docx`` (a tela de configuração importa
  ``agebackup`` inteiro, que importa a reconstrução);
- o ``cacert.pem`` do ``certifi`` (validação HTTPS no ``--test``);
- os documentos de *descoberta estática* da Drive API, para
  ``googleapiclient.discovery.build`` montar o cliente sem baixar o discovery.

Construa pela raiz do projeto com ``./packaging/build.sh``.
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

# Importados de forma dinâmica (dentro de funções) pelo google-auth/oauthlib;
# listados para garantir que entrem no binário.
hiddenimports = [
    "google.auth.transport.requests",
    "google.oauth2.service_account",
    "google_auth_oauthlib.flow",
]

a = Analysis(
    [str(Path(SPECPATH) / "entry_setup.py")],
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
    name="agebackup-setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
