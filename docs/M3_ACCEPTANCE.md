# M3 界面功能及短测报告 — 2026-10-30

2026-11-03 多来源密钥/API选择追加：四来源独立存储、模型记忆、异步状态隔离及会话固定来源已接入；全量775通过、1项现场音频测试未启用。真实Qt来源/模型/密钥弹窗布局与EXE入口通过；新协议使用本地HTTPX/SSE测试，不等于真实账号、费用或质量验收。DeepSeek原密钥/费用兼容，其他来源读实际Token而金额未估算。见 [MULTI_PROVIDER_TRANSLATION.md](MULTI_PROVIDER_TRANSLATION.md)。

2026-11-03 焦点历史追加：回看不被新句打断，底部按钮恢复实时/自选焦点，保留最多128条。全量677通过、1项现场音频测试未启用，最后布局专项57通过；Qt渲染/实际按钮点击12项及EXE入口检查通过，不代替实际触控板/多显示器或长测。见 [FOCUS_HISTORY.md](FOCUS_HISTORY.md)。

2026-11-03 翻译顺序追加：焦点/列表等待前句，补齐后保留阅读时间；实时原文继续，重试/终止失败可区分。全量661通过、1项现场音频测试未启用，最后提示专项75通过；本地HTTPX/SSE乱序响应、真实Qt布局和EXE入口通过。上下文裁剪与超时诊断一并更新，真实服务故障根因仍未确认。见 [TRANSLATION_CONTEXT_AND_ORDER.md](TRANSLATION_CONTEXT_AND_ORDER.md)。

2026-11-03 追加焦点拖动/暂停/超时原文保留/悬窗基础语速：最终全量624通过、1项旧现场音频测试未启用（44.57秒）；专项97通过。真实进程收音三次暂停/继续、暂停停止及目标退出通过；真实Qt排版/动画和EXE入口通过。模型联合推理、付费服务真网故障及长测未执行。当前操作与证据见 [FOCUS_PAUSE_AND_RECOVERY.md](FOCUS_PAUSE_AND_RECOVERY.md)，以下保留各批次历史结果。

2026-11-03 新增日语到中文：UI/CLI、识别语言策略、两种翻译模式、文本拼接及存稿命名已接入；全量 528 通过、1 项音频 smoke 未启用。没有执行真实日语音频/DeepSeek 质量和延迟验收，既有 M3 待执行项保留。见 [JAPANESE_SUPPORT.md](JAPANESE_SUPPORT.md)。

**阶段：M3。** 本轮交付界面功能与短测；完整 M3/MVP 尚未验收。用户已反馈浏览器实时翻译“效果很好”，随后授权继续，并要求多句字幕、更小字号和悬浮窗长宽。用户明确选择“先完成功能和短测，长测留到空闲时”，因此本轮没有启动 60 分钟 GPU 测试。

2026-10-31 已按用户要求制作空白便携分发包，四组共 8 卷，最大 390 MB，实际解压迁移和 10,327 个文件摘要校验通过；当前源码全量回归 435 通过、1 跳过。该交付不把 M3 长测、全屏/多屏或真实服务验收标为完成，见 [PORTABLE_PACKAGE.md](PORTABLE_PACKAGE.md)。

2026-10-31 追加 Token 明细与预计费用显示：每次请求按真实返回用量累计，重试/取消/重复及未知用量有回归，峰谷/缓存不确定时显示费用区间。最新完整回归 **412 通过、1 跳过**；没有发送真实付费请求或做长测。说明、官方价格依据和剩余验收见 [USAGE_AND_COST.md](USAGE_AND_COST.md)。

2026-10-31 用户随后要求美化界面。最新统一主题、课程/翻译/存稿页签、字幕分区及工具栏交付见 [UI_POLISH.md](UI_POLISH.md)：完整回归 **374 通过、1 跳过**，离屏布局预览已检查，Python wheel 及 SVG 资源打包验证通过。该结果不代表新增真实音频、翻译质量或长测通过。

2026-10-31 追加可选的每次翻译稿自动保存：首次选择目录、保存偏好、每会话双语 TXT、日期/语言/整分钟命名、重名保护。完整回归 **373 通过、2 跳过**；最后的设置入口滚动调整后界面专项 **5 通过**。测试证据、未执行的真实音频验收及使用步骤见 [TRANSCRIPT_SAVING.md](TRANSCRIPT_SAVING.md)。以下历史报告保留当时结果，不作为新功能的真实 ASR/服务实测。

后续用户授权的“整句后调用 DeepSeek、原文实时”模式已交付；最新回归为 320 通过、2 跳过，详细请求数对照、操作和限制见 [SENTENCE_TRANSLATION.md](SENTENCE_TRANSLATION.md)。下文保留此前多句字幕交付的原始测试记录。

后续焦点显示交付见 [FOCUS_DISPLAY.md](FOCUS_DISPLAY.md)：已按用户澄清实现旧句上推、无淡出；最新完整回归 337 通过、2 跳过，Windows 原生动画帧短测通过。下方仍为原始多句字幕记录，不能混为当前端到端音频/质量验收。

## 本次完成

- 悬窗按时间显示最近 1–12 条字幕，默认 4 条，原文/中文成对。复用片段行、更新既有版本，较早请求完成不跳回旧句；新会话清空旧内容。条数是字幕片段数量，长句可能换行，空间不足可滚动。
- 字号滑块及数字框均为 6–72 号，支持较小字；外观对话框可选字体、原文/中文/背景颜色、不透明度、条数以及宽高。宽度 280–8000、高度 120–8000，单位为 Qt 逻辑像素，显示/恢复时适配可用屏幕。
- 顶部拖动、右下角缩放；鼠标穿透、可见恢复按钮、Ctrl+Alt+E 恢复编辑、Ctrl+Alt+S 显示/隐藏。隐藏/关闭恢复可编辑，穿透不持久保存。快捷键占用会提示，不装键盘钩子。
- 有界本机偏好原子保存，重启恢复外观、窗口位置、语言、音源类型、时长和翻译术语表路径。不会自动捕获、自动开启中文翻译或保存 PID/字幕/密钥。
- GUI 翻译术语表选择与 CLI `--glossary`，只影响翻译，ASR 热词仍关闭。
- 性能窗口分别显示识别、排队、核心文本可用、HTTP 请求、Qt 文字绘制，包含 P50/P95、样本数、队列、显卡总占用和已报告 Token。每项最多 512 个样本；诊断可手动导出，默认不保存音频/字幕/诊断。
- 主窗口和设置区支持滚动，防止较小可用区域隐藏操作按钮。

## 主要修改文件

| 范围 | 文件 |
|---|---|
| 字幕渲染/交互 | `app/ui/overlay.py`、`app/ui/window.py` |
| 外观与偏好 | `app/ui/appearance.py`、`app/ui/preferences.py`、`app/ui/main.py` |
| 快捷键、生命周期 | `app/ui/hotkeys.py`、`app/ui/controller.py` |
| 性能统计 | `app/diagnostics/runtime.py` |
| 术语表传入 | `app/main.py`、`app/translation/cli.py` |
| 自动验证 | `tests/unit/test_ui_m3_features.py`、`test_ui_preferences.py`、`test_runtime_metrics.py`、`test_ui_cli_guards.py`、`test_ui_browser_flow.py`；`tests/integration/test_native_hotkeys.py`、`test_native_overlay_input.py` |
| 人工/实机工具 | `tools/check_overlay_native.py`、`tools/gui_live_checks.py` |
| 文档 | README、ARCHITECTURE/ARCHITECTURE_UI、DEVELOPMENT_PLAN、DECISIONS、本报告 |

## 测试结果

环境：Windows 11 x64 10.0.26300、Python 3.12.10、PySide6 6.8.3、pytest 8.4.2，沿用项目既有依赖。没有更换 GPU/CUDA 组合。原生音频模块本轮未修改；上一轮构建和 3 项 native 测试保留原证据。

| 检查 | 实际结果 | 证据/边界 |
|---|---|---|
| 最终全量 Python 回归 | **296 通过、1 跳过，14.15 秒** | [m3-final-tests.txt](evidence/m3-final-tests.txt)；跳过为需显式启用并播放音频的 M0 硬件 smoke |
| 多条身份/顺序、旧行更新、字号 6、数值宽高、偏好恢复及安全边界 | 通过 | 全量测试中的 `test_ui_m3_features.py`、`test_ui_preferences.py`；测试替身仅在 tests 中使用 |
| 64 位 QPC paint、统计边界、版本对齐、来源/网络/界面计时分开 | 通过 | `test_runtime_metrics.py`、CaptionLabel 绘制回归，不含真实语音质量判断 |
| 真实 Windows WM_HOTKEY 单次消费及注销 | 通过 | `test_native_hotkeys.py` 在独立 Windows Qt 子进程测试；[hotkey bridge](evidence/m3-hotkey-bridge-fixed.txt) 注册成功并各消费一次 |
| 穿透开/关后多次真实原生重绘 | 通过 | `test_native_overlay_input.py`；逐次检查自有窗口 WS_EX_TRANSPARENT，Qt 输入 flags 保持清除 |
| 实际点击穿过字幕窗、Ctrl+Alt+E 恢复 | 通过 | [native input state](evidence/m3-native-input-delivery/state.json)：下层计数由 0→1，状态 true→false，恢复后原生输入 bit 清除 |
| 恢复后实际拖动右下角缩放 | 通过 | 同一 state，窗口从 720×260 变为 **605×220**；行仍保留 4 条，放不下可滚动 |
| 实际顶部移动 | 通过 | [native drag state](evidence/m3-native-drag-delivery/state.json)：同一工具初始 (663,524) 移至 **(743,559)**，尺寸保持 720×260 |
| 主窗口排版预览 | 已检查 | [预览](evidence/m3-main-preview-final.png)；为布局检查，不是实时翻译截图 |
| 项目 Python 编译检查 | 通过 | `compileall -q app tests tools/check_overlay_native.py tools/gui_live_checks.py`；只检查项目源码，不编译第三方 Build Tools 安装目录 |
| 35 秒真实 VLC→GUI 多字幕短测 | **未通过准备阶段** | [失败原文](evidence/m3-live-local.console.txt)：`VLC RC interface did not start`，尚未进入捕获/模型运行；不能算真实音频通过，也不能据此判定生产捕获失败 |
| 真实 DeepSeek 请求/工科语义质量、网络异常实测 | 未执行 | 本轮没有使用用户密钥或发送付费请求；既有 Mock 网络/乱序/失败测试不代替真实服务验收 |
| 30 分钟延迟、60 分钟稳定性 | 未执行 | 按用户选择留到空闲时 |
| 混合 DPI/真实多显示器、VLC 普通/最大化/全屏 | 未执行完整验收 | 位置恢复算法有自动测试；不能宣称所有全屏模式兼容 |

原生输入测试工具明确显示“排版测试文字，不是语音识别或翻译结果”，不连接音频、ASR、凭据或 API。该工具的真实点击/几何变化只证明窗口交互，不能证明捕获或翻译质量。所有本轮测试窗口已退出，`stopped.json` 留有清理标记；没有停止用户自己的 ELT/浏览器。

## 性能数据

本轮测得全量测试耗时 14.15 秒，以及上述实际窗口几何变化；未获得新的语音端到端延迟、WER、翻译质量或 GPU 长时间稳定性数据。性能面板没有数据时显示“—”，不填入目标值。Qt paint 为文字完成绘制，不等于显示器刷新；首条中文只统计音频时间/版本可对齐的记录。

原生短测发现并修复 Qt 透明输入标记在恢复后重绘仍生效的问题；顶部 startSystemMove 在该自动化会话未产生移动，改为有界鼠标拖动状态并实际复测。细节与依据见 [D021–D023](DECISIONS.md#d021--多条字幕用既有片段身份复用控件)。

## 已知问题及边界

- 真实 VLC 自动验收工具的 RC 控制接口在本轮环境未启动，失败证据保留；尚未完成本轮新界面与真实音频的自动联动复测。用户浏览器使用反馈与该失败分开记录。
- 字幕数量按核心分段，不保证一条等于完整句。当前窗口高度/字号决定同时可见的行数，超过可用区域时滚动，不删除正文或重写输出。
- 多显示器/混合 DPI 及全屏硬件兼容性、30/60 分钟和人工质量验收仍待执行，当前不是完整 MVP 完成。
- 全局快捷键可能被其他应用占用或另一个 ELT 实例先注册，使用主窗口恢复按钮即可；占用不伪装为注册成功。

## Windows 验收步骤

1. 完全退出旧 ELT，双击项目根目录 `启动ELT.cmd`。在 VLC/Chrome/Edge 暂停课程，选择音源/语言，主动勾选中文，点击开始；音频就绪后继续播放。
2. 勾选置顶字幕，等待产生几个不同片段。确认多条原文与各自中文成对保留，改最近条数 2/4/8 检查顺序；确认新译文仍对应原文，较早的完成事件不会跳回旧句。
3. 将字号设为 6、12、16、32，确认确实变小/变大；建议先用 12–16。打开“外观 / 长宽”，设为 900×420 或适合屏幕的尺寸，点击应用；试字体、颜色，再拖右下角缩放、顶部移动。
4. 勾选鼠标穿透，点击下面的视频控件；按 Ctrl+Alt+E 或主窗口恢复按钮，确认可再次移动/缩放。Ctrl+Alt+S 隐藏/显示。关闭并重开 ELT，确认外观恢复且未自动捕获/启用中文/穿透。
5. 在性能统计中观察真实运行样本；暂停、恢复、停止并重新开始，检查旧字幕被清空，诊断中错误明确；需要留证时自行导出到新文件。
6. 空闲时再单独执行 30/60 分钟、显示器/DPI/全屏及真实服务异常、工科质量验收。当前不以短测替代这些项目。

开发者可复验（输出目录必须为新目录；窗口工具只做排版/输入检查）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --capture=sys --basetemp .test-tmp/m3-new
.\.venv\Scripts\python.exe tools/check_overlay_native.py --output docs/evidence/my-new-overlay-run
.\.venv\Scripts\python.exe tools/gui_live_checks.py --output docs/evidence/my-new-live-run
```

最后一个命令会创建自己的 VLC 并播放本地公开样本，默认不启用中文翻译；需要正常用户桌面和可用 RC 接口，失败时保留错误，不会改用测试文字冒充语音。

## 下一阶段建议

先由用户确认新版多句/较小字号/长宽交互是否符合阅读习惯，再在空闲时完成剩余 M3 长测及显示验证。保留既有 M1/M2 质量限制，不自动扩展到课程总结、笔记、账户或其他新功能。
