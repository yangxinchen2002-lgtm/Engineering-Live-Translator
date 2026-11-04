# ELT 便携版与模型部署

[中文](MODEL_SETUP.md) · [English](MODEL_SETUP.en.md)

## 1. 下载可直接运行的软件

进入 [ELT Windows 便携版下载页](https://github.com/yangxinchen2002-lgtm/Engineering-Live-Translator/releases/tag/v0.1.1-preview.20261104)，展开 Assets：

| 下载项 | 用途 |
|---|---|
| `01-ELT-Core.7z.001` 及同组后续分卷（若有） | 主程序、ELT.exe、独立 Python、界面与所需主依赖 |
| `02-ASR-Model.7z.001`、`.002` 等全部同组分卷 | 已配置的 Faster-Whisper large-v3-turbo 识别模型 |
| `03-GPU-Runtime.7z.001`、`.002` 等全部同组分卷 | 经过当前版本验证的 CUDA 12.4 / cuDNN 9.1 运行库 |
| `7za.exe` 与 `Extract-ELT.cmd` | 检查和一键合并解压 |
| `packages.json`、`SHA256SUMS.txt`、`READ-FIRST.txt` | 包清单、校验值、快速说明 |

将文件放在**同一个文件夹**，保持原名，双击 **Extract-ELT.cmd**。它先检查压缩数据，再合并到旁边的 **ELT** 文件夹。进入 ELT，双击 **ELT.exe**。不要单独解压 `.002` 等后续分卷，也不要把 GitHub 自动生成的 Source code ZIP 当成可运行软件。

每个上传文件不超过 400 MB；总下载量以 Assets 清单为准。建议至少预留 15 GB 空间供下载、解压和运行。路径可含空格，建议使用较短的本地路径。已存在 ELT 文件夹时解压脚本会停止，不覆盖你的文件。

无需另装 Python、Visual Studio、VLC 或虚拟声卡。需要 **Windows 11 x64、兼容的 NVIDIA 显卡及驱动**。内置播放器需要 [微软 WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download-section)，Windows 11 通常已有；缺少时从微软下载。软件不代为更换显卡驱动。

## 2. 首次配置

1. 在“翻译”页添加自己的 API Key，选择服务与模型；密钥保存在本机 Windows 凭据库。
2. 设置原始语言，在“启用翻译”旁选择中文或 English。实时与整句模式都可用。
3. 不安装 Qwen 时，在“朗读”页选择 **Windows 系统音色**。需要相应语言的 Windows 音色，可按[微软语音设置说明](https://support.microsoft.com/windows/appendix-a-supported-languages-and-voices-4486e345-7730-53da-fcfe-55cc64300f01)安装。
4. 选择应用音频或视频预读，再开始字幕；网页播放、暂停和跳转由你控制。
5. 若需英文界面，右上角选择 English 后重新打开 ELT。

便携包不含发布者的 API Key、个人字幕、偏好或课程浏览器资料。字幕保存默认关闭；开启时自行选择文件夹。第三方课程需由你自行登录，本包不能绕过访问限制。

## 3. 模型分别做什么

| 模型或服务 | 是否必须 | 作用 |
|---|---|---|
| Faster-Whisper large-v3-turbo | 必须，已在 02 组中 | 本机语音转文字 |
| DeepSeek / GPT / Claude / Gemini API | 启用翻译时 | 将识别文字翻译为中文或英文；使用你自己的账号 |
| Windows 系统音色 | 可选，不需下载 Qwen | 本机朗读译文 |
| Qwen3-TTS 0.6B CustomVoice | 可选 | 本地朗读，模型较小 |
| Qwen3-TTS 1.7B CustomVoice | 可选 | 本地朗读，支持讲课语气指令；体积和运行负担较大 |

**当前翻译由所选 API 完成，本教程部署的是 Whisper 识别模型和 Qwen 朗读模型。** 无需部署 DeepSeek 的本地大模型。接口只接收所需文本、术语和有限上下文，原始课程音频默认留在本机。

## 4. Whisper 下载入口与手动部署

完整下载 02 组并解压后无需再下载模型。只下载主程序或模型文件损坏时，可在 ELT 文件夹双击 **Download-ASR-Model.cmd**，等待明确成功后重开程序。

- [模型发布者页面](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo)
- [本版固定 revision 文件目录](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf)
- [Faster-Whisper 官方项目](https://github.com/SYSTRAN/faster-whisper)

原模型地址 `mobiuslabsgmbh/...` 已重定向至 `dropbox-dash/...`。保留已验证 revision，不直接替换为未验证模型或最新版 CUDA。下载脚本会把模型放在：

```text
ELT/
  models/large-v3-turbo/
    model.bin
    config.json
    tokenizer.json
    preprocessor_config.json
    vocabulary.json
```

模型约 1.62 GB，磁盘大小不等于显存需求。原始 Transformers 模型不能只改名为 `model.bin`；ELT 使用 CTranslate2 格式。手动下载要保留文件名和目录层级。

## 5. 可选：Qwen 本地朗读

Qwen 可朗读中文和英文；英语可选 Aiden 或 Ryan。没有 Qwen 时，字幕与 API 翻译仍可运行。

### 安装独立朗读环境

先从 [Python 官方 Windows 安装页](https://www.python.org/downloads/release/python-31210/) 安装完整 **Python 3.12 x64**，保留 Python launcher 安装选项。这个额外条件仅适用于 Qwen，基础软件不需要另装 Python。然后在解压后的 **ELT** 文件夹中双击 **Install-Qwen-Runtime.cmd**。它创建独立 `.venv-tts`，从 PyPI 与 PyTorch 官方源安装锁定依赖并检查导入，不会升级识别环境。建议额外预留 20 GB 磁盘空间。

此操作是你主动启用的可选安装，不在启动 ELT 时自动进行。已有 `.venv-tts` 时工具拒绝覆盖；失败会保留未完成目录并明确报错，重试前需自行改名。尝试过的嵌入式 Qwen 环境没有通过迁移导入测试，因此本版采用完整 Python 的独立环境；本次未重新执行从零下载并安装全部 Qwen 依赖的验收。

### 下载一个或两个朗读模型

| 操作入口 | 官方下载页 |
|---|---|
| 双击 `Download-Qwen-0.6B.cmd` | [Qwen3-TTS 0.6B CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) |
| 双击 `Download-Qwen-1.7B.cmd` | [Qwen3-TTS 1.7B CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) |

脚本包含模型所需的语音解码器，并对大文件进行摘要校验，可复用已经校验的文件。0.6B 本版 revision 为 `85e237c12c027371202489a0ec509ded67b5e4b5`，1.7B 为 `0c0e3051f131929182e2c023b9537f8b1c68adfe`。各模型及解码器约需数 GB，实际大小以下载日志为准。

```text
ELT/
  .venv-tts/Scripts/python.exe
  models/Qwen3-TTS-12Hz-0.6B-CustomVoice/
    model.safetensors
    config.json
    speech_tokenizer/...
  models/Qwen3-TTS-12Hz-1.7B-CustomVoice/   # 选装
```

安装和下载完成后**重新打开 ELT**，在“朗读”页选择 0.6B 或 1.7B、对应音色及 GPU/CPU，再试听。首次模型加载需要时间；CPU 可用但不承诺跟得上课程。一次只加载所选的朗读模型。Whisper 和 Qwen 共享显卡资源，不能仅凭模型参数量判断总显存是否足够。

## 6. 检查与排错

- 双击 **Check-ELT.cmd**：检查原始包文件、关键导入和独立配置，不进行音频捕获或付费翻译。安装可选组件后出现的新文件不会被当成原包的一部分。
- 缺少 `model.bin`：补齐 02 组或运行 Download-ASR-Model.cmd。
- CUDA / cuDNN 错误：补齐 03 组，确认 NVIDIA 驱动；不要将随机 DLL 混进目录。
- 内置窗口无法打开：安装微软 WebView2 Runtime；应用音频模式仍是独立入口。
- 选了 Windows 音色却无声音：确认相应语言音色已安装，检查朗读开关及音量。
- 选了 Qwen 却提示未安装：先完成独立环境和 CustomVoice 模型部署，保留 `speech_tokenizer` 子目录，重开 ELT。
- API 失败：检查自己的 Key、余额、网络和模型权限；原文仍应保留。
- 网络无法访问 Hugging Face：可从官方模型页下载相同 revision 后按上述目录放置，不复制他人的密钥或浏览器会话资料。

原安装包的文件摘要列在 `SHA256SUMS.txt`。可用 PowerShell `Get-FileHash .\文件名 -Algorithm SHA256` 比对。首次安全提示由 Windows 根据文件来源与签名决定，本版为未签名预览版；不要关闭系统安全保护。

本机迁移测试不代表所有电脑、驱动和一小时稳定性都已经验证；详细实际验证结果见 Release 说明。
