# ELT 空白便携分发包 — 2026-10-31

**历史记录：2026-11-03 用户要求只保留当前软件，下面所述的旧分卷、staging 和验证解压副本均已删除。当前本机 EXE 和原有环境保留；请勿将下面旧包的路径视为仍存在的交付文件。** 详情见 [CLEANUP.md](CLEANUP.md)。

**阶段：现有 M0–M3 实现的分发交付。** 打包已完成，完整 M3/MVP 验收状态保持未完成。

## 交付位置与启动

实际交付目录：`dist/ELT-20261031/packages/`。后来新增 EXE 入口补充包，目前 **17 个文件一起保留**，不要只复制第一卷：

1. 把所有文件放到同一个文件夹，双击 **一键解压.cmd**。
2. 脚本先检查四组压缩数据，再解压合并成旁边的 **ELT** 文件夹。若 ELT 已存在会停止，避免覆盖；自行改名后再解压。
3. 进入 ELT，双击 **ELT.exe**。需要桌面入口时，双击“创建桌面快捷方式.exe”。第一次自行设置 DeepSeek 密钥、主动启用中文；默认不开捕获、不保存字幕稿。

`05-EXE-Launcher.zip` 为后续追加的 **289,380 字节**启动器补充包，原四组模型/运行数据未重压。更新后的“一键解压.cmd”会一并合入它。已经解压旧版时，将该 ZIP 解压到原 ELT 文件夹的上一级并合并目录即可。EXE 只负责图形入口，资源继续放在完整目录中；本机桌面入口与便携版配置隔离规则见 [EXE_LAUNCHER.md](EXE_LAUNCHER.md)。

也可用 7-Zip 分别解压四组的 `.7z.001` 到同一目录。后续 `.002/.003/.004` 卷必须放在旁边，不改名、不单独解压。自带 `7za.exe`，正常使用无需另装解压软件、Python、Visual Studio 或虚拟声卡。

## 实际大小

| 分组 | 卷数 | 压缩字节数 | 内容 |
|---|---:|---:|---|
| 01-ELT-Core | 1 | 246,058,645 | 程序、Python 3.12.10、依赖、native helper、默认配置/词表、许可和启动器 |
| 02-ASR-Model | 4 | 1,460,375,830 | 已验证 revision 的 large-v3-turbo 权重及 tokenizer |
| 03-GPU-Runtime | 2 | 701,868,119 | CUDA 12.4 / cuBLAS、cuDNN 9.1 运行 DLL 和许可 |
| 04-VLC | 1 | 46,615,339 | VLC 3.0.24 及插件/许可 |
| **分卷合计** | **8** | **2,454,917,933** | 约 2.45 GB 压缩数据 |

首次交付的 16 文件共 2,456,264,989 字节；后续增加 EXE 补充包并更新说明，当前仍约 **2.46 GB**，实际大小以目录及 packages.json 为准。所有交付文件均已检查，**最大单卷恰为 390,000,000 字节**，低于十进制 400 MB 和 400 MiB。原始内容约 4.37 GB，解压建议预留至少 10 GB 空间。

`packages.json` 列出各卷大小和 SHA-256；`SHA256SUMS.txt` 包含交付文件摘要（自身除外）。保留 `先读我-解压与启动.txt`、`打包验证说明.txt`、`7-Zip-LICENSE.txt` 和 `Whisper-LICENSE.txt`。

## 空白与隐私边界

- 不包含 API Key、Windows 凭据、已保存字幕/录音、诊断日志、外观偏好、最近进程或课程测试材料。
- 应用文件按已知运行目录组装；移除 `.env`、`.jsonl`、`.srt/.vtt`、音视频、SQLite、缓存、editable 安装和本机 direct_url 元数据。正文审计未发现原工作区/用户路径或 key 样式材料。
- 分发版使用独立 profile 和 Windows 凭据目标，首次不会读取原版密钥或 DEEPSEEK_API_KEY 环境值。设置位于 LocalAppData 中独立 profile 下；这些资料没有进入压缩包。
- 原软件、原密钥、原字幕和原设置均保留。首次使用分发版须重新在 GUI 配置密钥，之后仍安全存到本机 Windows 凭据库，不写入软件目录。
- 只包含现有功能需要的模型；已延后的 Qwen/llama.cpp 不纳入运行包。Build Tools、下载压缩缓存、开发证据和测试音视频也不纳入。

## 验证结果

环境：现有 Windows 11 x64 10.0.26300、已验证 Python 3.12.10 和锁定依赖。没有升级 CUDA/cuDNN/CTranslate2。

| 检查 | 实际结果及证据 |
|---|---|
| 配置隔离、隐私筛选及原版回归专项 | **61 通过，0.20 秒**；[portable-focused-tests.txt](evidence/portable-focused-tests.txt) |
| 全量源码回归 | **435 通过、1 跳过，27.07 秒**；[portable-full-tests.txt](evidence/portable-full-tests.txt)；唯一跳过为需显式启用真实音频的 M0 smoke |
| 分卷与最终文件大小 | 8 卷，最大 390,000,000 字节；交付目录所有 16 文件均小于 400,000,000 字节 |
| 分卷 SHA-256 + 实际解压 | 四组均成功解压到 `verification/relocated-path/ELT`，解压时 CRC 通过；[验证汇总](../dist/ELT-20261031/verification-report.json) |
| 解压后逐文件 SHA-256 | **10,327 个内容文件通过**；[relocated-check.txt](../dist/ELT-20261031/verification-logs/relocated-check.txt) |
| 便携运行依赖与入口 | Python isolated=1；NumPy/SciPy、AV、ONNXRuntime、CTranslate2/Faster-Whisper、PySide6/QtSvg、pywin32、HTTPX、ELT 均从包内加载；CLI --help 成功，无原 venv 兜底 |
| 实际 GUI 离屏渲染 / 初始状态 | 窗口渲染通过，凭据不可用、翻译/存稿/捕获全关闭；[状态](evidence/portable-gui-smoke.txt)、[预览](evidence/portable-gui-preview.png)；未使用用户原凭据 |
| GPU 库可加载 | 自带 cudart/cuBLAS/cuBLASLt/cuDNN 核心 DLL 成功加载，当前设备实际检测到 1 张 CUDA 显卡 |
| 本地模型和 spawn 生命周期 | 独立 Python 实际创建 ASRWorker；CPU 显式 int8 请求、实际 int8_float32；加载 2.89 秒、1 秒合成静音预热约 7.07 秒，随后正确释放；[portable-model-smoke.txt](evidence/portable-model-smoke.txt) |
| 真实课程、付费 API、第二台干净 Windows | **未执行**；CPU 合成预热不是准确率、GPU 性能或课程端到端验收 |

初次迁移导入失败：Python 3.12.10 将 `_pth` 中终尾 `../..` 解析到错误层级，未找到 app。已最小复现、改为 Windows 原生分隔符 `..\\..`，重做包内导入及真实解压迁移验证；失败证据保留在 [初次导入日志](evidence/portable-runtime-imports.txt)，修正结果见 [portable-runtime-imports-fixed.txt](evidence/portable-runtime-imports-fixed.txt)。没有通过加入开发目录来掩盖问题。

## 使用条件和已知边界

需要 Windows 11 x64，GPU 识别需要兼容 CUDA 12 的 NVIDIA 显卡和驱动。显卡驱动及 Windows 系统组件不随应用复制或安装。当前验证为同机从新路径运行，没有另一台干净 Windows 主机的完整实测；不承诺所有设备、混合 DPI 或全屏方式通过。

全量测试、迁移校验与模型初始化不能替代原计划的 30/60 分钟、工科质量及真实服务异常验收。这些事项没有因打包标成完成。没有新增付费调用、音频采集或录音。

## 构建维护

主要新增/修改：`app/profile.py`、凭据和偏好命名空间；`tools/build_portable.py`、`check_portable.py`、`check_portable_model.py`、`verify_portable_release.py`；隔离/打包测试和文档。现有开发版启动脚本未覆盖。

构建器只允许新的 `dist/` 子目录，拒绝覆盖现有输出。7-Zip 26.05 从[官方发行页](https://www.7-zip.org/download.html)获取，并核对 GitHub release digest；第三方原许可保留。Python 隔离参考[官方 _pth 文档](https://docs.python.org/3.12/library/sys_path_init.html)，MSVC 本地 DLL 部署参考[微软文档](https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files)。

```powershell
.\.venv\Scripts\python.exe tools/build_portable.py --output dist/新的发行目录 --sevenzip .tmp/package-tools/extra/x64/7za.exe
.\.venv\Scripts\python.exe tools/verify_portable_release.py --release dist/新的发行目录
```

`staging/`、`verification/` 和 `build-logs/` 是本机组装与验证目录，**只需分享 packages 目录的交付文件**。
