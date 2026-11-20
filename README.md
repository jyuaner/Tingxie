# 听写 · Tingxie

> 按一下键，说话就变成文字。Windows 全局语音输入，识别在本机 CPU 或你配置的云端完成。

<p align="left">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-147d68" />
  <img alt="hotkey" src="https://img.shields.io/badge/trigger-任意键%20%2F%20鼠标侧键-147d68" />
  <img alt="offline" src="https://img.shields.io/badge/mode-本地离线%20%2F%20云端-147d68" />
  <img alt="license" src="https://img.shields.io/badge/license-MIT-blue" />
</p>

---

## 这是什么

一个常驻后台的听写小工具：**按下你绑定的键开始录音，再按一下结束，1–2 秒后文字出现在当前光标处** —— 微信、Word、IDE、浏览器输入框，都不用切窗口。

没有网页界面、不开端口、不装浏览器插件：解压后双击 `听写-全局输入.cmd`，它就一直在后台等你按键。

> v1.3.0 起，原来的浏览器版（Flask + Waitress + 网页界面）已经整体移除，只保留快捷键输入。

## 功能

| 能力 | 说明 |
| --- | --- |
| ⌨️ 任意触发键 | 鼠标侧键 / 中键 / 键盘任意键 / `ctrl+shift+d` 这类组合键 / 虚拟键码 |
| 🗣 中英双语 | 中文（普通话）、英文，或自动检测 |
| 🖥 双引擎 | 本地 Whisper Base（CPU，完全离线）或云端 API（更快更准），可自动切换与回退 |
| ✍️ 直接上屏 | 剪贴板 + `Ctrl+V` 注入当前前台窗口，识别后自动还原你原来的剪贴板 |
| 🔔 反馈明确 | 开始/结束/失败各有提示音；录音时按 `Esc` 取消；控制台打印耗时与字数 |
| 🧹 不留痕 | 音频只在内存里，不落盘；不写日志文件 |
| 🔒 单实例 | 第二个实例会提示并退出，避免两个进程抢同一个键 |
| 🛡 可控隐私 | `--asr local` 时音频不出本机；`config.json` 里的 Key 不进版本库 |

## 快速开始

1. 在 [Releases](../../releases) 下载 `Tingxie-Windows-x64-offline.zip`（约 250 MB）；
2. **完整解压**到任意目录（`_internal/` 里是模型和运行环境）；
3. 双击 **`听写-全局输入.cmd`**，窗口里会打印当前触发键与引擎状态；
4. 按一下鼠标侧键 → 说话 → 再按一下 → 文字出现在光标处；
5. 录音时想反悔，按 `Esc`。

窗口最小化就行，别关；关了就等于退出。

### 按键没反应？

```powershell
Tingxie.exe --selftest              # 自检：自己合成事件，2 秒告诉你钩子能不能收到（不动你的鼠标）
Tingxie.exe --probe                 # 30 秒内按一下你的键，打印它发的是 XBUTTON1/2 还是某个键盘键
Tingxie.exe --list-keys             # 列出所有可用键名
Tingxie.exe --trigger ctrl+shift+d  # 换个键试试
```

启动时也会自动自检：钩子安装失败或收不到事件，会自动改用 `ctrl+alt+d` 并提示，不会直接退出。

## 触发键

```powershell
听写-全局输入.cmd                              # 默认：鼠标侧键 x1（后退键）
听写-全局输入.cmd --trigger x2                 # 另一个侧键
听写-全局输入.cmd --trigger middle             # 鼠标中键
听写-全局输入.cmd --trigger f9                 # 键盘 F9
听写-全局输入.cmd --trigger ctrl+shift+d       # 任意组合键（推荐，不易误触）
听写-全局输入.cmd --trigger vk:0x7B            # 直接写虚拟键码
```

- `--button` / `--key` 都是 `--trigger` 的别名；
- 修饰键支持 `ctrl` / `alt` / `shift` / `win`；
- 按下的是哪个键，事件就被钩子吃掉，不会漏进别的窗口（浏览器的「后退」也不会被触发）；
- 也可以写进 `config.json` 的 `"trigger": "ctrl+shift+d"`，之后双击脚本就生效。

> ⚠️ 把单个字母（如 `--trigger d`）当触发键会让这个字母全局失效，日常建议用组合键或 F 区键。

## 语言

```powershell
听写-全局输入.cmd --language zh    # 中文（默认）
听写-全局输入.cmd --language en    # 英文
听写-全局输入.cmd --language auto  # 自动检测
```

中文会额外注入「请使用简体中文和标点符号」的提示词，输出带标点的简体中文；英文与自动检测不加提示词。

## 两种识别方式：离线 / 云端

| 模式 | 走哪条路 | 适合 |
| --- | --- | --- |
| `local` | 本机 Whisper Base（CPU int8），音频不出本机 | 断网、隐私敏感、开会 |
| `online` | 任意 OpenAI 兼容的 `/audio/transcriptions` 接口 | 有网，要更快更准 |
| `auto`（默认） | 配了 Key 就先走云端，超时/401/断网自动回退本地 | 日常使用 |

```powershell
听写-全局输入.cmd --asr local     # 强制离线
听写-全局输入.cmd --asr online    # 强制云端
听写-全局输入.cmd --asr auto      # 自动（默认）
```

云端配置：把 `config.example.json` 复制成 `config.json`（和 EXE 同目录），填三行即可：

```json
{
  "mode": "auto",
  "trigger": "ctrl+shift+d",
  "online": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-你的key",
    "model": "whisper-1"
  }
}
```

兼容的服务（都支持 OpenAI 的语音转写格式）：

| 服务 | base_url | model 示例 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `whisper-1` / `gpt-4o-mini-transcribe` |
| Groq | `https://api.groq.com/openai/v1` | `whisper-large-v3-turbo` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `FunAudioLLM/SenseVoiceSmall` |
| 自建网关 | `http://127.0.0.1:8000/v1` | 你的模型名 |

不想把 Key 写进文件，用环境变量：

```powershell
$env:TINGXIE_API_KEY  = "sk-..."
$env:TINGXIE_BASE_URL = "https://api.openai.com/v1"
$env:TINGXIE_MODEL    = "whisper-1"
$env:TINGXIE_MODE     = "auto"    # local / online / auto
```

> 🔐 `online` / `auto` 且配了 Key 时，音频会发送到你配置的服务商；`--asr local` 全程不出本机。
> `config.json` 含密钥，已在 `.gitignore` 中，请勿提交或分享。

## 从源码运行

```powershell
git clone https://github.com/jyuaner/Tingxie.git
cd Tingxie

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python scripts/fetch_model.py     # 一次性下载 whisper-base（也可只用云端，跳过这步）
python app.py                     # 就是全局听写
python app.py --list-keys         # 看可用键名
```

`models/whisper-base/` 需要四个文件：`model.bin`、`config.json`、`tokenizer.json`、`vocabulary.txt`（详见 [models/README.md](models/README.md)）。

## 打包

```powershell
python -m PyInstaller tingxie.spec --noconfirm
# 或者一步到位（含压缩与 SHA256）：
pwsh -File scripts/build.ps1
```

产物 `dist/Tingxie-windows-x64/`：

```
Tingxie.exe                # 主程序（双击即听写）
听写-全局输入.cmd            # 带提示的启动脚本，参数直接透传
config.example.json        # 云端配置示例
_internal/                 # 模型 + Python 运行时 + PortAudio
```

## 架构

```
按键（鼠标侧键 / 键盘 / 组合键）
   │  WH_MOUSE_LL / WH_KEYBOARD_LL 低级钩子（ctypes，无第三方钩子库）
   ▼
dictation.py  ── 提示音、Esc 取消、单实例互斥
   │  内存录音（PortAudio，16 kHz 单声道；声卡只支持 48 kHz 时自动重采样）
   ▼
asr.py  ── auto / local / online 路由，失败自动回退
   ├─ local → transcriber.py：Silero VAD → faster-whisper Whisper Base（CPU int8）
   └─ online → OpenAI 兼容 /audio/transcriptions（纯 urllib）
   ▼
剪贴板 + SendInput 注入当前前台窗口（可选 --type 逐字输入）
```

- 钩子：`ctypes` 直接调用 Win32，不引入第三方钩子库；按键事件被吞掉，避免浏览器后退；
- 音频：只在内存里流转，识别完即丢弃，不写临时文件；
- 上屏：剪贴板方式对中文标点最稳，并会在 0.35 秒后还原你原来的剪贴板。

## 目录结构

```
Tingxie/
├── app.py                 # 唯一入口，转给 dictation.main
├── dictation.py           # 触发键钩子、录音、提示音、上屏
├── asr.py                 # 本地/云端双引擎路由 + 配置文件
├── transcriber.py         # PyAV 解码 + Whisper 推理（内存波形直达）
├── config.example.json    # 云端配置示例（复制成 config.json）
├── 听写-全局输入.cmd        # 双击即用的启动脚本
├── models/                # whisper-base 模型（权重不入库）
├── scripts/
│   ├── fetch_model.py     # 下载并校验模型
│   └── build.ps1          # 一键打包 + 压缩
├── tingxie.spec           # PyInstaller 配置
└── requirements.txt
```

## 性能参考

| 场景 | 参考耗时 |
| --- | --- |
| 本地 · 5 秒短句 | 约 0.6–1.2 s |
| 本地 · 30 秒段落 | 约 3–6 s |
| 云端 · 5–30 秒 | 主要取决于网络往返，通常 1–3 s |

首次识别要加载模型（CPU 上约 1–5 秒预热），之后同一进程内复用。

## 已知限制

- 仅 Windows 10/11 64 位；老旧 CPU 是否兼容取决于指令集（AVX2 更稳）；
- 说话时不要按着触发键不放：是**按一下开始、再按一下结束**，不是对讲机；
- 说了才出字，不是边说边出字（无流式）；
- 上屏目标是**当前前台窗口**；管理员权限的窗口会因 Windows UIPI 拒绝接收，文字会留在剪贴板里，手动 `Ctrl+V`；
- 少数终端屏蔽 `Ctrl+V` 时可加 `--type` 逐字输入；
- 同时只能跑一个实例；关闭控制台窗口即退出；
- 噪声、口音、专业术语仍会出错，重要内容请核对。

## 隐私

- `--asr local`：识别全在本机，程序没有任何外发请求；
- `HF_HUB_OFFLINE=1`、`local_files_only=True`：模型缺失时报错，不会偷偷联网下载；
- 录音只在内存，识别结束即释放，不写磁盘；
- `online` / `auto` 且配置了 Key 时，音频会按你的配置发往对应服务商（计费与数据策略由服务商决定）；
- `config.json` 已在 `.gitignore` 中。

## 常见问题

**按了没反应？** 依次跑 `--selftest`、`--probe`、`--list-keys`；钩子被安全软件拦时会自动提示并改用 `ctrl+alt+d`。

**识别了但没进窗口？** 前台窗口是管理员权限的（任务管理器、管理员终端）会被 UIPI 拦截 —— 文字已在剪贴板，手动 `Ctrl+V`。

**云端报 401 / 400？** 检查 `base_url`（要带 `/v1`）、`api_key`、`model` 是否为该服务商支持的语音模型名。

**麦克风没声音？** Windows 设置 → 隐私和安全性 → 麦克风，允许桌面应用访问；`--devices` 列出设备，`--device N` 指定。

**想回到 v1.2 的网页版？** 旧版本仍在 [Releases](../../releases)，下载 v1.2.0 即可；两版共用同一份 `config.json` 格式。

**杀软报警？** PyInstaller 打包的未签名 EXE 常被启发式误报；可自行从源码构建，或对该目录加白名单。

## 路线图

- [ ] 托盘图标，彻底不占控制台窗口
- [ ] 边说边出字（流式解码）
- [ ] 模型档位切换（base / small / medium）
- [ ] 识别历史（可选，默认关闭）

## 许可证

[MIT](LICENSE)。Whisper 权重为 OpenAI 的 MIT 许可；`faster-whisper`、CTranslate2、PortAudio 按各自许可分发。

---

English docs: [README_EN.md](README_EN.md)