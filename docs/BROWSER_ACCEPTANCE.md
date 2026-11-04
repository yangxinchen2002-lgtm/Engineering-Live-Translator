# Chrome / Edge 音频捕获增量 — 2026-10-30

用户明确要求直接播放网页视频并实时翻译。本次扩展既有进程级音源选择和原生捕获，接入同一 M1/M2 流程；不是浏览器扩展，没有添加系统音频回退或虚拟声卡，也不宣称完整 M3/MVP 验收完成。

后续用户已反馈实际浏览器翻译“效果很好”并授权继续 M3；这是用户使用反馈，尚无正式质量/延迟数字。下文保留开发自动验收的失败边界，最新多条悬浮字幕和界面短测见 [M3_ACCEPTANCE.md](M3_ACCEPTANCE.md)。

## 实现

- GUI 新增 VLC / Chrome / Edge 音频来源切换、对应进程列表、捕获范围提示和动态就绪/退出状态。启用中文的勾选框固定在开始按钮上方。运行中禁止切换音源，切换后丢弃旧来源的迟到发现结果。
- ProcessSelector 读取进程快照和可见顶层窗口的所属 PID，确认 chrome.exe / msedge.exe 的浏览器窗口所属进程；不读取网页标题、URL、命令行或浏览历史。普通被遮挡/最小化窗口仍可具有 WS_VISIBLE；无桌面窗口的后台进程不作为浏览器来源。
- Python 在发现、开始会话和实际捕获时核验进程身份；native 按显式 source 校验实际可执行文件名，并验证创建 FILETIME。CLI 默认 VLC，浏览器必须使用 --source chrome/edge；拒绝 system、mic、其他程序和 WebView2。
- 原生仍使用 INCLUDE_TARGET_PROCESS_TREE，PCM 协议不变，started 状态增加 source/scope。目标退出、STOP、队列/数据完整性和资源释放沿用真实实现。
- 浏览器音频服务可能位于子进程，选择浏览器窗口所属主进程捕获整棵树，覆盖该树的窗口/标签页；没有单标签页保证。原始音频不上传，ASR 课程提示仍关闭，中文仅在用户主动启用后发送有限文字给 DeepSeek。

主要文件：app/audio/processes.py、capture.py；app/main.py、asr/cli.py、translation/cli.py；app/ui/controller.py、window.py；native/audio_capture/main.cpp、source_policy.h、source_policy_test.cpp；对应 browser 单元/集成测试。没有增加生产第三方依赖。

## 已执行结果

| 项目 | 实际结果与证据 |
|---|---|
| 原生 Release x64 构建 | 成功，新 elt_capture.exe 已更新；evidence/browser-native-build.txt |
| 原生测试 | 3/3 通过，含来源策略/跨程序拒绝；同上 |
| 第一轮完整 Python 回归 | 254 通过、1 跳过，17.34s；evidence/browser-full-tests.txt |
| 加入窗口归属/孤儿进程防护后的最终完整回归 | **257 通过、1 跳过，12.37s**；evidence/browser-final-tests.txt。跳过为显式 M0 实机 smoke 未启用 |
| 真实 native 参数/可执行文件保护 | Python 集成测试实际运行 helper，拒绝以 Python 进程充当 VLC/Chrome/Edge，拒绝 system 来源；属于上述全量测试 |
| GUI、异步切换及 CLI 路由 | 有自动测试，含旧发现结果迟到/失败、多实例、进程身份变化、浏览器 source 传递及本地模式不读凭据/不创建云端客户端 |
| 正常 Windows 进程发现 | 成功发现用户桌面的 Chrome 和 Edge 窗口所属主进程；隔离执行环境下的空列表未当作浏览器未运行 |
| 控件布局 | Chrome 模式实际控件离屏预览已检查；不把等待状态预览当成音频捕获成功 |
| 真实浏览器音频 / 音源隔离 / GPU 转写 | **未完成**。独立 Chrome 测试窗口和全新测试 profile 已启动并确认身份，但 Computer Use 在读取本地测试页面时因无法可靠判断当前浏览器 URL 而停止；没有点击播放，没有录制音频或取得真实转写结果。独立测试浏览器已停止，用户原窗口未关闭 |
| DeepSeek / 中文质量、端到端延迟、长时间稳定性 | 未执行，未使用用户密钥发送任何真实翻译请求 |

Computer Use 返回：“Computer Use has been stopped for this turn because it could not determine the current browser URL on Windows with enough confidence to enforce policy.” 已停止浏览器操作，未尝试绕过检查。Playwright CLI 前置所需 npm/npx 不可用，因此没有额外安装或以其绕过该限制。

自动测试存在 Mock：它们仅在 tests 内验证边界、路由和状态，不进入生产采集/字幕流程。没有用 Mock 通过推断真实浏览器捕获通过。本轮无可报告的真实浏览器字幕延迟或准确率数据。

## 正常桌面验收

1. 完全退出并重新打开 ELT。在 Chrome 或 Edge 打开有声音的课程网页，暂停视频，暂停同一浏览器其他页面的音频。
2. 选择对应浏览器及进程实例，设置语言。可先不勾中文验证原文；需要翻译时主动勾选“启用中文翻译”。点击开始，音频连接就绪后继续播放。
3. 确认真正出现课程原文；启用中文时观察译文和服务状态。仅“已连接”仍代表 signal=unverified，不能据此判定收到非空音频。
4. 暂停 3–5 秒后恢复，确认继续转写；完全退出所选浏览器，确认显示退出错误并回收 helper。重新打开浏览器后重新选择新进程，不自动按名称接续。
5. 连续 10 次开始/停止，检查无残留捕获/识别进程；再检查窗口关闭、模型加载中停止、浏览器音频服务重启、30/60 分钟稳定性。
6. 打开 tools/browser_audio_check.html，点击测试音。CLI 使用 capture --source chrome/edge --pid 实际PID --seconds 30 --isolation。另用 VLC 播放 440 Hz，检查 Chrome/Edge 的 1000 Hz 捕获不混入 440 Hz。该项目前待执行；保留原有频偏导致 inconclusive 的规则，不修改阈值冒充隔离通过。

测试音和独立测试配置仅由显式工具产生，不是生产录音。tools/browser_fixture_host.py 可创建独立测试浏览器，要求新输出目录；stop.request 或最长 600 秒期限会关闭它自己启动的浏览器及其后代，不复用用户配置或关闭已有窗口。测试 profile 在 .tmp/browser-fixtures 下，未复制用户浏览器数据。

## 技术依据与边界

[微软 Application Loopback 示例](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)支持目标进程及子进程，并说明无音频流时可返回静音。[Chromium 音频架构](https://github.com/chromium/chromium/blob/main/media/audio/README.md)说明 Windows 音频服务默认独立运行。[EnumWindows](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows)与[IsWindowVisible](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindowvisible)用于读取窗口归属，不操作网页。

支持目标为 Chrome、Edge、VLC。Firefox、其他 Chromium 品牌及 WebView2 暂不支持；无单标签页隔离保证；受保护媒体遵守 Windows/浏览器访问限制。关闭一个网页标签不一定结束浏览器进程，用户结束翻译时应主动停止 ELT。
