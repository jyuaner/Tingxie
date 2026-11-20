"""CPU-only, local-model speech recognition with bounded audio decoding."""
from __future__ import annotations

import os

# Set before faster-whisper / huggingface_hub are imported: the shipped build must
# never attempt a network lookup, even when the model directory is incomplete.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import copy  # noqa: E402
import io  # noqa: E402
import sys  # noqa: E402
from fractions import Fraction  # noqa: E402
from pathlib import Path  # noqa: E402
from threading import Lock  # noqa: E402
from typing import Callable  # noqa: E402

SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 60 * 60
LANGUAGES = frozenset({"zh", "en", "auto"})
REQUIRED_MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")

#: 中文提示词，逼模型输出简体中文并补全标点。
_ZH_PROMPT = "以下是普通话内容，请使用简体中文和标点符号。"


def _bundle_root() -> Path:
    """Directory holding bundled data, both in-source and inside a PyInstaller build."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(__file__).resolve().parent


DEFAULT_MODEL_DIR = _bundle_root() / "models" / "whisper-base"


class ModelNotReadyError(RuntimeError):
    """The distribution does not contain a complete local model."""


class _AudioTooLong(ValueError):
    """Internal marker: decoding hit the duration ceiling."""

    def __init__(self) -> None:
        super().__init__("音频时长超过上限（60 分钟），请剪短或拆分后重试。")


def decode_audio(path: str | os.PathLike[str]) -> "object":
    """Decode any supported container to mono 16 kHz float32 in [-1, 1].

    ``protocol_whitelist=pipe`` keeps libav away from nested ``file:``/``http:``
    references, and a hard sample ceiling stops a crafted header from promising
    an unbounded stream.
    """
    import av
    import numpy as np

    max_samples = int(MAX_AUDIO_SECONDS * SAMPLE_RATE)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    sample_count = 0
    source_duration = Fraction(0)

    def too_long() -> None:
        raise _AudioTooLong()

    with io.BytesIO() as raw:

        def append_frame(frame) -> None:
            nonlocal sample_count
            samples = frame.to_ndarray().tobytes()
            sample_count += len(samples) // 2
            if sample_count > max_samples:
                too_long()
            raw.write(samples)

        try:
            with Path(path).open("rb") as source, av.open(
                source, mode="r", options={"protocol_whitelist": "pipe"}
            ) as container:
                for frame in container.decode(audio=0):
                    if not frame.sample_rate:
                        raise ValueError("音频采样率无效，请重新导出 WAV 文件。")
                    source_duration += Fraction(frame.samples, frame.sample_rate)
                    if source_duration > MAX_AUDIO_SECONDS:
                        too_long()
                    frame.pts = None
                    for converted in resampler.resample(frame):
                        append_frame(converted)
                for converted in resampler.resample(None):
                    append_frame(converted)
        except _AudioTooLong:
            raise
        except (av.error.FFmpegError, OSError, ValueError, EOFError, IndexError) as exc:
            raise ValueError(
                "无法读取音频，文件可能损坏或没有音轨，请重新导出为 WAV、MP3 或 M4A 后重试。"
            ) from exc
        finally:
            del resampler

        audio = np.frombuffer(raw.getvalue(), dtype=np.int16).astype(np.float32)
        audio /= 32768.0
        return audio


class OfflineTranscriber:
    """Lazily loaded Whisper model driven entirely from a local directory."""

    def __init__(self, model_dir: str | os.PathLike[str] = DEFAULT_MODEL_DIR) -> None:
        self.model_dir = Path(model_dir).resolve()
        self._model = None
        self._model_lock = Lock()

    def _missing_model_files(self) -> list[str]:
        missing: list[str] = []
        for name in REQUIRED_MODEL_FILES:
            path = self.model_dir / name
            try:
                if not path.is_file() or path.stat().st_size == 0:
                    missing.append(name)
            except OSError:
                missing.append(name)
        return missing

    @property
    def model_ready(self) -> bool:
        return not self._missing_model_files()

    def ensure_model_ready(self) -> None:
        missing = self._missing_model_files()
        if missing:
            raise ModelNotReadyError(
                "离线模型不完整，缺少或无法读取："
                + "、".join(missing)
                + "。请重新解压包含 models/whisper-base 的完整程序包；程序不会联网下载。"
            )

    def _load_model(self):
        with self._model_lock:
            if self._model is None:
                self.ensure_model_ready()
                try:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(
                        str(self.model_dir),
                        device="cpu",
                        compute_type="int8",
                        local_files_only=True,
                        cpu_threads=min(4, max(1, os.cpu_count() or 1)),
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "本地语音模型加载失败，请重新解压完整程序包，并确认内存充足。"
                    ) from exc
        return self._model

    def transcribe(
        self,
        path: str | os.PathLike[str],
        language: str,
        on_update: Callable[[dict], None] | None = None,
    ) -> dict:
        """解码一个音频文件再识别（网页版的入口）。"""
        if language not in LANGUAGES:
            raise ValueError("语言仅支持中文（zh）、英语（en）或自动检测（auto）。")
        self.ensure_model_ready()
        if on_update is not None:
            on_update({"progress": 0, "stage": "decoding", "text": ""})
        audio = decode_audio(Path(path))
        return self.transcribe_array(audio, language, on_update, checked=True)

    def transcribe_array(
        self,
        audio,
        language: str,
        on_update: Callable[[dict], None] | None = None,
        checked: bool = False,
    ) -> dict:
        """识别已经解码好的单声道 16 kHz float32 波形（全局听写走这里，不用落盘）。"""
        if not checked:
            if language not in LANGUAGES:
                raise ValueError("语言仅支持中文（zh）、英语（en）或自动检测（auto）。")
            self.ensure_model_ready()

        segments: list[dict] = []
        text_parts: list[str] = []

        def publish(progress: int, stage: str) -> None:
            if on_update is None:
                return
            on_update(
                {
                    "progress": max(0, min(99, int(progress))),
                    "stage": stage,
                    "text": "".join(text_parts).strip(),
                }
            )

        duration = len(audio) / SAMPLE_RATE
        empty = {"text": "", "segments": [], "duration": duration, "language": language}
        if not len(audio):
            return empty

        publish(1, "analyzing")
        try:
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            vad_options = VadOptions(min_silence_duration_ms=500, min_speech_duration_ms=250)
            speech = get_speech_timestamps(audio, vad_options, sampling_rate=SAMPLE_RATE)
        except Exception as exc:
            raise RuntimeError(
                "本地语音活动检测组件不可用，请重新解压包含全部依赖的程序包。"
            ) from exc
        if not speech:
            return empty

        publish(2, "loading")
        model = self._load_model()
        publish(3, "transcribing")

        generated, info = model.transcribe(
            audio,
            language=None if language == "auto" else language,
            beam_size=3,
            condition_on_previous_text=False,
            initial_prompt=_ZH_PROMPT if language == "zh" else None,
            vad_filter=True,
            vad_parameters=vad_options,
        )
        if info.duration_after_vad == 0:
            return empty

        for segment in generated:
            raw_text = segment.text
            if raw_text.strip():
                segments.append(
                    {
                        "start": float(segment.start),
                        "end": float(segment.end),
                        "text": raw_text.strip(),
                    }
                )
                text_parts.append(raw_text)
            progress = 3 + int(96 * min(1.0, max(0.0, segment.end / duration)))
            publish(progress, "transcribing")

        return {
            "text": "".join(text_parts).strip(),
            "segments": copy.deepcopy(segments),
            "duration": duration,
            "language": info.language,
        }