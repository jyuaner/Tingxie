"""Download the CTranslate2 Whisper Base bundle into models/whisper-base/.

Only needed once when building from source: the shipped offline package already
contains the model. After this script finishes, Tingxie never touches the network.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO = "Systran/faster-whisper-base"
BASE_URL = f"https://huggingface.co/{REPO}/resolve/main"
FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models" / "whisper-base"


def _download(name: str, target: Path) -> None:
    url = f"{BASE_URL}/{name}?download=true"
    print(f"→ {name}")
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1048576:6.1f} / {total / 1048576:.1f} MiB", end="")
    print(f"\r  {target.stat().st_size / 1048576:6.1f} MiB 完成")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载 faster-whisper 的 whisper-base 模型")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    parser.add_argument("--verify", action="store_true", help="下载后打印 SHA256")
    args = parser.parse_args(argv)

    TARGET.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = TARGET / name
        if target.is_file() and target.stat().st_size > 0 and not args.force:
            print(f"✓ 已存在，跳过：{name}")
            continue
        try:
            _download(name, target)
        except Exception as exc:  # noqa: BLE001 - 网络问题需要直白提示
            print(f"\n下载失败（{name}）：{exc}", file=sys.stderr)
            print("可手动从 https://huggingface.co/%s/tree/main 下载四个文件放入 %s" % (REPO, TARGET))
            return 1
        if target.stat().st_size == 0:
            print(f"下载结果为空：{name}", file=sys.stderr)
            return 1

    if args.verify:
        for name in FILES:
            print(f"{_sha256(TARGET / name)}  {name}")

    print(f"\n模型就绪：{TARGET}")
    print("接下来：python app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())