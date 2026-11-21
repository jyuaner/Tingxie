# 听写 · 复刻任务书（可直接粘贴给其他 AI）

> 用法：把本文件**整篇**粘贴给 AI（或作为附件上传），再加一句「按这个任务书实现，先给文件清单和关键代码，再逐文件补全」。文末有更短的「精简版提示词」，适合在对话框里一次性提问。

---

## 0. 一句话目标

做一个 **Windows 桌面常驻的全局语音输入工具**：按下自定义的触发键（鼠标侧键/键盘键/组合键）开始录音，再按一下停止，1–2 秒后把识别出的文字**直接输入到当前光标所在的任何窗口**。不出现网页、不开端口、不点按钮。

## 1. 运行环境与交付形态

- 目标系统：Windows 10 / 11，64 位；不要求独立显卡。
- 语言/运行时：Python 3.12。
- 交付：一个可双击运行的 **单文件 EXE**（PyInstaller onefile，含模型与运行时），另附一个 onedir 版离线包（zip）。
- **必须能完全离线运行**：首次使用也不联网；模型随包分发。
- 只有一个常驻进程，控制台窗口显示状态，关闭窗口即退出。

## 2. 交互定义（逐条实现，不可自创）

1. **切换式录音**：按一下触发键 = 开始录音；再按一下 = 停止并开始识别。**不是按住说话**。
2. **提示音**：开始（升调两声）、停止（降调两声）、识别成功（高声两声）、失败（低声两声）。可用 `--silent` 关闭。
3. **Esc 取消**：录音过程中按 Esc 立即丢弃本次录音，不识别。
4. **最短时长保护**：录音短于 0.35 秒视为误触，丢弃并提示。
5. **最长时长**：默认 120 秒自动停止（可配置）。
6. **上屏方式**：优先「写剪贴板 + 注入 Ctrl+V」，注入后 0.35 秒**还原用户原来的剪贴板内容**；另有 `--type` 逐字 Unicode 输入作为兜底。
7. **吞掉触发键事件**：触发键的按键事件不能漏给前台窗口（否则浏览器的「后退键」会被触发）。
8. **单实例**：已有实例在运行时，第二个实例打印提示后退出（不允许两个进程抢同一个键）。
9. **控制台输出**：每步带时间戳与符号，例如
   `[14:03:12] ● 开始录音…（再按一次停止，Esc 取消）`、
   `[14:03:18] … 录音 6.2s，识别中…`、
   `[14:03:19] ✓ 42 字 / 1.1s（本地）→ 你好，……`。
10. 识别结果为空时提示「没听到语音」而不是上屏空字符串。

## 3. 功能需求

### 3.1 触发键（必须可自定义）

支持四种写法：

| 写法 | 含义 |
| --- | --- |
| `x1` / `x2` / `middle` | 鼠标后退侧键 / 前进侧键 / 中键 |
| `f9`、`space`、`capslock`… | 任意单键（字母、数字、F1–F24、方向键、标点） |
| `ctrl+shift+d` | 修饰键 + 一个键（`ctrl`/`alt`/`shift`/`win` 任意组合） |
| `vk:0x7B` | 直接给 Win32 虚拟键码 |

- 命令行参数：`--trigger`，并接受 `--button` / `--key` 作为别名。
- 提供 `--list-keys` 打印全部可用键名。
- 组合键判定：触发键按下时用 `GetAsyncKeyState` 校验修饰键状态；**未要求任何修饰键时，Ctrl/Alt/Win 必须处于抬起状态**（避免打字时误触）。
- 触发键也可写进配置文件 `"trigger": "ctrl+shift+d"`。

### 3.2 语言

- `--language zh|en|auto`，默认 `zh`。
- 中文额外注入提示词：`以下是普通话内容，请使用简体中文和标点符号。`
- 英文与 `auto` 不注入提示词；`auto` 时把 `language=None` 交给模型自行判定。

### 3.3 双引擎（离线 / 云端）

| 模式 | 行为 |
| --- | --- |
| `local` | 本地 Whisper（CPU int8）；音频不出本机 |
| `online` | 调用任意 **OpenAI 兼容** `POST {base_url}/audio/transcriptions`（multipart：`file` + `model` + `language`） |
| `auto`（默认） | 配置了 Key 就用云端，失败（超时/401/断网/返回异常）**自动回退本地**，并在结果里说明原因 |

- `--asr auto|local|online` 覆盖配置。
- 云端返回要兼容多种结构：`{"text": …}`、`{"data":{"text":…}}`、`{"result":{"text":…}}`、`{"segments":[…]}`。
- 云端不可用时不能崩，只提示并回退（可在配置里 `"fallback": false` 关闭回退）。

### 3.4 配置

`config.json`（与 EXE 同目录；`--config PATH` 可指定）：

```json
{
  "mode": "auto",
  "fallback": true,
  "trigger": "ctrl+shift+d",
  "online": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-...",
    "model": "whisper-1",
    "timeout": 60,
    "send_language": true
  }
}
```

环境变量优先于文件：`TINGXIE_API_KEY`、`TINGXIE_BASE_URL`、`TINGXIE_MODEL`、`TINGXIE_MODE`、`TINGXIE_CONFIG`。仓库提供 `config.example.json`。

## 4. 推荐技术方案（可按此实现）

| 环节 | 方案 |
| --- | --- |
| 全局按键 | `SetWindowsHookExW(WH_MOUSE_LL / WH_KEYBOARD_LL, …)`，用 `ctypes` 直接调 Win32，**不要引入第三方钩子库** |
| 消息循环 | 主线程必须 `GetMessageW → TranslateMessage → DispatchMessageW`（低级钩子要靠它派发） |
| 录音 | `sounddevice.InputStream`（PortAudio），16 kHz 单声道 float32 回调收集到内存 |
| 采样率回退 | 先试 16 kHz；失败则用设备默认采样率（多為 48 kHz）录音，停止后用线性插值重采样到 16 kHz |
| 解码/识别 | `faster-whisper`（CTranslate2）：`device="cpu"`、`compute_type="int8"`、`cpu_threads=min(4, cpu_count)`、`beam_size=3`、`condition_on_previous_text=False`、`vad_filter=True` |
| VAD | `faster_whisper.vad.VadOptions(min_silence_duration_ms=500, min_speech_duration_ms=250)`，无语音段直接返回空 |
| 上屏 | `OpenClipboard/SetClipboardData(CF_UNICODETEXT)` + `SendInput` 发 Ctrl+V；兜底 `KEYEVENTF_UNICODE` 逐字 |
| 单实例 | `CreateMutexW(None, False, "Local\\TingxieDictation")`，先 `OpenMutexW` 检测 |
| 打包 | PyInstaller：onedir 一份 + onefile 一份；把模型目录、`_sounddevice_data/portaudio-binaries` 作为 data 一并收集 |

## 5. 命令行接口（照抄）

```
--trigger / --button / --key   触发键（默认 x1）
--list-keys                    列出可用键名后退出
--language zh|en|auto          识别语言（默认 zh）
--asr auto|local|online        引擎（默认按 config.json）
--config PATH                  配置文件路径
--model DIR                    本地模型目录（默认 models/whisper-base）
--device N                     录音设备序号
--devices                      列出输入设备后退出
--probe                        诊断：30 秒内打印收到的鼠标/键盘事件
--selftest                     自检：自己合成一次鼠标移动，判断钩子是否可用
--debug-events                 打印每个侧键事件的 wParam / injected 标记
--type                         逐字输入而不是粘贴
--keep-clipboard               上屏后不还原剪贴板
--no-paste                     只打印结果，不注入任何窗口
--max-seconds 120              单次录音上限
--min-seconds 0.35             低于该时长视为误触
--hotkey ctrl+alt+d            备用快捷键（RegisterHotKey，不依赖鼠标钩子）
--no-autofallback              启动时不做钩子自检、不自动启用备用键
--silent                       关闭提示音
--no-preload                   启动时不预热模型
```

## 6. 文件结构

```
Tingxie/
├── app.py                 # 薄入口，调用 dictation.main()
├── dictation.py           # 钩子、录音、提示音、状态机、上屏
├── asr.py                 # 本地/云端路由 + 配置 + multipart 客户端
├── transcriber.py         # 内存波形 → Whisper（VAD、提示词、进度）
├── config.example.json
├── 听写-全局输入.cmd        # 双击启动脚本（参数透传）
├── models/                # whisper-base 权重（不入库）
├── scripts/fetch_model.py # 下载并校验模型
├── scripts/build.ps1      # 打包 + 压缩 + SHA256
├── tingxie.spec           # onedir 打包
└── tingxie_onefile.spec   # onefile 打包（单文件 EXE）
```

## 7. 必须注意的坑（写进实现里）

1. **钩子必须有消息泵**：只 `SetWindowsHookEx` 不跑 `GetMessage` 循环，回调永远不会触发。
2. **回调要保留引用**（`HOOKPROC(...)` 存到实例属性上），否则被 GC 后钩子失效。
3. **吞事件**：命中触发键时钩子返回 `1`，否则 `CallNextHookEx`。
4. **注入事件防递归**：`flags & LLMHF_INJECTED` 的事件要忽略（自检/自动化时可用开关放行）。
5. **`use_last_error` + 64 位类型**：`GetClipboardData`、`GlobalLock`、`GlobalAlloc` 必须声明 `restype`/`argtypes`，否则句柄被截断成 int 直接崩溃。
6. **剪贴板重试**：`OpenClipboard` 会被别的程序占用，要重试若干次（约 12 次 × 30ms）。
7. **模型不联网**：导入 faster-whisper 前设置 `HF_HUB_OFFLINE=1`、`HF_HUB_DISABLE_TELEMETRY=1`，加载时 `local_files_only=True`；模型缺失就报错，不许偷偷下载。
8. **静音判定**：先跑 VAD，无语音段直接返回「没听到语音」，避免上屏空串。
9. **onefile 的代价**：每次启动解压到 `%TEMP%`（数秒），打包时不要压缩模型以外的资产太多余量；`--onefile` 的 EXE 首次启动可能被杀软扫描。
10. **UIPI**：前台窗口若是管理员权限进程，普通进程注入会被拒；此时文字留在剪贴板并提示。
11. **控制台中文**：启动时 `SetConsoleOutputCP(65001)` 并 `sys.stdout.reconfigure(encoding="utf-8")`。
12. **长音频限制**：录音缓冲区超过 `--max-seconds` 要截断，避免内存爆。

## 8. 错误文案（保持中文、面向用户）

- 模型缺失：`本地模型不完整，请检查 models/whisper-base 或配置云端`
- 云端未配置：`云端未配置（config.json 里的 online.base_url / api_key）`
- 麦克风打不开：`录音启动失败：<原因>`
- 太短：`太短了（0.42s），已忽略`
- 无语音：`没听到语音`
- 上屏失败：`上屏失败，文字已放到剪贴板，可手动 Ctrl+V`

## 9. 验收清单（让 AI 自测并逐条回答）

1. `--list-keys` 能打印全部键名；`--trigger ctrl+shift+d` 能解析且非法输入（`ctrl+`、`nope`）被拒绝并给出提示。
2. `--selftest` 在正常环境返回「自检通过」；在钩子被拦的环境给出原因而不是崩。
3. 按触发键：有升调提示音、控制台打印「开始录音」；再按：降调提示音、进入识别。
4. 录音时按 Esc：丢弃、无上屏、提示「已取消」。
5. 说一句中文 → 文字出现在记事本光标处，且**原来的剪贴板内容被还原**。
6. 触发键是侧键时，浏览器里按它**不会后退**。
7. 同时启动两个实例 → 第二个提示「已有一个听写实例在运行」并退出。
8. 拔掉网络、`--asr local` → 仍能识别。
9. `--asr online` 且配置错误的 Key → 报错清晰；`--asr auto` → 自动回退本地并提示原因。
10. 把 EXE 拷到另一台同架构机器（不带任何外部文件）双击可用（onefile 版）。
11. 录音 3 秒以内短句 → 上屏耗时 ≤ 3 秒（中端 CPU）。
12. 关闭控制台窗口 → 进程退出、钩子释放（再次启动不提示实例占用）。

## 10. 非目标（不要做）

- 不要做网页界面、不要开 HTTP 端口（本项目早期版本有，已移除）。
- 不要做流式「边说边出字」。
- 不要做说话人分离、自动摘要、识别历史。
- 不要引入 Electron / WebView / 第三方钩子库（`pynput`、`keyboard` 等）。

## 11. 给执行 AI 的附加指令

1. 先复述需求要点与文件清单，再开始写代码；
2. 按文件逐个输出完整代码，不要省略；
3. 关键 Win32 结构体（`MSLLHOOKSTRUCT`、`KBDLLHOOKSTRUCT`、`INPUT`）必须写全字段；
4. 给出 `pyinstaller` 的确切命令与需要收集的 data 文件；
5. 最后按第 9 节清单逐条自测，说明哪些通过、哪些只能在实机验证。

---

## 精简版提示词（一次性粘贴用）

> 用 Python 3.12 写一个 Windows 全局听写工具，PyInstaller 打成单文件 EXE，完全离线可用。
> ① 用 ctypes 调 `SetWindowsHookExW(WH_MOUSE_LL/WH_KEYBOARD_LL)` 做全局热键，主线程跑 GetMessage 消息泵；触发键可用 `--trigger` 自定义（`x1`/`x2`/`middle`、任意键、`ctrl+shift+d` 组合、`vk:0x7B`），命中时钩子返回 1 吞掉事件，组合键用 `GetAsyncKeyState` 校验修饰键。
> ② 按一下开始、再按一下停止（不是对讲机）；开始/停止/成功/失败各有提示音，Esc 取消，短于 0.35 秒视为误触，默认最长 120 秒。
> ③ 录音用 sounddevice 收进内存（16 kHz 单声道，设备不支持则用默认采样率再线性重采样），音频不落盘。
> ④ 识别用 faster-whisper（CPU、int8、beam 3、vad_filter=True，中文注入简体标点提示词），语言 `--language zh|en|auto`；同时支持云端：任意 OpenAI 兼容 `/audio/transcriptions`，`--asr auto|local|online`，云端失败自动回退本地。配置放 `config.json`（base_url/api_key/model/trigger），也支持环境变量。
> ⑤ 结果用「写剪贴板 + SendInput 发 Ctrl+V」输入到前台窗口，0.35 秒后还原原剪贴板；提供 `--type` 逐字输入兜底。
> ⑥ 单实例互斥锁 `Local\TingxieDictation`；控制台输出带时间戳的状态；模型缺失时明确报错且绝不联网下载（`HF_HUB_OFFLINE=1`、`local_files_only=True`）。
> ⑦ 提供 `--list-keys`、`--probe`（打印按键事件）、`--selftest`（自己合成事件检测钩子是否可用）、`--devices`。
> 交付前请按验收清单自测：侧键在浏览器里不后退、双实例会被拒、断网仍能本地识别、错误 Key 时 auto 能回退、中文上屏且剪贴板被还原。