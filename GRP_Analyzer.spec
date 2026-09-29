# -*- mode: python ; coding: utf-8 -*-

import os

_icon = 'icon.ico' if os.path.isfile('icon.ico') else None

a = Analysis(
    ['main_pg.py'],
    pathex=['.'],
    binaries=[],
    datas=[('icon.ico', '.')] if _icon else [],
    hiddenimports=['psycopg2', 'psycopg2.extras',
                   'core.config', 'core.models', 'core.timefmt',
                   'db.database_pg',
                   'logic.algorithms', 'logic.documentary_analyzer',
                   'logic.statistic_analyzer', 'logic.technical_analyzer_pg',
                   'integration.excel_sync', 'integration.pdf_parts_import',
                   'integration.word_report_pg',
                   'ui.views_pg', 'ui.algorithms_view'],
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
    name='GRP_Analyzer',
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
    icon=_icon,
)