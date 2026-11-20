# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把模型、前端资源与运行环境一起装进单目录。

    python -m PyInstaller tingxie.spec --noconfirm

产物：dist/Tingxie-windows-x64/Tingxie.exe + _internal/
"""
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()  # noqa: F821 - SPECPATH 由 PyInstaller 注入
MODEL_DIR = ROOT / "models" / "whisper-base"

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
]
if MODEL_DIR.is_dir():
    datas.append((str(MODEL_DIR), "models/whisper-base"))

# 全局听写用的 PortAudio DLL 必须落在 sounddevice 期望的相对路径上
try:
    _spec = importlib.util.find_spec("sounddevice")
    if _spec and _spec.origin:
        portaudio = Path(_spec.origin).parent / "_sounddevice_data" / "portaudio-binaries"
        if portaudio.is_dir():
            datas.append((str(portaudio), "_sounddevice_data/portaudio-binaries"))
        else:
            print(f"[tingxie.spec] 未找到 PortAudio 目录：{portaudio}")
    else:
        print("[tingxie.spec] 未安装 sounddevice，全局听写将不可用")
except Exception as exc:  # 缺少 sounddevice 时仍可打出纯网页版
    print(f"[tingxie.spec] sounddevice 检查失败：{exc}")

# faster-whisper 运行时按需导入 ctranslate2 / tokenizers / onnxruntime(VAD)
hiddenimports = (
    collect_submodules("faster_whisper")
    + collect_submodules("ctranslate2")
    + ["onnxruntime", "av", "waitress", "sounddevice", "cffi"]
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
    excludes=["tkinter", "pytest", "setuptools", "pip", "httpcore2", "httpx2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Tingxie",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Tingxie-windows-x64",
)