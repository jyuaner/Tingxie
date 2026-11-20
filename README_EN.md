# Tingxie — offline speech-to-text for Windows

> Turn speech into text on your own machine. Models and runtime are bundled, so even the very first launch works without a network connection.

![Tingxie UI](docs/images/main.png)

Tingxie (听写) is a small desktop tool for Windows 10/11 x64 that records from your microphone or imports an audio file, transcribes it with Whisper Base running on the CPU, and lets you edit, copy or export the result as TXT. No cloud, no account, no GPU, no build step in the UI.

## Features

- **Record or import** — in-browser recording with playback before transcription, plus drag & drop for WAV / MP3 / M4A / MP4 / FLAC / OGG / WEBM / AAC / WMA / OPUS.
- **Global dictation** — press a mouse side button, speak, press again: the transcript is pasted straight into whatever window has focus.
- **Language control** — Chinese (Mandarin), English, or automatic detection.
- **Editable results** — edit inline, copy to clipboard, export UTF-8 TXT (with BOM, so Notepad and Excel open it correctly).
- **Visible progress** — decoding → voice activity detection → model loading → segment-by-segment progress with a real percentage.
- **Nothing left behind** — temporary audio is deleted as soon as the job ends; transcripts live in memory only.
- **Loopback only** — the web server binds `127.0.0.1`, validates `Host` / `Origin` and requires a per-launch token, so neither the LAN nor a random website can drive it.

## Quick start (end users)

1. Download `Tingxie-Windows-x64-offline.zip` from [Releases](../../releases) (~250 MB).
2. **Extract the whole folder** — the EXE needs `_internal/` next to it (model + runtime live there).
3. Double-click `Tingxie.exe`; the browser opens the local UI automatically.
4. Record or import → pick a language → transcribe → edit / copy / export.

## Global dictation (side button)

Type less: **press a mouse side button → speak → press again → the text lands at your cursor** about a second later (WeChat, Word, IDE, browser fields — anything that accepts a paste).

1. Double-click **`听写-全局输入.cmd`** in the extracted folder (or run `Tingxie.exe --dictate`);
2. Press the side button once: rising beeps mean recording started; press again for the falling beeps and transcription;
3. Text is injected with the clipboard + `Ctrl+V`, and your previous clipboard content is restored.

**Button does nothing?** Run `Tingxie.exe --dictate --probe` and press the button once within 30 seconds:

| Output | Use |
| --- | --- |
| `mouse: 侧键按下 XBUTTON1` | `--button x1` (default) |
| `mouse: 侧键按下 XBUTTON2` | `--button x2` |
| `key: vk=0x78` (F9) | `--button f9` |
| nothing | the vendor driver swallowed it — remap it to a key or pick another trigger |

For a hands-off check run `Tingxie.exe --dictate --selftest`: it synthesises a 1-pixel mouse move and reports whether the hook receives events (it never clicks or types into other windows). If it reports a failure, use a hotkey instead: `--dictate --hotkey ctrl+alt+d`. The daemon runs the same self-check at startup and switches to `ctrl+alt+d` automatically when the hook delivers nothing.

Flags: `--language zh|en|auto`, `--type` (type instead of paste), `--keep-clipboard`, `--no-paste` (print only), `--device N` (`--devices` lists inputs), `--max-seconds 120`, `--silent`. Press **Esc** while recording to cancel.

Paste targets the **foreground window**; elevated windows reject injection because of Windows UIPI — the text then stays on the clipboard for a manual `Ctrl+V`.

## Run from source

```powershell
git clone https://github.com/jyuaner/Tingxie.git
cd Tingxie

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python scripts/fetch_model.py    # one-time download of whisper-base (CTranslate2)

python app.py                    # web UI: picks a free port and opens the browser
python app.py --port 8722 --no-browser --debug
python dictation.py              # global dictation daemon
python dictation.py --probe      # identify what your side button actually sends
```

`models/whisper-base/` must contain `model.bin`, `config.json`, `tokenizer.json` and `vocabulary.txt` — see [models/README.md](models/README.md).

## Build the offline package

```powershell
python -m PyInstaller tingxie.spec --noconfirm
# or the wrapper that also zips the result:
pwsh -File scripts/build.ps1
```

Output: `dist/Tingxie-windows-x64/` (`Tingxie.exe` + `_internal/` including the model, `static/`, `templates/`, the PortAudio DLL used by dictation, plus `听写-全局输入.cmd`). Compress that directory to get the redistributable offline bundle.

## Architecture

```
[Global dictation] dictation.py
mouse side button (XBUTTON1/2) -> WH_MOUSE_LL hook -> sounddevice capture in RAM
        | press again
transcriber.transcribe_array() -> clipboard + Ctrl+V into the foreground window
(Esc cancels, beeps give feedback, the button event is swallowed so browsers do not navigate)

[Web UI]
browser (localhost): index.html + app.js + core.mjs + style.css
        | fetch + X-App-Token          | multipart audio
Waitress on 127.0.0.1 <- Flask (webapp.py)
Host/Origin checks - CSP - 201 MiB cap - single-job JobManager (worker thread)
        |
transcriber.py (shared by both paths)
PyAV decode -> mono 16 kHz int16 (hard 3600 s ceiling)
Silero VAD -> faster-whisper Whisper Base (CPU, int8, beam 3)
```

- **Frontend**: plain HTML/CSS/ES modules — no bundler, no framework.
- **Backend**: Flask + Waitress, one job at a time, results kept in memory.
- **Dictation**: Win32 low-level mouse/keyboard hooks via `ctypes` (no third-party hook library) + PortAudio capture in memory; text goes out through the clipboard and `SendInput`, then the clipboard is restored.
- **Inference**: `faster-whisper` on CTranslate2 with `device="cpu"`, `compute_type="int8"`, `cpu_threads=min(4, cpu_count)`; VAD filtering enabled; Chinese runs get a simplified-Chinese punctuation prompt.
- **Packaging**: PyInstaller onedir; model, static assets and the PortAudio DLL are collected as data files.

### HTTP API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/` | Single-page UI, injects the per-launch token |
| GET | `/api/info` | Model name, offline flag, upload limits, readiness, latest job |
| POST | `/api/transcriptions` | `multipart/form-data`: `audio` + `language` (`zh`/`en`/`auto`) → `202 {id}` |
| GET | `/api/transcriptions/<id>` | Snapshot: `state`, `stage`, `progress`, `text`, `segments`, `duration`, `language`, `error` |
| POST | `/api/shutdown` | Graceful stop when idle |

Errors are always `{"error": "..."}` with `400 / 403 / 404 / 409 / 413 / 503`.

## Performance (CPU only)

| Machine | Sample | 10 minutes of audio |
| --- | --- | --- |
| i5-1135G7 (4 threads) | whisper-base int8 | ≈ 1.5–2.5 min |
| R5-5600U (4 threads) | whisper-base int8 | ≈ 1.5–2.5 min |
| i5-8250U | whisper-base int8 | ≈ 3–5 min |
| Low-power Celeron / Pentium | — | noticeably slower; split long files |

Dictation is much cheaper per use: a 10-second utterance usually comes back in 1–2 seconds on the same hardware.

## Limitations

- Windows 10/11 x64 only; older CPUs depend on the instruction set (AVX2 is the safe bet).
- One file at a time in the web UI: **200 MB / 60 minutes** maximum, enforced in both the UI and the server.
- Batch transcription of a finished recording — not real-time streaming. Dictation also waits for the second press before producing text.
- No speaker diarization, no auto summary, no second-pass punctuation model.
- Noisy audio, strong accents and jargon still produce errors; proofread anything important.
- Transcripts are memory-only: export before closing the program.
- Dictation pastes into the foreground window; elevated windows are blocked by UIPI (text stays on the clipboard).

## Privacy

- Recognition runs entirely on the local CPU; the app makes no outbound business requests.
- `HF_HUB_OFFLINE=1` and `local_files_only=True` — a missing model raises an error instead of downloading.
- Web uploads go to the system temp directory and are `unlink`ed when the job ends; dictation audio never touches the disk.
- The web server binds loopback only and rejects requests without the per-launch token.

## FAQ

**The browser did not open.** Check the URL printed in the console (`http://127.0.0.1:<port>/`); the port is random on each launch to avoid conflicts.

**"Offline model incomplete".** The archive was not fully extracted. Verify `_internal/models/whisper-base/` contains all four files (`model.bin` ≈ 138 MB).

**"A task is already running".** The queue holds a single job — wait for it or restart the program.

**Empty transcript.** Voice activity detection runs first; silence or very low input volume is reported as no speech. Check the input device and recording level.

**Dictation: the side button does nothing.** Run `--dictate --probe`, press it once, and note whether it reports `XBUTTON1/2` or a `vk=0x..` key; then pass `--button x1/x2/f9`. No output at all means the vendor driver intercepted it.

**Dictation: text is not injected.** Elevated target windows cannot receive input from a non-elevated process (UIPI) — the text stays on the clipboard. For terminals that ignore `Ctrl+V`, add `--type`.

**Antivirus warning.** Unsigned PyInstaller executables often trip heuristics. Build from source yourself or allowlist the folder.

## License

[MIT](LICENSE). Whisper weights are MIT (OpenAI), `faster-whisper` and CTranslate2 ship under their own licenses (see `_internal/licenses/` in the packaged build).

---

中文文档见 [README.md](README.md)。