# -*- mode: python ; coding: utf-8 -*-
#
# SM2 Map Overlay — PyInstaller build specification.
#
# Build:   pyinstaller --noconfirm build.spec
# Output:  dist/detector.exe   (single self-contained file, no console)
#
# EVERYTHING is bundled inside the exe — Tesseract included — so end users
# only download detector.exe and run it. Nothing else to install.
#
# To stay under 100 MB, place a TRIMMED Tesseract-OCR folder next to this
# spec before building. It must contain ONLY:
#     Tesseract-OCR/
#     ├── tesseract.exe
#     ├── *.dll                  (all DLLs shipped with Tesseract)
#     └── tessdata/
#         └── eng.traineddata    (English only — delete every other language)
#
# A full Tesseract install is ~150 MB because tessdata/ holds 100+ languages.
# Keeping only eng.traineddata (~4 MB, or ~15 MB for the best-quality model)
# brings the whole exe to roughly 70-90 MB.

block_cipher = None

a = Analysis(
    ['detector.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('Tesseract-OCR', 'Tesseract-OCR'),   # bundled INTO the exe
        ('app_icon.ico', '.'),
        ('app_icon.png', '.'),
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'pystray._win32',
        'urllib.request',
        'pyrect',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Only exclude heavy THIRD-PARTY packages this app never imports.
        # Never exclude stdlib modules (urllib, unittest, email, http, xml,
        # multiprocessing, etc.) — indirect dependencies rely on them and
        # excluding them causes ModuleNotFoundError crashes at runtime.
        'scipy', 'sklearn', 'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'keras', 'matplotlib', 'pandas',
        'notebook', 'IPython', 'jupyter',
        'PyQt5', 'PyQt6', 'wx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Drop heavyweight native libs that cv2/numpy may pull in but this app never
# calls into (Qt GUI backends, MKL/OpenBLAS math kernels). Binary .dll/.pyd
# files only — safe to remove, unlike Python modules.
a.binaries = [b for b in a.binaries if not any(token in b[0].lower() for token in (
    'libopenblas', 'mkl_', 'qt5', 'qt6', 'qwindows',
))]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='detector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,         # UPX is intentionally OFF: combined with the global
                       # keyboard hook, screen capture and registry writes,
                       # UPX-packed exes trip many antivirus/SmartScreen
                       # heuristics. The small size saving is not worth the
                       # extra false-positive risk for end users.
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)
