# 交互界面初版验收记录 — 2026-10-30

**阶段：M3 的界面初版，用户追加授权；完整 M3/MVP 未验收。** M2 的真实 DeepSeek、语义质量和中文延迟仍未执行；用户已选择本轮无密钥测试。

以上及下文保留初版的验收历史。用户随后已反馈密钥保存及浏览器实时翻译可用，并授权后续 M3；多条字幕、较小字号、长宽、穿透/恢复、偏好及性能统计的最新实现与测试见 [M3_ACCEPTANCE.md](M3_ACCEPTANCE.md)。下文“没有鼠标穿透/颜色设置”等是初版当时状态。

## 实际交付

原生 PySide6 桌面界面，VLC 自动发现/显式多实例选择、语言/时长选择、真实后台开始/停止、本地原文与可选流式中文显示、Preview/Final/前段译文状态、有界最近字幕和诊断、置顶可移动/缩放字幕窗、字号与透明背景、隐藏输入密钥设置入口。启动不会自动捕获、请求 API 或保存课程录音。

主要文件：app/ui/{main,window,controller,protocol,lifetime,runner}.py；启动ELT.cmd；pyproject.toml 的 gui-scripts；requirements-ui-lock.txt。既有 CLI/source/pipeline 增加 source-only、选定进程创建时间保护及真实音频连接就绪事件。tests/unit/test_ui_*.py、tests/integration/test_ui_lifecycle.py；tools/gui_live_checks.py 和 tools/render_gui.py 为显式测试工具，不被生产流程调用。

## 已执行测试与证据

| 检查 | 实际结果 | 证据/含义 |
|---|---|---|
| 界面接入后的完整自动回归（当时版本） | 203 通过，1 跳过，16.87s | evidence/gui-unit-tests-v2.txt；跳过为显式 M0 实机 smoke 未启用 |
| 最终界面相关自动测试 | 17 通过，13.57s | evidence/gui-delivery-tests.txt；消息边界、旧版本/Final、防 HTML 注入、控件/字号/背景、多实例/重启、真实就绪与错误显示、原文云端边界、过期 PID；compileall 亦通过 |
| Windows Job 实际进程清理 | 通过，包含在上述 17 项 | 真实启动测试后台及后代，关闭 GUI 所有权句柄后两者结束；不等同于真实 VLC/GPU 整链强杀验收 |
| 本地安装及 GUI entry point | 成功 | evidence/gui-editable-install-v2.txt；.venv/Scripts/elt-gui.exe 已生成 |
| 实际控件离屏渲染/布局检查 | 完成；1100×810，字体 21pt | evidence/gui-preview-final.png；无伪字幕，使用等待状态；离屏预览不是桌面音频验收 |
| GUI→VLC→GPU、暂停恢复、停止/加载中取消 | 未完成验收 | gui-live-v1/v2/v3 均在 VLC RC 启动前失败，stderr 留存；没有真实字幕结果，不能记为通过 |
| 最终完整回归重跑 | 环境阻塞，已停止 | 当前会话的 asyncio 初始化卡在 socket._fallback_socketpair.accept；先前 203 项结果只代表当时版本，不能当作最终全量回归 |
| 当前用户桌面自动打开/点击 | 未完成 | Computer Use launch_app 返回 “Computer Use app approval timed out”；没有绕过授权或声称已为用户打开 |
| 真实 DeepSeek、中文双语显示/质量/延迟 | 未执行 | 用户本轮不配置密钥；未发真实翻译请求，无模拟中文接入界面 |

测试环境为本机 Windows/Python 3.12.10、PySide6 6.8.3；当前工具运行在隔离 Windows 会话（实测 session 12、只能枚举自身进程），不具备与用户桌面相同的本机回环连接/音频环境。VLC 控制接口不能连接；asyncio IOCP 初始化所需的回环 socketpair 也卡在 accept。原有 M0/M1/M2 真机证据保留，不能替代本轮 GUI 链路验证。没有为通过测试而修改生产事件循环、插入假字幕或关闭安全设置。

原始自动测试首次因系统临时目录权限报错，改用工作区内 --basetemp 后通过 203 项；原失败日志 evidence/gui-unit-tests.txt 保留。之后补充的 CLI 边界单元测试使用立即返回的测试协程执行器，不测试 asyncio/IOCP；Windows Job 集成测试使用真实进程，没有模拟清理。

完整回归的 203 项与最终定向测试 17 项存在重叠，不能相加作为不同测试总数。

**性能数据：** 本轮没有可报告的真实字幕端到端延迟、GUI 渲染延迟或持续播放时长。自动测试耗时仅为测试运行时间。没有新的准确率或低延迟结论。

## 用户在正常 Windows 桌面验收

1. 双击根目录“启动ELT.cmd”或“.venv/Scripts/elt-gui.exe”。窗口应正常显示中文，打开时没有捕获、模型加载或 API 调用。
2. 点击“打开 VLC”，载入有声课程并暂停。回到 ELT，单实例应自动选中，多实例应要求选择；选英语或德语，不勾中文，点击“开始字幕”。
3. 模型就绪后仍等待连接；出现“音频连接已就绪，现在可以继续播放 VLC”才继续播放。应出现真实原文和识别耗时；未启用中文时无译文、无 API 请求。
4. 勾选置顶字幕窗；移动顶部、拖右下角、调字号和背景。点击“最近字幕”查看已收到的原文。其他软件的音频不应进入字幕；正式隔离仍需按 M0 的双音频谱方法验证。
5. 暂停 VLC 3 秒后恢复，确认没有崩溃且字幕继续；播放中关闭 VLC，确认明确提示目标退出；重开 VLC 并重新选择后可再开始。
6. 点击“停止”，等待状态结束，确认没有残留 elt_capture/ASR 子进程；连续 10 次开始/停止。模型加载中点击停止、运行中关闭 ELT，也应完成清理，无死锁。20 秒期限触发强停时应明确提示未完成。
7. 中文验收另行由用户本人设置有效密钥，主动启用翻译，检查网络失败原文继续、版本/Final 对应。不能将“密钥已配置”当成服务已验证。
8. 分别测试 VLC 普通/最大化/全屏、高 DPI/多显示器，再执行 30 分钟延迟及 60 分钟稳定性；当前均待执行。

正常终端可运行以下复现检查（输出目录必须不存在；第一条会启动可听的测试 VLC，结束后关闭测试播放器）：

```powershell
.\.venv\Scripts\python.exe tools/gui_live_checks.py --output 'D:\MyTests\new-gui-live'
.\.venv\Scripts\python.exe -m pytest -q --basetemp .test-tmp/gui-full
.\.venv\Scripts\python.exe tools/render_gui.py --output 'D:\MyTests\new-idle-preview.png'
```

诊断与字幕在内存中有界保留；不默认写磁盘。需要排查时使用界面“诊断详情→导出诊断”，保存到指定新文件。当前没有单文件安装包、鼠标穿透、字体颜色选择或已验证的全屏兼容保证。

本次到交互界面初版停止。下一步先完成上述真实桌面链路和 M2 真服务验收，再继续完整 M3 性能及兼容性工作。

## 双击启动修复

用户反馈双击无法打开后，在真实 cmd.exe 中复现了启动脚本命令截断（例如 `n.exe" -c "import` 被识别成独立命令）。原文件为 UTF-8/LF、0 个 CRLF；脚本因此在启动 GUI 前退出，返回 1。已改为纯 ASCII 命令内容和 Windows CRLF，增加 .gitattributes 防止后续检出改变换行；导入失败分支会显示实际错误并保留窗口。

使用相同的 `cmd.exe /d /c .\启动ELT.cmd` 复测，退出码为 0，不再出现命令截断。该结果验证的是启动入口；当前隔离会话内启动的窗口不能视为用户桌面上的可见性验收，也不改变真实 VLC/GPU 联动的待验收状态。新增 Windows cmd.exe 缺失环境错误分支及文件格式回归测试，结果另见 evidence/gui-launcher-fix-tests.txt。

## 密钥保存修复

用户反馈保存密钥失败后，复现到 pywin32 312 参数转换错误：原代码将密钥预编码成 UTF-16-LE bytes 传给 CredWrite，绑定在调用 Windows 前即抛出 TypeError（bytes 不能转换为 Unicode）。已改为传 Python str，由 pywin32 编码；CredRead 返回的 bytes 仍按 UTF-16-LE 解码。[对应版本源代码](https://github.com/mhammond/pywin32/blob/b312/win32/src/win32credmodule.cpp)、[PyCREDENTIAL 字段文档](https://mhammond.github.io/pywin32/PyCREDENTIAL.html)均明确此输入类型。

同时修正界面将所有异常都显示成“请检查格式”的问题：只传递安全的分类和数字 Windows 错误码，区分格式、凭据访问失败和组件异常。若写入已成功但后续读取验证失败，明确显示“已写入，但读取验证失败”，不误称输入格式错误。原始异常文本、密钥及 HTTP 请求不进入此错误展示流程。

相关自动回归 **33 通过，13.97s**，见 evidence/credential-fix-tests.txt；包含 Unicode 写入/UTF-16 字节读取的测试替身、格式校验、错误码/秘密不泄露、线程池→GUI 成功/失败、启动文件格式，以及真实 pywin32 参数转换。原生接口测试使用独立随机诊断目标和故意无效 flags，验证新参数进入 Windows、旧 bytes 在转换处失败；不会写入或覆盖用户的实际密钥。测试退出后 pyreadline3 曾输出非致命 Console 析构异常（无效测试控制台句柄），测试退出码仍为 0；没有将其当作实际凭据保存结果。

当前工具会话读取应用指定凭据返回 Windows 错误 5，无法代替用户正常桌面的凭据库写读验收。**没有用用户密钥进行保存测试或发送 DeepSeek 请求**，也不以 Mock 成功宣称真实保存通过。用户须关闭并重新打开 ELT，重新粘贴后保存；如仍失败，可提供界面显示的错误码，不需要提供密钥。

原有配置、术语和凭据安全回归另 **22 通过，1.16s**，见 evidence/credential-existing-tests.txt；与上述 33 项合计 55 项相关自动测试，并非全量/真实凭据库验收。此组结束时也出现相同的 pyreadline3 无效控制台句柄析构提示；compileall 通过。
