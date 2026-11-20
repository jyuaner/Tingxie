# 听写 · Tingxie

> 让声音，成为文字。一款**完全离线**的 Windows 本地语音转文字工具 —— 模型与运行环境全部内置，首次使用也不需要联网。

<p align="left">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-147d68" />
  <img alt="offline" src="https://img.shields.io/badge/network-100%25%20offline-147d68" />
  <img alt="engine" src="https://img.shields.io/badge/engine-faster--whisper%20base-147d68" />
  <img alt="license" src="https://img.shields.io/badge/license-MIT-blue" />
</p>

![听写主界面](docs/images/main.png)

<p align="center">
  <img src="docs/images/upload.png" width="49%" alt="导入音频并试听" />
  <img src="docs/images/empty.png" width="49%" alt="空状态界面" />
</p>

---

## 这是什么

**听写**是一款「双击就能用」的离线语音转文字小工具：录一段话，或者拖进一个音频文件，几秒到几分钟后拿到可编辑的文字。

- 音频**不上传**任何云端，识别在本机 CPU 上完成；
- 不需要账号、不需要 API Key、不需要显卡；
- 解压后双击 `Tingxie.exe`，浏览器里操作，界面像本地应用。

适合课堂录音整理、会议记录、口述笔记、采访素材转写等场景。

## 功能

| 能力 | 说明 |
| --- | --- |
| 🎙 麦克风录音 | 浏览器内录音，停止后可先试听，再决定是否转写 |
| 📂 导入音频 | 支持 WAV / MP3 / M4A / MP4 / FLAC / OGG / WEBM / AAC / WMA / OPUS |
| 🌐 语言识别 | 中文（普通话）、英语，或交给模型自动检测 |
| ✍️ 结果处理 | 文字可编辑、复制、导出 UTF-8 TXT（带 BOM，Excel/记事本不乱码） |
| 📊 进度可见 | 解码 → 语音检测 → 加载模型 → 逐段识别，实时百分比与阶段提示 |
| 🧹 不留痕迹 | 临时音频在任务结束即删除；结果只存在内存中，退出即清空 |
| 🔒 本机防护 | 仅监听 `127.0.0.1`，校验 Host / Origin / 一次性访问令牌，防止局域网访问与跨站调用 |

## 快速开始（普通用户）

1. 在 [Releases](../../releases) 下载 `Tingxie-Windows-x64-offline.zip`（约 224 MB）；
2. **完整解压**到任意目录（不要只把 EXE 拖出来，`_internal` 里是模型和运行环境）；
3. 双击 `Tingxie.exe`，程序会自动打开浏览器页面；
4. 录音或导入音频 → 选语言 → 开始转写 → 编辑/复制/导出。

> 首次识别会加载模型，CPU 上需要几秒预热；之后的转换更快。

## 从源码运行

```powershell
git clone https://github.com/jyuaner/Tingxie.git
cd Tingxie

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 把 Whisper Base（faster-whisper / CTranslate2 格式）放进 models/whisper-base/
python scripts/fetch_model.py

python app.py            # 默认自动选空闲端口并打开浏览器
python app.py --port 8722 --no-browser --debug
```

`models/whisper-base/` 需要四个文件：

```
models/whisper-base/
├── model.bin          # CTranslate2 权重（int8 也可）
├── config.json
├── tokenizer.json
└── vocabulary.txt
```

`scripts/fetch_model.py` 从 `Systran/faster-whisper-base` 下载并放到该目录（仅首次运行需要联网，之后程序本身完全离线）。

## 打包为离线单目录 EXE

```powershell
python -m pip install pyinstaller
python -m PyInstaller tingxie.spec --noconfirm
```

产物在 `dist/Tingxie-windows-x64/`：`Tingxie.exe` + `_internal/`（含 `models/whisper-base`、`static/`、`templates/`）。
把这个目录整体压缩即得到可分发离线包。`scripts/build.ps1` 封装了上面两步。

## 技术架构

```
┌───────────────────────── 浏览器（本机） ─────────────────────────┐
│  templates/index.html + static/app.js + core.mjs + style.css     │
│  录音(MediaRecorder) · 拖拽导入 · 编辑/复制/导出 · 轮询进度        │
└───────────────▲──────────────────────────────────────┬───────────┘
                │ fetch + X-App-Token                  │ multipart 音频
┌───────────────┴──────────────────────────────────────▼───────────┐
│  Waitress（127.0.0.1，随机端口）  ←  Flask  webapp.py            │
│  Host/Origin 校验 · CSP · 201 MiB 请求上限 · 单任务队列(JobManager)│
└───────────────▲──────────────────────────────────────┬───────────┘
                │ 进度回调 progress/stage/text          │ 后台线程
┌───────────────┴──────────────────────────────────────▼───────────┐
│  transcriber.py                                                  │
│  PyAV 解码 → 16 kHz 单声道 int16（硬上限 3600 s）                  │
│  Silero VAD 切片 → faster-whisper Whisper Base（CPU / int8）      │
└──────────────────────────────────────────────────────────────────┘
```

- **前端**：原生 HTML/CSS/ES Module，无构建步骤，无框架依赖。
- **后端**：Flask + Waitress（生产级 WSGI，多线程），单任务队列，结果驻留内存。
- **识别**：`faster-whisper` + CTranslate2，`device="cpu"`、`compute_type="int8"`、`cpu_threads=min(4, cpu_count)`；开启 VAD 过滤与 `beam_size=3`，中文额外注入简体标点提示词。
- **打包**：PyInstaller onedir，模型与静态资源通过 `--add-data` 一并收集。

### HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 单页界面（注入一次性 `X-App-Token`） |
| GET | `/api/info` | 模型名、离线标记、上传上限、是否就绪、最近任务 |
| POST | `/api/transcriptions` | `multipart/form-data`：`audio` 文件 + `language`（`zh`/`en`/`auto`），返回 `202 {id}` |
| GET | `/api/transcriptions/<id>` | 任务快照：`state`、`stage`、`progress`、`text`、`segments`、`duration`、`language`、`error` |
| POST | `/api/shutdown` | 空闲时优雅退出本地服务 |

错误统一为 `{"error": "..."}`；状态码覆盖 `400 / 403 / 404 / 409 / 413 / 503`。

## 目录结构

```
Tingxie/
├── app.py               # 启动器：选端口、起 Waitress、开浏览器
├── webapp.py            # Flask 应用、安全校验、单任务队列
├── transcriber.py       # 音频解码 + Whisper 推理
├── templates/index.html # 界面结构
├── static/
│   ├── app.js           # 交互逻辑（录音、上传、轮询、导出）
│   ├── core.mjs         # 纯函数：校验、时间格式化、字数统计
│   ├── style.css        # 设计系统与动效
│   └── favicon.svg
├── models/              # 放置 whisper-base（不随仓库分发权重）
├── scripts/
│   ├── fetch_model.py   # 下载并校验模型文件
│   └── build.ps1        # 一键打包离线包
├── tingxie.spec         # PyInstaller 配置
├── requirements.txt
└── docs/images/
```

## 性能参考（CPU，无独显）

| 机器 | 示例 | 10 分钟音频耗时 |
| --- | --- | --- |
| i5-1135G7 (4 线程) | whisper-base int8 | ≈ 1.5–2.5 分钟 |
| R5-5600U (4 线程) | whisper-base int8 | ≈ 1.5–2.5 分钟 |
| 老款 i5-8250U | whisper-base int8 | ≈ 3–5 分钟 |
| 低功耗赛扬/奔腾 | — | 明显更慢，长音频建议拆分 |

> 实测值随音频内容、语音密度与后台负载波动，仅供参考。VAD 会跳过静音段，静音越多越快。

## 已知限制

- 仅提供 **Windows 10/11 64 位** 构建，老旧 CPU 是否兼容取决于指令集（AVX2 通常更稳）；
- 单个文件上限 **200 MB / 60 分钟**，超出会被前端与后端同时拦截；
- **录完再转写**，不是实时流式识别；
- 没有说话人分离、没有自动摘要、没有标点/断句模型二次校正；
- 噪声、口音、专业术语仍会出错，重要内容请人工校对；
- 结果只保存在内存，关闭程序即清空 —— 记得先导出；
- 界面为单任务串行：一个任务跑完才能提交下一个。

## 隐私说明

- 推理全部在本机完成，程序没有任何外发网络的业务请求；
- `HF_HUB_OFFLINE=1`，即使模型目录缺失也不会触发在线下载；
- 上传的音频写入系统临时目录，任务结束（完成或失败）立即 `unlink`；
- 服务只绑定 `127.0.0.1`，并通过一次性 token 拒绝非本页面发起的请求。

## 常见问题

**双击后浏览器没打开？** 看控制台窗口打印的地址，手动访问 `http://127.0.0.1:<端口>/`。端口每次启动随机，避免冲突。

**提示「离线模型不完整」？** 解压不完整。请完整解压 zip，确认 `_internal/models/whisper-base/` 下四个文件齐全（`model.bin` 约 138 MB）。

**提示「已有任务正在处理」？** 单任务队列，等当前任务结束或重启程序。

**转写结果为空？** 程序会先做语音活动检测，音量过低/纯静音会被判定为无语音。检查系统输入设备、调高录音音量。

**杀毒软件报警？** PyInstaller 打包的未签名 EXE 常被启发式误报。可自行从源码构建，或对该目录加白名单。

## 路线图

- [ ] 边说边出字（流式解码）
- [ ] 说话人分离与自动分段标题
- [ ] 模型可选（base / small / medium）与量化档位切换
- [ ] macOS / Linux 构建

## 许可证

[MIT](LICENSE)。Whisper 模型权重来自 OpenAI（MIT），`faster-whisper` 与 CTranslate2 遵循各自许可，详见打包目录 `_internal/licenses/`。

---

**English**: Tingxie is a fully offline, local speech-to-text desktop tool for Windows 10/11 x64. Record from the microphone or import audio (WAV/MP3/M4A/FLAC/WebM…), transcribe with Whisper Base on CPU via faster-whisper, then edit, copy or export to TXT. No cloud, no account, no GPU — models are bundled and the very first run works without a network connection. See [README_EN.md](README_EN.md) for the English documentation.