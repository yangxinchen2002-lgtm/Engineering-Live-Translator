# ELT portable application and model setup

[中文](MODEL_SETUP.md) · [English](MODEL_SETUP.en.md)

## 1. Download the runnable application

Open the [Windows portable release](https://github.com/yangxinchen2002-lgtm/Engineering-Live-Translator/releases/tag/v0.1.1-preview.20261104) and expand Assets.

| Assets | Purpose |
|---|---|
| All `01-ELT-Core.7z.*` volumes | ELT.exe, isolated Python, interface and main dependencies |
| All `02-ASR-Model.7z.*` volumes | Configured Faster-Whisper large-v3-turbo recognition model |
| All `03-GPU-Runtime.7z.*` volumes | Validated CUDA 12.4 / cuDNN 9.1 runtime libraries |
| `7za.exe` and `Extract-ELT.cmd` | Archive checks and extraction |
| `packages.json`, `SHA256SUMS.txt`, `READ-FIRST.txt` | Inventory, checksums and quick instructions |

Keep all files in **one folder**, retain their names, and double-click **Extract-ELT.cmd**. It checks the archives, then merges the three groups into an **ELT** folder. Open that folder and double-click **ELT.exe**. Do not extract `.002` and later volumes individually. GitHub's automatically generated Source code ZIP is not the runnable application.

Each uploaded asset is below 400 MB; see Assets for total size. Allow at least 15 GB for downloading, extraction and use. Prefer a short local path. The extractor stops if an ELT folder already exists, without overwriting it.

You do not need to install Python, Visual Studio, VLC or a virtual audio device for the basic package. You need **Windows 11 x64 and a compatible NVIDIA GPU/driver**. The built-in player requires [Microsoft WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download-section), usually present on Windows 11. ELT does not replace your GPU driver.

## 2. First start

1. Add your own API key and choose a provider/model in Translation. Keys stay in Windows Credential Manager.
2. Choose the source language and Chinese or English translation target. Both live preview and full-sentence modes are available.
3. For narration without Qwen, choose **Windows system voices** in Speech. Install a matching language voice using [Microsoft's guidance](https://support.microsoft.com/windows/appendix-a-supported-languages-and-voices-4486e345-7730-53da-fcfe-55cc64300f01) if necessary.
4. Select application audio or video lookahead and start subtitles. You control video playback, pauses and seeking.
5. Choose English at the top right and reopen ELT for the English interface.

The package contains no publisher API keys, transcripts, preferences or course-browser login data. Saving is off by default. Sign in to your own course site when required; the application does not bypass access restrictions.

## 3. Which model does what?

| Model/service | Required? | Role |
|---|---|---|
| Faster-Whisper large-v3-turbo | Yes; included in group 02 | Local speech recognition |
| DeepSeek / GPT / Claude / Gemini API | When translation is enabled | Translates text using your own account |
| Windows system voices | Optional | Local narration without Qwen |
| Qwen3-TTS 0.6B CustomVoice | Optional | Smaller local narration model |
| Qwen3-TTS 1.7B CustomVoice | Optional | Local narration with instruction-controlled lecture style |

**Translation currently uses the selected API. This guide deploys Whisper recognition and Qwen narration.** No local DeepSeek language model is needed. Translation requests contain required text, relevant terminology and bounded context; raw course audio stays local by default.

## 4. Whisper download and manual setup

If you extracted group 02, the model is already present. Otherwise, or to restore missing model files, double-click **Download-ASR-Model.cmd** in the ELT folder. Wait for confirmed success, then reopen ELT.

- [Publisher model page](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo)
- [Pinned revision files](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf)
- [Official Faster-Whisper project](https://github.com/SYSTRAN/faster-whisper)

The previous `mobiuslabsgmbh/...` model address redirects to `dropbox-dash/...`. Keep the validated revision and library combination. Files belong here:

```text
ELT/
  models/large-v3-turbo/
    model.bin
    config.json
    tokenizer.json
    preprocessor_config.json
    vocabulary.json
```

The model is about 1.62 GB on disk; this is not its GPU memory requirement. ELT needs CTranslate2 format. Renaming a Transformers weight file to `model.bin` does not convert it.

## 5. Optional Qwen narration

Qwen can speak Chinese and English; Aiden and Ryan are English voice options. Subtitles and API translation work without Qwen.

### Install the separate narration runtime

First install full **Python 3.12 x64**, including the Python launcher, from [Python's official Windows installer page](https://www.python.org/downloads/release/python-31210/). This additional prerequisite applies only to Qwen, not the basic application. Then double-click **Install-Qwen-Runtime.cmd** inside the extracted ELT folder. It creates **.venv-tts**, installs locked dependencies from PyPI and the official PyTorch index, and checks imports without upgrading the recognition environment. Reserve an additional 20 GB of disk space.

Installation is explicit and does not run when you launch ELT. Existing `.venv-tts` directories are never overwritten. Failed installations keep their incomplete directory and report failure. Rename an incomplete directory before retrying. An experimental embedded Qwen environment did not pass relocation imports; this release uses the full-Python environment instead. A complete fresh Qwen download/install has not been repeated for this release.

### Download one or both models

| Application shortcut | Official download |
|---|---|
| `Download-Qwen-0.6B.cmd` | [Qwen3-TTS 0.6B CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) |
| `Download-Qwen-1.7B.cmd` | [Qwen3-TTS 1.7B CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) |

The downloader includes the speech decoder and verifies large-file hashes. The pinned revisions are `85e237c12c027371202489a0ec509ded67b5e4b5` for 0.6B and `0c0e3051f131929182e2c023b9537f8b1c68adfe` for 1.7B. Each model plus decoder requires several GB; consult the actual download log.

```text
ELT/
  .venv-tts/Scripts/python.exe
  models/Qwen3-TTS-12Hz-0.6B-CustomVoice/
    model.safetensors
    config.json
    speech_tokenizer/...
  models/Qwen3-TTS-12Hz-1.7B-CustomVoice/   # optional
```

After installation and download, **reopen ELT**, choose the model, voice and GPU/CPU in Speech, and preview it. Initial loading takes time. CPU is supported but is not guaranteed to keep up with a lecture. Only the selected narration model is loaded. Whisper and Qwen share GPU resources; parameter count alone cannot establish total memory needs.

## 6. Checks and troubleshooting

- **Check-ELT.cmd** checks original package files, key imports and configuration isolation. It does not capture audio or make paid translation requests. Newly installed optional files are not considered original package contents.
- Missing `model.bin`: restore group 02 or use Download-ASR-Model.cmd.
- CUDA/cuDNN errors: restore group 03 and check your NVIDIA driver. Do not mix arbitrary DLL versions into the folder.
- Built-in player fails to open: install Microsoft WebView2 Runtime. Application audio remains a separate input path.
- Windows narration is silent: check the matching language voice, narration toggle and volume.
- Qwen is unavailable: install its separate runtime and a CustomVoice model, retain `speech_tokenizer`, then reopen ELT.
- API errors: check your own key, balance, network and model permissions. Source text should remain visible.
- Hugging Face is inaccessible: manually obtain the same revision from the publisher and preserve the directory structure. Never copy another person's credentials or browser sessions.

Compare assets against **SHA256SUMS.txt**, for example with PowerShell `Get-FileHash .\filename -Algorithm SHA256`. This preview is unsigned; Windows may display a trust prompt based on file origin and signing status. Do not disable system security protections.

Local relocation tests do not certify every computer, driver or one-hour workload. Consult the release notes for the actual validation scope.
