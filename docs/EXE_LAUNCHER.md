# EXE 入口和桌面快捷方式 — 2026-10-31

2026-11-03 清理后，本机 `ELT.exe` 和桌面入口继续可用；下文提到的旧便携分卷及 EXE 补充 ZIP 已删除，仅保留历史验证说明。详情见 [CLEANUP.md](CLEANUP.md)。

已完成用户要求的本机 EXE 启动方式。用户明确不要求把模型和库全部塞进单个文件，并反馈“使用得很顺利”。这次不扩展 M3 长测范围。

## 直接使用

- 桌面双击 **ELT 工科实时字幕**。真实快捷方式位于当前用户桌面，目标为项目根目录 `ELT.exe`，工作目录和图标均指向本项目。
- 也可双击根目录 **ELT.exe**。启动不调用 cmd.exe，应用按原有方式显示窗口。
- 要重新建立快捷方式，双击同目录的 **创建桌面快捷方式.exe**。同目标只更新自己的快捷方式；遇到同名的其他目标会加序号，不覆盖无关图标。
- 模型、运行库和程序目录继续保留。不要只把 ELT.exe 拿走；移动程序目录后可重新创建快捷方式。

本机入口使用现有 `.venv`，保留原来的默认密钥和设置位置。便携目录存在 distribution.json 时，入口使用 `runtime/python`，采用经过验证的独立 profile，不继承外部 DeepSeek key；继续满足空白分发要求。没有将本机密钥、字幕或设置打进 EXE。

## 实现与验证

采用 C++20 / MSVC 19.44 / Windows SDK 10.0.26100 编译，Windows GUI subsystem（PE Subsystem=2）；2026-11-03 图标更新后的入口文件为 **339,968 字节**。静态链接启动器自身 CRT，内嵌 ELT 图标和版本信息；直接通过 CreateProcessW 启动 Python 图形入口，路径含空格时正确引用，无命令解释器。IShellLinkW / IPersistFile 和当前用户 Known Desktop Folder 创建真正的 Windows .lnk，支持系统重定向桌面位置。

| 检查 | 结果 |
|---|---|
| 原生 Release 编译 | 成功；[exe-launcher-build.txt](evidence/exe-launcher-build.txt) |
| PE 类型 | x64 / Windows GUI subsystem=2，不是改扩展名的 CMD |
| 本机实际控件启动 | 成功，默认配置命名空间，未启动捕获/翻译；[exe-local-startup.json](evidence/exe-local-startup.json) |
| 便携目录启动 | 自带 Python / isolated=1，独立 profile；[exe-portable-startup.json](evidence/exe-portable-startup.json) |
| 未设环境密钥的便携启动 | 成功；[exe-portable-no-env-key.json](evidence/exe-portable-no-env-key.json) |
| 桌面快捷方式 | 已创建并用 Shell COM 读回目标/工作目录/图标；[exe-desktop-shortcut.json](evidence/exe-desktop-shortcut.json) |
| 原生错误路径 + 界面回归 | **28 通过，1.46 秒**；[exe-launcher-tests.txt](evidence/exe-launcher-tests.txt)，含缺运行环境、坏 profile、超大配置、未知参数 |
| 用户使用反馈 | 用户已确认“使用得很顺利”；不把反馈等同于正式准确率或长测数据 |

启动检查使用真实 Qt 控件离屏初始化，不注入模拟字幕，不调用 ASR/翻译服务；桌面图标在用户明确授权后真实写入。没有覆盖原凭据或字幕。正式的 30/60 分钟、全屏/多屏和质量验收保持原状态。

## 旧便携分发包

已追加 `dist/ELT-20261031/packages/05-EXE-Launcher.zip`，**289,380 字节**，内容为 ELT.exe、创建桌面快捷方式.exe 和 EXE 使用说明。ZIP 已实际解压/CRC 检查通过。原八个大分卷无需重新下载或重压，更新后的“一键解压.cmd”会一并合入补充包；日常启动改用 ELT.exe。交付目录现为 17 文件，SHA256SUMS 和 packages.json 已更新，仍全部低于 400 MB。

已解压的旧版本可把 ZIP 解压到原 ELT 文件夹的上一级，合并 ELT 目录。补充包不带个人资料；它会在该目录采用已有的便携 profile。

## 构建维护

`native/launcher/` 包含源码、CMake、资源与 ICO；图标源文件为 `app/ui/assets/elt.svg`。`tools/build_launcher.py` 从 SVG 生成多尺寸 ICO、编译并放置本机入口及快捷方式工具。窗口、应用默认图标、左上角标识使用同一设计；Python wheel 资源配置包括 SVG 和 ICO。

```powershell
.\.venv\Scripts\python.exe tools/build_launcher.py
```

此入口不是把多 GB 资源冻结成单文件；它保留原有多进程/路径架构，无需每次启动先解压模型。官方依据：[CreateProcess](https://learn.microsoft.com/windows/win32/procthread/creating-processes)、[Shell Links](https://learn.microsoft.com/windows/win32/shell/links)、[Known Folder Path](https://learn.microsoft.com/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath)。

## 2026-11-03 图标重设计

蓝紫渐变圆角底板、白色声波对话框和青色字幕对话框表达本地语音识别与双语字幕。图形不依赖字体；同一 SVG 导出 16、20、24、32、40、48、64、96、128、256 共 10 个尺寸，避免只使用一张大图缩放。见[图标预览](evidence/icon-current.png)、[小尺寸检查](evidence/icon-sizes.png)、[当前界面](evidence/icon-ui-current.png)。

桌面快捷方式的目标仍为根目录 ELT.exe，IconLocation 更新为当前 `app/ui/assets/elt.ico`；缺少 ICO 时回退 EXE 内嵌图标。只更新同目标的本软件快捷方式，并发送单项 Shell 更新通知，没有清空系统图标缓存、重启 Explorer 或修改其他桌面图标。程序已在运行时，重开后载入新窗口图标。

真实 MSVC 构建通过；从编译后的 PE 资源读取并核对 10 个尺寸，与 Qt ICO 解码一致。桌面快捷方式目标/图标/工作目录读回通过，真实 EXE 的 Qt 主窗口启动检查通过，未开始音频或付费翻译。既有 GUI/启动器相关测试 **14 通过（22.31 秒）**。证据：`icon-build.txt`、`icon-resources.json`、`icon-desktop-shortcut.json`、`icon-exe-startup.json`、`icon-tests.txt`，均位于 docs/evidence。未重新打包已删除的旧便携分卷。
