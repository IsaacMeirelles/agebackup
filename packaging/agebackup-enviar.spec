# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o executável autônomo ``agebackup-enviar``.

Gera um binário único (onefile) que embute o interpretador, as dependências e
os arquivos de dados, funcionando sem Python instalado.

O comando abre uma conexão FTPS, então o ``cacert.pem`` do ``certifi`` entra
como dado: sem ele, a validação TLS do certificado do servidor falharia. O
restante dos dados (templates de ``pptx``/``docx`` e os documentos de descoberta
do Google) vem junto porque o pacote ``agebackup`` inteiro é importado.

Construa pela raiz do projeto com ``./packaging/build.sh``.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

RAIZ = Path(SPECPATH).parent  # raiz do projeto (packaging/..)

datas = []
datas += collect_data_files("pptx")  # templates de apresentação
datas += collect_data_files("docx")  # templates de documento
datas += collect_data_files("certifi")  # bundle de certificados CA (FTPS)
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
    [str(Path(SPECPATH) / "entry_enviar.py")],
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
    name="agebackup-enviar",
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
