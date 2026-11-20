"""听写 · 全局语音输入（唯一入口）。

双击 EXE（或运行本文件）就是全局听写：按一下触发键开始录音，再按一下停止，
识别结果直接上屏。没有网页、没有浏览器、没有服务端口。

常用参数见 ``python app.py --help``，或 ``--list-keys`` 查看可用触发键。
"""
from __future__ import annotations

import sys

from dictation import main as dictation_main


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # 老命令行里的 --dictate 仍然接受，方便沿用脚本
    return dictation_main([item for item in raw if item != "--dictate"])


if __name__ == "__main__":
    sys.exit(main())