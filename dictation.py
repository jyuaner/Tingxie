"""全局听写：按一下鼠标侧键开始录音，再按一下停止，识别结果直接打进当前窗口。

    python dictation.py                 # 默认鼠标侧键 XBUTTON1（后退键）
    python dictation.py --button x2     # 换成 XBUTTON2（前进键）
    python dictation.py --button f9     # 也可以换成键盘键
    python dictation.py --probe         # 诊断：打印你按的任何键/鼠标键

识别完全在本机 CPU 上完成，音频只在内存里，不落盘、不外发。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
import wave
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import numpy as np

from transcriber import DEFAULT_MODEL_DIR, SAMPLE_RATE, OfflineTranscriber

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- Win32 常量
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_MOUSEMOVE = 0x0200
WM_XBUTTONDOWN = 0x020B
WM_MBUTTONDOWN = 0x0207
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
XBUTTON1, XBUTTON2 = 1, 2
LLMHF_INJECTED = 0x00000001
LLKHF_INJECTED = 0x00000010
VK_ESCAPE = 0x1B
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_MOVE = 0x0001
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

KEY_NAMES = {
    "scroll": 0x91, "pause": 0x13, "capslock": 0x14, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F,
    "apps": 0x5D, "ralt": 0xA5, "rctrl": 0xA3,
}


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)

# 64 位下必须声明 restype，否则句柄会被截断成 int，GlobalLock 直接崩
user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = (wintypes.HANDLE,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wintypes.HANDLE,)
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE


# ---------------------------------------------------------------- 声音提示
def beep(freq: int, ms: int = 90) -> None:
    try:
        import winsound

        winsound.Beep(freq, ms)
    except Exception:
        pass


def tone_start() -> None:
    threading.Thread(target=lambda: (beep(880, 70), beep(1180, 90)), daemon=True).start()


def tone_stop() -> None:
    threading.Thread(target=lambda: (beep(760, 70), beep(520, 90)), daemon=True).start()


def tone_done() -> None:
    threading.Thread(target=lambda: (beep(1040, 60), beep(1320, 80)), daemon=True).start()


def tone_error() -> None:
    threading.Thread(target=lambda: (beep(420, 140), beep(300, 180)), daemon=True).start()


# ---------------------------------------------------------------- 剪贴板 / 注入
def _open_clipboard(retries: int = 12) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def get_clipboard_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("padding", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_key(vk: int, up: bool) -> None:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL

HOTKEY_ID = 0x7E51


def inject_xbutton(button: int = XBUTTON1) -> None:
    """自检用：合成一次侧键按下/抬起。"""
    for flags in (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP):
        event = INPUT(type=INPUT_MOUSE)
        event.u.mi = MOUSEINPUT(dx=0, dy=0, mouseData=button, dwFlags=flags, time=0, dwExtraInfo=None)
        user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        time.sleep(0.05)


def inject_mouse_move(back: bool = False) -> None:
    event = INPUT(type=INPUT_MOUSE)
    event.u.mi = MOUSEINPUT(dx=-1 if back else 1, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_MOVE,
                            time=0, dwExtraInfo=None)
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))


def paste_text(text: str, restore_clipboard: bool = True, delay: float = 0.35) -> bool:
    """Ctrl+V 上屏：剪贴板方式对中文、标点、长文本最稳。"""
    previous = get_clipboard_text() if restore_clipboard else None
    if not set_clipboard_text(text):
        return False
    time.sleep(0.02)
    _send_key(0x11, False)  # Ctrl
    _send_key(0x56, False)  # V
    _send_key(0x56, True)
    _send_key(0x11, True)
    if restore_clipboard and previous is not None:
        time.sleep(delay)
        set_clipboard_text(previous)
    return True


def type_text(text: str) -> bool:
    """逐字 Unicode 注入：少数屏蔽粘贴的窗口（部分终端）用它兜底。"""
    for ch in text:
        for down in (False, True):
            event = INPUT(type=INPUT_KEYBOARD)
            flags = 0x0004 | (KEYEVENTF_KEYUP if down else 0)  # KEYEVENTF_UNICODE
            event.u.ki = KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=flags, time=0, dwExtraInfo=None)
            user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        time.sleep(0.002)
    return True


# ---------------------------------------------------------------- 录音
class Recorder:
    """内存录音，统一输出 16 kHz 单声道 float32，停止后直接交给识别。"""

    def __init__(self, samplerate: int = SAMPLE_RATE, device=None, max_seconds: float = 120.0):
        self.samplerate = samplerate
        self.device = device
        self.max_seconds = max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._started = 0.0
        self._capture_rate = samplerate
        self._lock = threading.Lock()
        self.overflow = False

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001 - PortAudio 回调
        if status:
            self.overflow = True
        with self._lock:
            self._chunks.append(indata.copy())

    def start(self) -> None:
        import sounddevice as sd

        try:
            device_rate = int(sd.query_devices(self.device)["default_samplerate"] or self.samplerate)
        except Exception:
            device_rate = self.samplerate
        rates = [self.samplerate] + ([device_rate] if device_rate != self.samplerate else [])
        last_error: Exception | None = None
        for rate in rates:
            stream = None
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    callback=self._callback,
                    blocksize=0,
                    device=self.device,
                )
                stream.start()
            except Exception as exc:  # 有些声卡只接受原生采样率（多为 48 kHz）
                last_error = exc
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                continue
            with self._lock:
                self._chunks = []
            self._stream = stream
            self._capture_rate = int(stream.samplerate)
            self.overflow = False
            self._started = time.time()
            return
        raise last_error or RuntimeError("没有可用的录音设备")

    def stop(self) -> np.ndarray:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(chunks).reshape(-1).astype(np.float32)
        if self._capture_rate != self.samplerate and len(audio):
            target = int(len(audio) * self.samplerate / self._capture_rate)
            index = np.linspace(0, len(audio) - 1, target).astype(np.int32)
            audio = audio[index]
        return audio

    @property
    def elapsed(self) -> float:
        return time.time() - self._started if self._started else 0.0


def wav_to_array(path: str | os.PathLike[str]) -> np.ndarray:
    """测试用：把 16-bit PCM WAV 直接读成 float32 数组（跳过 PyAV）。"""
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
    if width != 2:
        raise ValueError("测试 WAV 需为 16-bit PCM")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        import math

        ratio = SAMPLE_RATE / rate
        target = int(len(audio) * ratio)
        idx = np.linspace(0, len(audio) - 1, target).astype(np.int32)
        audio = audio[idx]
    return audio.astype(np.float32)


# ---------------------------------------------------------------- 主逻辑
class Dictation:
    def __init__(self, args) -> None:
        self.args = args
        self.engine = OfflineTranscriber(Path(args.model))
        self.recorder = Recorder(device=args.device, max_seconds=args.max_seconds)
        self.state = "idle"  # idle | recording | busy
        self._lock = threading.Lock()
        self._last_trigger = 0.0
        self._target_button = self._parse_button(args.button)
        self._seen_events = 0          # 钩子收到的事件计数（自检用）
        self._selftest_running = False

    # --- 触发源解析
    @staticmethod
    def _parse_button(value: str) -> tuple[str, int]:
        v = value.strip().lower()
        if v in ("x1", "1", "back", "后退"):
            return "mouse", XBUTTON1
        if v in ("x2", "2", "forward", "前进"):
            return "mouse", XBUTTON2
        if v in ("middle", "3", "滚轮", "中键"):
            return "mouse", 0  # 预留：中键走 WM_MBUTTONDOWN 分支
        if v in KEY_NAMES:
            return "key", KEY_NAMES[v]
        raise SystemExit(f"不认识的按键：{value}（可用 x1/x2，或 {', '.join(sorted(KEY_NAMES))}）")

    def log(self, message: str, symbol: str = "·") -> None:
        print(f"[{datetime.now():%H:%M:%S}] {symbol} {message}", flush=True)

    # --- 钩子
    def install(self) -> None:
        kind, code = self._target_button

        def mouse_proc(n_code, w_param, l_param):
            if n_code >= 0:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                self._seen_events += 1
                if self.args.debug_events and w_param in (WM_XBUTTONDOWN, WM_MBUTTONDOWN):
                    print(
                        f"[debug] wparam=0x{w_param:04X} xbutton={(info.mouseData >> 16) & 0xFFFF} "
                        f"injected={bool(info.flags & LLMHF_INJECTED)} target={self._target_button}",
                        flush=True,
                    )
                if kind == "mouse":
                    if code == 0 and w_param == WM_MBUTTONDOWN:
                        pressed = True
                    else:
                        pressed = w_param == WM_XBUTTONDOWN and ((info.mouseData >> 16) & 0xFFFF) == code
                    if pressed and not (info.flags & LLMHF_INJECTED and not self.args.allow_injected):
                        self.trigger()
                        return 1  # 吃掉事件：浏览器不会因此后退/前进
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        def key_proc(n_code, w_param, l_param):
            if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if info.flags & LLKHF_INJECTED and not self.args.allow_injected:
                    return user32.CallNextHookEx(None, n_code, w_param, l_param)
                if kind == "key" and info.vkCode == code:
                    self.trigger()
                    return 1
                if info.vkCode == VK_ESCAPE and self.state == "recording":
                    self.cancel()
                    return 1
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._mouse_proc = HOOKPROC(mouse_proc)
        self._key_proc = HOOKPROC(key_proc)
        self._hooks = []
        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc, None, 0)
        if not hook:
            # 有些安全软件会拦钩子；不退出，交给 --hotkey / 自动回退处理
            self.log(f"鼠标钩子安装失败（错误码 {ctypes.get_last_error()}）", "✗")
            return False
        self._hooks.append(hook)
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._key_proc, None, 0)
        if hook:
            self._hooks.append(hook)
        else:
            self.log("键盘钩子安装失败，Esc 取消不可用（不影响主流程）", "!")
        return True

    def check_hook(self, timeout: float = 1.2) -> bool:
        """启动自检：合成一次 1 像素的鼠标移动，确认钩子真的能收到事件。

        只发移动事件，不会在别的窗口里触发点击或翻页。
        """
        self._selftest_running = True
        baseline = self._seen_events
        try:
            inject_mouse_move()
            inject_mouse_move(back=True)
            msg = wintypes.MSG()
            deadline = time.time() + timeout
            while time.time() < deadline and self._seen_events == baseline:
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.01)
            return self._seen_events > baseline
        finally:
            self._selftest_running = False

    def run_loop(self) -> None:
        msg = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                self.trigger()
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def register_hotkey(self) -> None:
        """可选的备用触发键：不依赖鼠标钩子，注册失败只提示不退出。"""
        if not self.args.hotkey:
            return
        try:
            modifiers, vk = parse_hotkey(self.args.hotkey)
        except ValueError as exc:
            self.log(str(exc), "!")
            return
        if user32.RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, vk):
            self._hotkey_registered = True
            self.log(f"备用快捷键已启用：{self.args.hotkey}", "·")
        else:
            self.log(f"注册快捷键 {self.args.hotkey} 失败，可能已被其他程序占用", "!")

    # --- 状态机
    def trigger(self) -> None:
        if self._selftest_running:  # 忽略自己合成的事件
            return
        now = time.time()
        if now - self._last_trigger < 0.25:
            return
        self._last_trigger = now
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self.state == "idle":
                self.start_recording()
            elif self.state == "recording":
                self.stop_recording()
            else:
                tone_error()
                self.log("上一段还在识别，稍等一下", "…")
        finally:
            self._lock.release()

    def start_recording(self) -> None:
        try:
            self.recorder.start()
        except Exception as exc:
            tone_error()
            self.log(f"录音启动失败：{exc}", "✗")
            return
        self.state = "recording"
        self._auto_stop = threading.Timer(self.args.max_seconds, self._auto_stop_fire)
        self._auto_stop.daemon = True
        self._auto_stop.start()
        tone_start()
        self.log("开始录音…（再按一次停止，Esc 取消）", "●")

    def _auto_stop_fire(self) -> None:
        if self.state != "recording":
            return
        self.log(f"已到单次上限 {self.args.max_seconds:.0f}s，自动停止", "!")
        self.stop_recording()

    def cancel(self) -> None:
        if self.state != "recording":
            return
        self._stop_timer()
        self.recorder.stop()
        self.state = "idle"
        tone_error()
        self.log("已取消", "✗")

    def _stop_timer(self) -> None:
        timer = getattr(self, "_auto_stop", None)
        if timer is not None:
            timer.cancel()
            self._auto_stop = None

    def stop_recording(self) -> None:
        self._stop_timer()
        audio = self.recorder.stop()
        limit = int(self.args.max_seconds * SAMPLE_RATE)
        if len(audio) > limit:
            audio = audio[:limit]
        seconds = len(audio) / SAMPLE_RATE
        tone_stop()
        self.state = "busy"
        if seconds < self.args.min_seconds:
            self.state = "idle"
            tone_error()
            self.log(f"太短了（{seconds:.2f}s），已忽略", "✗")
            return
        self.log(f"录音 {seconds:.1f}s，识别中…", "…")
        threading.Thread(target=self._transcribe_and_type, args=(audio,), daemon=True).start()

    def _transcribe_and_type(self, audio: np.ndarray) -> None:
        started = time.time()
        try:
            result = self.engine.transcribe_array(audio, self.args.language)
            text = (result.get("text") or "").strip()
            elapsed = time.time() - started
            if not text:
                tone_error()
                self.log(f"没听到语音（{elapsed:.1f}s）", "✗")
                return
            if self.args.no_paste:
                self.log(f"识别结果（{elapsed:.1f}s，未上屏）：{text}", "✓")
            else:
                ok = type_text(text) if self.args.type_mode else paste_text(
                    text, restore_clipboard=not self.args.keep_clipboard
                )
                if ok:
                    tone_done()
                    self.log(f"{len(text)} 字 / {elapsed:.1f}s → {text}", "✓")
                else:
                    tone_error()
                    self.log("上屏失败，文字已放到剪贴板，可手动 Ctrl+V", "✗")
        except Exception as exc:  # noqa: BLE001 - 直接告诉用户原因
            tone_error()
            self.log(f"识别失败：{exc}", "✗")
        finally:
            self.state = "idle"
            if self.args.once:
                self.shutdown()

    def shutdown(self) -> None:
        if getattr(self, "_hotkey_registered", False):
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._hotkey_registered = False
        for hook in getattr(self, "_hooks", []):
            user32.UnhookWindowsHookEx(hook)
        user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), WM_QUIT, 0, 0)

    def preload(self) -> None:
        if not self.engine.model_ready:
            self.log("模型不完整，请检查 models/whisper-base", "✗")
            return
        try:
            started = time.time()
            self.engine.ensure_model_ready()
            self.engine._load_model()
            self.log(f"模型已预热（{time.time() - started:.1f}s）", "·")
        except Exception as exc:  # noqa: BLE001
            self.log(f"模型预热失败：{exc}", "!")


def probe(duration: float = 30.0) -> None:
    """把收到的每个鼠标/键盘事件打出来，用来确认侧键到底发的什么。"""
    seen: list[str] = []

    def mouse_proc(n_code, w_param, l_param):
        if n_code >= 0 and w_param in (0x0201, 0x0202, 0x0204, 0x0205, WM_XBUTTONDOWN, 0x020C, 0x0207, 0x0208):
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            names = {
                0x0201: f"左键按下", 0x0202: "左键抬起",
                0x0204: "右键按下", 0x0205: "右键抬起",
                0x0207: "中键按下", 0x0208: "中键抬起",
                WM_XBUTTONDOWN: f"侧键按下 XBUTTON{(info.mouseData >> 16) & 0xFFFF}",
                0x020C: f"侧键抬起 XBUTTON{(info.mouseData >> 16) & 0xFFFF}",
            }
            label = names.get(w_param, hex(w_param))
            if label not in seen:
                seen.append(label)
                print(f"  mouse: {label}    (injected={bool(info.flags & LLMHF_INJECTED)})", flush=True)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def key_proc(n_code, w_param, l_param):
        if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            label = f"key: vk=0x{info.vkCode:02X}"
            if label not in seen:
                seen.append(label)
                print(f"  {label}    (injected={bool(info.flags & LLKHF_INJECTED)})", flush=True)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    mouse_cb, key_cb = HOOKPROC(mouse_proc), HOOKPROC(key_proc)
    hooks = [
        user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_cb, None, 0),
        user32.SetWindowsHookExW(WH_KEYBOARD_LL, key_cb, None, 0),
    ]
    if not hooks[0]:
        raise SystemExit("钩子安装失败")
    print(f"诊断模式：{duration:.0f} 秒内按下你想用的那个键（建议按鼠标侧键、键盘 F 区各一次）", flush=True)
    print("看到 `侧键按下 XBUTTON1/XBUTTON2` 就用 --button x1 / x2；看到 `key: vk=0x..` 就用 --button f9 之类。", flush=True)
    deadline = time.time() + duration
    msg = wintypes.MSG()
    while time.time() < deadline:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)
    for hook in hooks:
        if hook:
            user32.UnhookWindowsHookEx(hook)
    print("诊断结束" + ("（没收到任何按键）" if not seen else ""))


def parse_hotkey(value: str) -> tuple[int, int]:
    """把 "ctrl+alt+d" / "f9" 解析成 (修饰键, 虚拟键码)。"""
    names = {
        "space": 0x20, "enter": 0x0D, "tab": 0x09, "backspace": 0x08, "esc": 0x1B,
        "escape": 0x1B, "pause": 0x13, "scroll": 0x91, "capslock": 0x14,
        "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "`": 0xC0, "-": 0xBD, "=": 0xBB, ",": 0xBC, ".": 0xBE, "/": 0xBF,
        ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    }
    names.update({f"f{i}": 0x6F + i for i in range(1, 25)})
    names.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})
    names.update({str(d): 0x30 + d for d in range(10)})

    mods = 0
    vk = None
    for part in [p.strip().lower() for p in value.split("+") if p.strip()]:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "super", "meta"):
            mods |= MOD_WIN
        elif part in names:
            vk = names[part]
        else:
            raise ValueError(f"不认识的快捷键片段：{part}")
    if vk is None:
        raise ValueError("快捷键必须以一个键结尾，例如 ctrl+alt+d")
    return mods, vk


def selftest(duration: float = 2.5) -> int:
    """不依赖用户输入的自检：本进程自己合成一次侧键，看钩子能否收到。"""
    seen: list[int] = []

    def proc(n_code, w_param, l_param):
        if n_code >= 0:
            seen.append(int(w_param))
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    callback = HOOKPROC(proc)
    hook = user32.SetWindowsHookExW(WH_MOUSE_LL, callback, None, 0)
    print(f"钩子安装：{'成功' if hook else '失败'}", flush=True)
    if not hook:
        print("这个进程装不上全局鼠标钩子，侧键方案不可用（可改用 --hotkey）。", flush=True)
        return 2
    time.sleep(0.15)
    inject_mouse_move()
    inject_xbutton(XBUTTON1)
    msg = wintypes.MSG()
    deadline = time.time() + duration
    while time.time() < deadline:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)
    user32.UnhookWindowsHookEx(hook)
    if WM_XBUTTONDOWN in seen or 0x020C in seen:
        print(f"自检通过：收到 {len(seen)} 个鼠标事件（含侧键），侧键方案可用。", flush=True)
        return 0
    print(f"自检失败：只收到 {len(seen)} 个鼠标事件 {[hex(w) for w in seen][:8]}，其中没有侧键。", flush=True)
    print("可以改用快捷键：--hotkey ctrl+alt+d", flush=True)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全局听写：按一下侧键开始，再按一下停止，文字自动上屏",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--button", default="x1", help="触发键：x1/x2（鼠标侧键）或 f9/capslock/scroll 等")
    parser.add_argument("--language", default="zh", choices=["zh", "en", "auto"], help="识别语言")
    parser.add_argument("--model", default=str(DEFAULT_MODEL_DIR), help="whisper-base 模型目录")
    parser.add_argument("--device", type=int, default=None, help="录音设备序号（见 --devices）")
    parser.add_argument("--devices", action="store_true", help="列出录音设备后退出")
    parser.add_argument("--probe", action="store_true", help="诊断模式：打印按下的键")
    parser.add_argument("--type", dest="type_mode", action="store_true", help="逐字输入而不是粘贴")
    parser.add_argument("--keep-clipboard", action="store_true", help="粘贴后保留识别文字在剪贴板")
    parser.add_argument("--no-paste", action="store_true", help="只打印结果，不注入任何窗口")
    parser.add_argument("--max-seconds", type=float, default=120.0, help="单次录音上限（秒）")
    parser.add_argument("--min-seconds", type=float, default=0.35, help="短于该时长视为误触")
    parser.add_argument("--no-preload", action="store_true", help="启动时不预热模型")
    parser.add_argument("--once", action="store_true", help="识别一次后退出（测试用）")
    parser.add_argument("--wav", default=None, help="测试用：用固定 WAV 代替麦克风")
    parser.add_argument("--allow-injected", action="store_true", help="调试用：接受模拟注入的按键")
    parser.add_argument("--silent", action="store_true", help="关闭提示音")
    parser.add_argument("--debug-events", action="store_true", help="打印收到的每个鼠标侧键事件（排查用）")
    parser.add_argument("--selftest", action="store_true", help="自检：自己合成一次侧键，检查钩子是否可用")
    parser.add_argument("--hotkey", default="", help="备用快捷键（钩子失效时用），例如 ctrl+alt+d")
    parser.add_argument("--no-autofallback", action="store_true", help="启动时不做钩子自检，也不自动启用备用快捷键")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:  # 让 cmd 里正确显示中文
        kernel32.SetConsoleOutputCP(65001)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)

    if args.devices:
        import sounddevice as sd

        for index, device in enumerate(sd.query_devices()):
            if device["max_input_channels"] > 0:
                mark = "*" if index == sd.default.device[0] else " "
                print(f"{mark}{index:3d}  {device['name']}  in={device['max_input_channels']}", flush=True)
        return 0

    if args.probe:
        print("进入诊断模式…", flush=True)
        probe()
        return 0

    if args.selftest:
        return selftest()

    if args.silent:
        global beep

        beep = lambda *a, **k: None  # noqa: E731

    app = Dictation(args)
    kind, code = app._target_button
    label = {XBUTTON1: "鼠标侧键 XBUTTON1（后退键）", XBUTTON2: "鼠标侧键 XBUTTON2（前进键）"}.get(
        code, f"{kind} {code:#04x}"
    )
    print("听写 · 全局语音输入", flush=True)
    print(f"触发键：{label}   语言：{args.language}", flush=True)
    if args.hotkey:
        print(f"备用快捷键：{args.hotkey}", flush=True)
    print(f"输出方式：{'逐字输入' if args.type_mode else '粘贴（Ctrl+V）'}", flush=True)
    print("按一下开始录音，再按一下停止；录音时按 Esc 取消；关闭窗口退出。\n", flush=True)

    if not args.no_preload:
        threading.Thread(target=app.preload, daemon=True).start()

    if args.wav:
        audio = wav_to_array(args.wav)
        app.log(f"测试模式：使用 {Path(args.wav).name}（{len(audio) / SAMPLE_RATE:.1f}s）", "·")
        app.state = "busy"
        app._transcribe_and_type(audio)
        return 0

    # 单实例保护：两个实例会互相抢侧键事件，第二个必须直接退出
    SYNCHRONIZE = 0x00100000
    kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    existing = kernel32.OpenMutexW(SYNCHRONIZE, False, "Local\\TingxieDictation")
    if existing:
        kernel32.CloseHandle(existing)
        print("已有一个听写实例在运行（侧键会被它独占）。请先关闭那个窗口再启动。", flush=True)
        return 1
    instance = kernel32.CreateMutexW(None, False, "Local\\TingxieDictation")
    if not instance:
        print("创建单实例锁失败，仍继续启动。", flush=True)

    hook_ok = app.install()
    if not args.no_autofallback:
        if not hook_ok:
            print("鼠标钩子不可用（可能被安全软件拦截），只能靠快捷键触发", flush=True)
        elif app.check_hook():
            print("钩子自检：通过", flush=True)
        else:
            print("钩子自检：没收到任何鼠标事件，侧键可能不可用", flush=True)
            hook_ok = False
        if not hook_ok and not args.hotkey:
            args.hotkey = "ctrl+alt+d"
            print("已自动改用备用快捷键 ctrl+alt+d（可用 --hotkey 换键）", flush=True)
    if not hook_ok and not args.hotkey:
        print("侧键和快捷键都不可用，无法继续。请加 --hotkey ctrl+alt+d 再试。", flush=True)
        return 2
    app.register_hotkey()
    try:
        import signal

        signal.signal(signal.SIGINT, lambda *_: app.shutdown())
        signal.signal(signal.SIGBREAK, lambda *_: app.shutdown())
    except Exception:
        pass
    try:
        app.run_loop()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())