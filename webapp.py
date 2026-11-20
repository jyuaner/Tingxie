"""Loopback-only Flask API and an in-memory, single-job background worker."""
from __future__ import annotations

import copy
import hmac
import os
import re
import secrets
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import BinaryIO, Callable

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from transcriber import LANGUAGES, ModelNotReadyError

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
#: Anything a browser adds around a 200 MiB file must still fit the request.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
AUDIO_EXTENSIONS = frozenset(
    {".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".webm", ".aac", ".wma", ".opus"}
)

_APP_TOKEN = secrets.token_urlsafe(32)
_LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1)(?::([0-9]{1,5}))?")
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'"
)


class BusyError(RuntimeError):
    """An upload, transcription, or shutdown already owns the single slot."""


class UploadTooLargeError(ValueError):
    """The streamed upload crossed ``MAX_UPLOAD_BYTES``."""


def _failure_message(exc: BaseException) -> str:
    detail = " ".join(str(exc).split())
    if not detail:
        return "转写失败，请检查音频或重新启动程序。"
    return f"转写失败，请检查音频或重新启动程序。详情：{detail[:300]}"


class JobManager:
    """Retain one in-memory job; terminal states imply temporary-file cleanup."""

    def __init__(self, engine, temp_dir: str | os.PathLike[str]) -> None:
        self.engine = engine
        self.temp_dir = Path(temp_dir).resolve()
        self._lock = threading.Lock()
        self._latest: dict | None = None
        self._busy = False
        self._stopping = False

    @property
    def model_ready(self) -> bool:
        return bool(self.engine.model_ready)

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def latest_job(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._latest)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            if self._latest and self._latest["id"] == job_id:
                return copy.deepcopy(self._latest)
            return None

    def begin_shutdown(self) -> None:
        with self._lock:
            if self._busy:
                raise BusyError("任务正在处理中，请等待完成后再退出。")
            self._stopping = True

    def submit(self, stream: BinaryIO, language: str, filename: str) -> str:
        if language not in LANGUAGES:
            raise ValueError("语言仅支持中文（zh）、英语（en）或自动检测（auto）。")
        display_name = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
        extension = Path(display_name).suffix.lower()
        if not display_name or extension not in AUDIO_EXTENSIONS:
            raise ValueError(
                "请选择支持的音频文件：WAV、MP3、M4A、MP4、FLAC、OGG、WEBM、AAC、WMA 或 OPUS。"
            )

        with self._lock:
            if self._busy or self._stopping:
                raise BusyError("已有任务正在处理或程序正在退出，请稍后重试。")
            if not self.model_ready:
                raise ModelNotReadyError(
                    "离线模型不完整，请重新解压包含 models/whisper-base 的完整程序包。"
                )
            self._busy = True

        path: Path | None = None
        job_id: str | None = None
        try:
            fd, name = tempfile.mkstemp(
                prefix="offline-stt-", suffix=extension, dir=self.temp_dir
            )
            path = Path(name)
            with os.fdopen(fd, "wb") as target:
                size = 0
                while True:
                    chunk = stream.read(min(1024 * 1024, MAX_UPLOAD_BYTES - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise UploadTooLargeError("音频文件超过 200 MiB，请压缩或拆分后重试。")
                    target.write(chunk)
                if size == 0:
                    raise ValueError("音频文件为空，请重新录音或选择有效的音频文件。")

            job_id = uuid.uuid4().hex
            with self._lock:
                self._latest = {
                    "id": job_id,
                    "state": "queued",
                    "stage": "queued",
                    "progress": 0,
                    "text": "",
                    "segments": [],
                    "duration": 0.0,
                    "language": language,
                    "error": None,
                    "filename": display_name[:255],
                }
            worker = threading.Thread(
                target=self._run,
                args=(job_id, path, language),
                name="offline-transcriber",
                daemon=True,
            )
            worker.start()
            return job_id
        except BaseException as exc:
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock:
                self._busy = False
                if job_id is not None and self._latest:
                    self._latest.update(
                        {"state": "failed", "stage": "failed", "error": _failure_message(exc)}
                    )
            raise

    def _run(self, job_id: str, path: Path, language: str) -> None:
        result: dict | None = None
        error: str | None = None

        def on_update(update: dict) -> None:
            with self._lock:
                if not self._latest or self._latest["id"] != job_id:
                    return
                cleaned = {}
                for key, value in update.items():
                    cleaned[key] = min(99, max(0, int(value))) if key == "progress" else value
                self._latest.update(cleaned)

        with self._lock:
            if self._latest and self._latest["id"] == job_id:
                self._latest.update({"state": "running", "stage": "decoding"})

        try:
            result = self.engine.transcribe(path, language, on_update)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the UI as text
            error = _failure_message(exc)

        try:
            path.unlink(missing_ok=True)
        except OSError:
            error = "临时音频清理失败，请关闭程序后清理系统临时目录，并检查目录权限。"

        with self._lock:
            if self._latest and self._latest["id"] == job_id:
                if error is None and result is not None:
                    self._latest.update(result)
                    self._latest.update(
                        {"state": "completed", "stage": "completed", "progress": 100, "error": None}
                    )
                else:
                    self._latest.update(
                        {"state": "failed", "stage": "failed", "error": error or "转写失败。"}
                    )
            self._busy = False


def create_app(manager: JobManager, shutdown_callback: Callable[[], None] | None = None) -> Flask:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app = Flask(
        __name__,
        template_folder=str(base / "templates"),
        static_folder=str(base / "static"),
    )
    app.json.ensure_ascii = False
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    def json_error(message: str, status: int):
        return jsonify({"error": message}), status

    @app.before_request
    def protect_local_app():
        host = request.environ.get("HTTP_HOST", "")
        match = _LOCAL_HOST.fullmatch(host)
        if not match or (match.group(1) is not None and not 1 <= int(match.group(1)) <= 65535):
            return json_error("仅允许通过 localhost 或 127.0.0.1 访问本机程序。", 403)
        origin = request.headers.get("Origin")
        if origin is not None and origin != request.host_url.rstrip("/"):
            return json_error("已拒绝跨来源请求，请从程序打开的本机页面操作。", 403)
        if request.path.startswith("/api/"):
            supplied = request.headers.get("X-App-Token", "").encode("utf-8")
            if not hmac.compare_digest(supplied, _APP_TOKEN.encode("ascii")):
                return json_error("请求凭证无效，请刷新本机程序页面后重试。", 403)
        return None

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/") or response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        messages = {
            400: "请求格式无效，请重新选择音频文件后重试。",
            403: "请求被拒绝，请从本机程序页面操作。",
            404: "未找到该任务或页面，程序只保留最近一次任务。",
            405: "请求方法不支持，请从本机程序页面操作。",
            413: "上传内容过大：音频最多 200 MiB，含表单的整个请求最多 201 MiB。",
        }
        return json_error(messages.get(exc.code or 500, "请求无法处理，请稍后重试。"), exc.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        app.logger.exception("Local application request failed")
        return json_error("程序处理请求失败，请重试或重新启动程序。", 500)

    @app.get("/")
    def index():
        return render_template("index.html", csrf_token=_APP_TOKEN)

    @app.get("/api/info")
    def info():
        return jsonify(
            model="Whisper Base",
            offline=True,
            max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
            max_audio_minutes=60,
            model_ready=manager.model_ready,
            job=manager.latest_job(),
        )

    @app.post("/api/transcriptions")
    def transcriptions():
        upload = request.files.get("audio")
        if upload is None or not upload.filename:
            return json_error("请选择音频文件或先完成录音。", 400)
        language = request.form.get("language", "auto")
        try:
            job_id = manager.submit(upload.stream, language, filename=upload.filename)
        except BusyError as exc:
            return json_error(str(exc), 409)
        except ModelNotReadyError as exc:
            return json_error(str(exc), 503)
        except UploadTooLargeError as exc:
            return json_error(str(exc), 413)
        except ValueError as exc:
            return json_error(str(exc), 400)
        return jsonify(id=job_id), 202

    @app.get("/api/transcriptions/<job_id>")
    def transcription(job_id: str):
        job = manager.get_job(job_id)
        if job is None:
            return json_error("未找到该任务，程序只保留最近一次任务。", 404)
        return jsonify(job)

    @app.post("/api/shutdown")
    def shutdown():
        try:
            manager.begin_shutdown()
        except BusyError as exc:
            return json_error(str(exc), 409)
        if shutdown_callback is not None:
            timer = threading.Timer(0.25, shutdown_callback)
            timer.daemon = True
            timer.start()
        return jsonify(ok=True)

    return app