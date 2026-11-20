# -*- mode: python ; coding: utf-8 -*-
"""单文件（onefile）打包：模型、运行时、PortAudio 全部塞进一个 EXE。

    python -m PyInstaller tingxie_onefile.spec --noconfirm

产物：dist/听写.exe —— 双击即用，不需要 _internal 目录。
首次启动会把内容解到 %TEMP%，之后同一进程复用。
"""
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()  # noqa: F821
MODEL_DIR = ROOT / "models" / "whisper-base"

datas = []
if MODEL_DIR.is_dir():
    datas.append((str(MODEL_DIR), "models/whisper-base"))

try:
    _spec = importlib.util.find_spec("sounddevice")
    if _spec and _spec.origin:
        portaudio = Path(_spec.origin).parent / "_sounddevice_data" / "portaudio-binaries"
        if portaudio.is_dir():
            datas.append((str(portaudio), "_sounddevice_data/portaudio-binaries"))
except Exception as exc:
    print(f"[tingxie-onefile] sounddevice 检查失败：{exc}")

example = ROOT / "config.example.json"
if example.is_file():
    datas.append((str(example), "config.example.json"))

hiddenimports = (
    collect_submodules("faster_whisper")
    + collect_submodules("ctranslate2")
    + ["onnxruntime", "av", "sounddevice", "cffi"]
)
datas += collect_data_files("faster_whisper", include_py_files=False)

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "setuptools", "pip", "flask", "waitress", "jinja2", "werkzeug"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="听写",
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