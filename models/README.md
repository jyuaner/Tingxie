# models/

本目录用于存放本地语音识别模型，**权重不随仓库分发**（`whisper-base` 约 138 MB）。
`models/whisper-base/` 已被 `.gitignore` 忽略，只有本说明文件会被提交。

## 需要的文件

程序在启动时校验以下四个文件是否存在且非空，缺任何一个都会提示「离线模型不完整」：

```
models/whisper-base/
├── model.bin          # CTranslate2 权重，int8 / float32 均可
├── config.json
├── tokenizer.json
└── vocabulary.txt
```

## 获取方式

**推荐：脚本下载（需要一次联网）**

```powershell
python scripts/fetch_model.py
```

脚本从 Hugging Face 下载 `Systran/faster-whisper-base` 的 CTranslate2 版本，校验 SHA256 后放入
`models/whisper-base/`。之后的运行、打包、分发都不再需要网络。

**手动放置**

1. 打开 <https://huggingface.co/Systran/faster-whisper-base/tree/main>；
2. 下载 `model.bin`、`config.json`、`tokenizer.json`、`vocabulary.txt`；
3. 四个文件一起放进 `models/whisper-base/`。

**从发布包提取**

已下载 `Tingxie-Windows-x64-offline.zip` 的话，模型在
`Tingxie-Windows-x64/_internal/models/whisper-base/`，直接复制过来即可。

## 换成更大的模型

`faster-whisper` 的任意 CTranslate2 模型目录都可以用（`small`、`medium`、`large-v3` 等），
按上面同样的四文件结构放好，然后：

```powershell
python app.py --model models/whisper-large-v3
# 打包版：Tingxie.exe --model D:\models\whisper-large-v3
```

体积与速度大致线性增长，CPU 上 `small` 通常仍是可接受的选择；`medium` 及以上建议配更多核心。
打包时记得同步修改 `tingxie.spec` 里的模型路径与 `models` 名称，否则 EXE 里仍是 `whisper-base`。

## 说明

- `HF_HUB_OFFLINE=1` 与 `local_files_only=True` 已经生效，模型缺失时程序**不会**偷偷联网下载，只会报错；
- 权重来源：OpenAI Whisper（MIT），CTranslate2 转换版由 Systran 发布；
- 首次识别需要加载模型，CPU 上约有 1–5 秒预热时间，之后同一进程内复用；
- 只用云端（`--asr online`）时可以不准备本地模型。