"""Tingxie launcher: serve the local web UI on loopback and open the browser."""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from asr import AsrRouter, load_config
from transcriber import DEFAULT_MODEL_DIR, OfflineTranscriber
from webapp import JobManager, create_app

BANNER = "听写 · 本地语音转文字（完全离线）"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _workspace() -> Path:
    """Temporary workspace for uploads; removed when the process exits."""
    from transcriber import _bundle_root  # local import keeps startup cheap

    base = Path(tempfile.gettempdir()) / "tingxie"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--dictate" in raw:
        # 全局听写模式：侧键触发，识别结果直接上屏，不开浏览器
        from dictation import main as dictation_main

        return dictation_main([item for item in raw if item != "--dictate"])

    parser = argparse.ArgumentParser(description="听写 · 本地离线语音转文字")
    parser.add_argument("--port", type=int, default=0, help="固定端口，默认自动选择空闲端口")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--debug", action="store_true", help="使用 Flask 开发服务器并输出调试日志")
    parser.add_argument("--model", default=str(DEFAULT_MODEL_DIR), help="whisper-base 模型目录")
    parser.add_argument("--asr", default="", choices=["", "auto", "local", "online"],
                        help="识别引擎：local 离线 / online 云端 / auto 自动（默认按 config.json）")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 EXE 同目录的 config.json）")
    args = parser.parse_args(argv)

    model_dir = Path(args.model).resolve()
    config = load_config(args.config)
    engine = AsrRouter(OfflineTranscriber(model_dir), config, mode=args.asr or None)
    manager = JobManager(engine, _workspace())
    server_holder: dict[str, object] = {}

    def shutdown() -> None:
        server = server_holder.get("server")
        if server is not None:
            try:
                server.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        os._exit(0)

    app = create_app(manager, shutdown)
    port = args.port or _free_port()
    url = f"http://127.0.0.1:{port}/"

    info = engine.describe()
    print(BANNER)
    print(f"模型目录：{model_dir}")
    print(
        "识别引擎：{}（本地{} / 云端{}）".format(
            info["mode"],
            "就绪" if info["local_ready"] else "不可用",
            ("已配置 " + (info["online_host"] or "")) if info["online_ready"] else "未配置",
        )
    )
    print(f"可用状态：{'就绪' if engine.model_ready else '不可用（检查 models/ 或 config.json）'}")
    print(f"访问地址：{url}")
    print("关闭此窗口或按 Ctrl+C 结束程序。\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    if args.debug:
        app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
        return 0

    from waitress import create_server

    server = create_server(app, host="127.0.0.1", port=port, threads=4, clear_untrusted_proxy_headers=True)
    server_holder["server"] = server
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())