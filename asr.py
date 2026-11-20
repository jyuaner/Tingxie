"""ASR 引擎路由：本地 Whisper（完全离线）与云端 API（联网）两种模式。

设计要点
--------
* 本地：复用 ``transcriber.OfflineTranscriber``，CPU int8，不联网；
* 云端：任何 OpenAI 兼容的 ``/audio/transcriptions`` 服务（OpenAI、Groq、
  SiliconFlow、阿里百炼、自建网关等），只要 base_url + api_key + model；
* ``mode``：``local`` / ``online`` / ``auto``；``auto`` 在有 key 时优先云端，
  失败（超时、401、无网）自动回退本地，并把原因写进结果的 note；
* 云端失败不会让听写整个挂掉 —— 这条链路是给自己用的，宁可慢也不能丢话。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

import numpy as np

from transcriber import SAMPLE_RATE, OfflineTranscriber, decode_audio

MODES = ("auto", "local", "online")
CONFIG_NAME = "config.json"

DEFAULT_CONFIG: dict = {
    "mode": "auto",
    "fallback": True,
    "online": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "whisper-1",
        "timeout": 60,
        "send_language": True,
    },
}


class AsrError(RuntimeError):
    """云端识别失败（网络、鉴权、返回格式）。"""


def app_root() -> Path:
    """打包后是 EXE 所在目录，源码运行时是仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("TINGXIE_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return app_root() / CONFIG_NAME


def load_config(explicit: str | os.PathLike[str] | None = None) -> dict:
    """读配置；文件不存在就用默认值（key 也可用环境变量给）。"""
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = config_path(explicit)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, dict) and isinstance(config.get(key), dict):
                        config[key].update(value)
                    else:
                        config[key] = value
        except Exception as exc:  # 配置写坏了也要能启动
            print(f"[asr] 读取配置失败，使用默认值：{exc}", file=sys.stderr)

    online = config.setdefault("online", {})
    # 环境变量优先，方便不把 key 写进文件
    online["api_key"] = os.environ.get("TINGXIE_API_KEY") or online.get("api_key") or ""
    online["base_url"] = os.environ.get("TINGXIE_BASE_URL") or online.get("base_url") or ""
    online["model"] = os.environ.get("TINGXIE_MODEL") or online.get("model") or "whisper-1"
    if os.environ.get("TINGXIE_MODE"):
        config["mode"] = os.environ["TINGXIE_MODE"]
    return config


def encode_wav(audio: "np.ndarray", sample_rate: int = SAMPLE_RATE) -> bytes:
    """float32 [-1,1] → 16-bit 单声道 WAV 字节。"""
    pcm = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((pcm * 32767.0).astype(np.int16).tobytes())
    return buffer.getvalue()


def build_multipart(fields: dict, filename: str, content: bytes, content_type: str = "audio/wav"):
    """手工拼 multipart/form-data（不引入 requests 依赖）。"""
    boundary = "----tingxie" + uuid.uuid4().hex
    buffer = io.BytesIO()
    for name, value in fields.items():
        buffer.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    buffer.write(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
    )
    buffer.write(content)
    buffer.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return boundary, buffer.getvalue()


def _extract_text(payload: dict) -> str:
    """兼容几种常见返回结构：OpenAI / 一些国内网关。"""
    if not isinstance(payload, dict):
        return ""
    for path in (("text",), ("data", "text"), ("result", "text"), ("data", "result", "text")):
        node = payload
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                node = None
                break
        if isinstance(node, str) and node.strip():
            return node.strip()
    # 少数服务返回 segments 数组
    segments = payload.get("segments") or (payload.get("data") or {}).get("segments")
    if isinstance(segments, list):
        return "".join(str(s.get("text", "")) for s in segments if isinstance(s, dict)).strip()
    return ""


def transcribe_online(audio: "np.ndarray", language: str, online_cfg: dict) -> dict:
    base_url = str(online_cfg.get("base_url") or "").rstrip("/")
    api_key = str(online_cfg.get("api_key") or "")
    model = str(online_cfg.get("model") or "whisper-1")
    timeout = float(online_cfg.get("timeout") or 60)
    if not base_url or not api_key:
        raise AsrError("云端模式未配置 base_url / api_key")

    fields = {"model": model, "response_format": "json"}
    if online_cfg.get("send_language", True) and language in ("zh", "en"):
        fields["language"] = "zh" if language == "zh" else "en"

    wav = encode_wav(audio)
    boundary, body = build_multipart(fields, "audio.wav", wav)
    request = urllib.request.Request(
        f"{base_url}/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "User-Agent": "Tingxie/1.2",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:400].decode("utf-8", "replace")
        raise AsrError(f"云端返回 {exc.code}：{detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise AsrError(f"连不上云端（{exc.reason}）") from exc
    except Exception as exc:  # 超时、解码失败等
        raise AsrError(f"云端请求失败：{exc}") from exc

    text = _extract_text(payload)
    return {
        "text": text,
        "segments": [],
        "duration": len(audio) / SAMPLE_RATE,
        "language": payload.get("language") or language,
        "engine": "online",
        "elapsed": round(time.time() - started, 1),
    }


class AsrRouter:
    """对上层只暴露 transcribe / transcribe_file / describe。"""

    def __init__(self, local: OfflineTranscriber | None, config: dict | None = None,
                 mode: str | None = None, fallback: bool | None = None) -> None:
        self.config = config if config is not None else load_config()
        self.local = local if local is not None else OfflineTranscriber()
        self.mode = (mode or self.config.get("mode") or "auto").lower()
        if self.mode not in MODES:
            self.mode = "auto"
        self.fallback = bool(self.config.get("fallback", True) if fallback is None else fallback)

    # --- 状态
    @property
    def local_ready(self) -> bool:
        return bool(self.local.model_ready)

    @property
    def online_ready(self) -> bool:
        online = self.config.get("online") or {}
        return bool(online.get("api_key")) and bool(online.get("base_url"))

    @property
    def model_ready(self) -> bool:
        """当前模式下是否可用（网页版用它决定按钮是否可点）。"""
        if self.mode == "online":
            return self.online_ready or (self.fallback and self.local_ready)
        if self.mode == "local":
            return self.local_ready
        return self.online_ready or self.local_ready

    def describe(self) -> dict:
        online = self.config.get("online") or {}
        return {
            "mode": self.mode,
            "fallback": self.fallback,
            "local_ready": self.local_ready,
            "online_ready": self.online_ready,
            "online_model": online.get("model") if self.online_ready else None,
            "online_host": (online.get("base_url") or "").split("//")[-1].split("/")[0] or None,
        }

    def warm_up(self) -> None:
        if self.local_ready:
            self.local._load_model()

    # --- 识别
    def _order(self, mode: str | None) -> list[str]:
        chosen = (mode or self.mode).lower()
        if chosen == "online":
            order = ["online"] + (["local"] if self.fallback else [])
        elif chosen == "local":
            order = ["local"]
        else:  # auto
            order = ["online", "local"] if self.online_ready else ["local"]
        return order

    def transcribe(self, audio, language: str, on_update=None, mode: str | None = None) -> dict:
        errors: list[str] = []
        order = self._order(mode)
        usable = [engine for engine in order if self._engine_ready(engine)]
        if not usable:
            if "online" in order:
                raise AsrError(
                    "云端未配置（config.json 里的 online.base_url / api_key），本地模型也不完整"
                )
            raise AsrError("本地模型不完整，请检查 models/whisper-base")

        for index, engine in enumerate(usable):
            try:
                if engine == "online":
                    if on_update:
                        on_update({"progress": 45, "stage": "uploading", "text": ""})
                    result = transcribe_online(audio, language, self.config.get("online") or {})
                else:
                    result = self.local.transcribe_array(audio, language, on_update)
                    result["engine"] = "local"
                if errors:
                    result["note"] = "；".join(errors)
                return result
            except Exception as exc:  # 换下一个引擎
                errors.append(f"{'云端' if engine == 'online' else '本地'}失败：{exc}")
                if index == len(usable) - 1:
                    raise AsrError("；".join(errors)) from exc
        raise AsrError("没有可用的识别引擎")  # pragma: no cover

    def transcribe_file(self, path, language: str, on_update=None, mode: str | None = None) -> dict:
        if on_update:
            on_update({"progress": 0, "stage": "decoding", "text": ""})
        audio = decode_audio(Path(path))
        return self.transcribe(audio, language, on_update, mode=mode)

    def _engine_ready(self, engine: str) -> bool:
        return self.online_ready if engine == "online" else self.local_ready