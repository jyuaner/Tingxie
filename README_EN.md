# Tingxie — press a key, speak, text appears

> Global dictation for Windows. Press your trigger key, talk, press it again — the transcript is pasted into whatever window has focus. Recognition runs on the local CPU or on a cloud API you configure.

Windows 10/11 x64 · no browser UI · no port · no account required for the offline mode.

> Since v1.3.0 the browser version (Flask + Waitress + web UI) has been removed. The product is the hotkey dictation daemon only.

## What it does

1. Double-click `听写-全局输入.cmd` (extracted folder) — it sits in the background;
2. Press the trigger key (default: mouse side button `x1`) — rising beeps start recording;
3. Speak, press the trigger again — falling beeps, then the text is pasted at your cursor;
4. Press `Esc` while recording to cancel.

## Features

- **Any trigger** — mouse side/middle button, any keyboard key, combos like `ctrl+shift+d`, or a raw virtual-key code.
- **Chinese / English / auto-detect** — Chinese gets a simplified-Chinese punctuation prompt.
- **Two engines** — local Whisper Base (CPU, fully offline) or any OpenAI-compatible transcription endpoint, with automatic fallback.
- **Pastes, not types** — clipboard + `Ctrl+V` into the focused window, previous clipboard restored; `--type` for terminals that block paste.
- **No traces** — audio lives in RAM only, never written to disk; no log files.
- **Single instance** — a second copy refuses to start so two processes never fight over the same key.

## Quick start

```powershell
听写-全局输入.cmd                              # default trigger: x1 (mouse back button)
听写-全局输入.cmd --trigger ctrl+shift+d       # any combo
听写-全局输入.cmd --trigger f9                 # any key
听写-全局输入.cmd --trigger middle             # middle click
听写-全局输入.cmd --list-keys                  # every supported key name
听写-全局输入.cmd --language en                # zh (default) / en / auto
```

`--button` and `--key` are aliases of `--trigger`. The trigger can also live in `config.json` as `"trigger": "ctrl+shift+d"`.

**Nothing happens?** Run these in order:

```powershell
Tingxie.exe --selftest    # synthesises a 1-pixel mouse move; tells you in 2 s whether hooks work
Tingxie.exe --probe       # press your key within 30 s; prints XBUTTON1/2 or the virtual-key code
Tingxie.exe --list-keys   # supported key names
```

If hooks are blocked (security software) the daemon says so at startup and falls back to `ctrl+alt+d` automatically.

## Offline vs cloud

| Mode | Path | When |
| --- | --- | --- |
| `local` | local Whisper Base, CPU int8, audio never leaves the machine | offline, privacy-sensitive |
| `online` | any OpenAI-compatible `/audio/transcriptions` endpoint | online, faster/stronger |
| `auto` (default) | cloud first when configured, automatic fallback to local | everyday use |

```powershell
听写-全局输入.cmd --asr local     # force offline
听写-全局输入.cmd --asr online    # force cloud
听写-全局输入.cmd --asr auto      # default
```

Copy `config.example.json` to `config.json` next to the EXE:

```json
{
  "mode": "auto",
  "trigger": "ctrl+shift+d",
  "online": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-your-key",
    "model": "whisper-1"
  }
}
```

Works with OpenAI, Groq (`https://api.groq.com/openai/v1`), SiliconFlow, or your own gateway. Override without touching the file: `TINGXIE_API_KEY`, `TINGXIE_BASE_URL`, `TINGXIE_MODEL`, `TINGXIE_MODE`.

> In `online`/`auto` with a key configured, audio is sent to the provider you chose. `--asr local` keeps everything on the machine. `config.json` holds a secret and is git-ignored.

## Run from source

```powershell
git clone https://github.com/jyuaner/Tingxie.git
cd Tingxie
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/fetch_model.py    # optional when you only use the cloud engine
python app.py
```

## Build

```powershell
python -m PyInstaller tingxie.spec --noconfirm
pwsh -File scripts/build.ps1     # build + zip + sha256
```

Output: `dist/Tingxie-windows-x64/` — `Tingxie.exe`, `听写-全局输入.cmd`, `config.example.json`, `_internal/` (model, runtime, PortAudio).

## Architecture

```
trigger key (mouse / keyboard / combo)
  -> WH_MOUSE_LL / WH_KEYBOARD_LL low-level hooks (ctypes, no third-party hook library)
  -> dictation.py: beeps, Esc cancel, single-instance mutex
  -> in-memory capture (PortAudio, 16 kHz mono, resampled from 48 kHz when needed)
  -> asr.py: auto / local / online routing with fallback
       local  -> transcriber.py: Silero VAD -> faster-whisper Whisper Base (CPU int8)
       online -> OpenAI-compatible /audio/transcriptions (plain urllib)
  -> clipboard + SendInput into the foreground window (or --type)
```

## Limitations

- Windows 10/11 x64 only; older CPUs depend on the instruction set.
- Toggle, not push-to-talk: press once to start, press again to stop.
- No streaming: text appears after you stop.
- Elevation boundary: elevated windows reject injection (UIPI) — the text stays on the clipboard.
- One instance at a time; closing the console window quits the daemon.

## Privacy

`--asr local` makes no outbound requests. `HF_HUB_OFFLINE=1` and `local_files_only=True` mean a missing model errors out instead of downloading. Audio never touches the disk.

## License

[MIT](LICENSE). Whisper weights are MIT (OpenAI); faster-whisper, CTranslate2 and PortAudio ship under their own licenses.

---

中文文档见 [README.md](README.md)。