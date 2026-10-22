# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['entry_gui.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'agebackup.gui.app',
        'agebackup.gui.config_tab',
        'agebackup.gui.backup_tab',
        'agebackup.gui.compact_tab',
        'agebackup.gui.upload_tab',
        'agebackup.gui.restore_tab',
        'agebackup.gui.log_tab',
        'agebackup.gui.help_dialog',
        'agebackup.gui.utils',
        'agebackup.config_paths',
        'agebackup.logging_paths',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='agebackup-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
