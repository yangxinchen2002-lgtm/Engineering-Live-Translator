# 桌面交互界面初版

2026-11-03 多来源翻译：新增密钥来源、翻译API和可编辑模型控件；每来源一份凭据/模型，普通偏好只有非敏感选择。凭据异步结果带来源标识，旧来源和取消后的旧保存不会误更新当前操作；会话中锁定服务/模型。现有DeepSeek课程梳理独立，不跟随字幕来源。详见 [MULTI_PROVIDER_TRANSLATION.md](MULTI_PROVIDER_TRANSLATION.md)。

2026-11-03 焦点历史：实时卡片与滚动回看独立，历史快照/行最多128项，既有句子修订保持滚动锚点，不自动追加新句；底部按钮退出回看并直接恢复当前实时焦点。渲染定时器/行在退出和新会话清理，定位坐标不变，后台工作与API调用不受影响。历史绘制不冒充实时焦点绘制，诊断仅发进入/退出状态。接口和验证见 [FOCUS_HISTORY.md](FOCUS_HISTORY.md)。

2026-11-03 翻译显示顺序修正：焦点和列表等待较早未完成的封口原文；后续已译结果保留，最新识别原文继续作为预览。迟到结果在原句就位并保留1.5–8秒再推进，焦点恢复仍以8项FIFO从128条记录分批补充。临时重试与终止失败独立，显示等待/异常只发诊断，无网络或模型调用。普通列表将最近N条正文与一条实时预览分开；绘制统计不把被暂缓的中文当作已显示。见 [TRANSLATION_CONTEXT_AND_ORDER.md](TRANSLATION_CONTEXT_AND_ORDER.md)。

2026-11-03 追加：归一化可拖动焦点、预览保留区、原文回退和迟到中文同卡更新；悬窗基础语速只发信号。会话暂停由stdin事件控制，STOP释放当前原生连接、恢复时重建连接，ASR/VAD模型保留，采样边界提交端点并清空时序上下文；QPC墙钟间隔保留。朗读用户暂停与错误独立。完整接口和队列上限见 [FOCUS_PAUSE_AND_RECOVERY.md](FOCUS_PAUSE_AND_RECOVERY.md)。

2026-11-03 本次扩展：八种原始语言；Windows应用会话经发现线程的COM公寓枚举，跨线程只传ProcessInfo元数据，身份比较仍使用PID/创建时间/路径。通用来源仍使用原生进程树API。朗读新增CatchUpPacer，按字数及稳定计时控制相对倍率，PlaybackConverter支持最高3倍并保留流状态。当前接口和验收见 [EXPANDED_SOURCES_AND_PACING.md](EXPANDED_SOURCES_AND_PACING.md)。

2026-11-03：原始语言选择增加日语，UI/偏好/后台命令共享语言注册表；日语候选预览不添加字间空格。两种翻译模式、焦点显示和存稿入口沿用现有交互。新增语言的验证结果见 [JAPANESE_SUPPORT.md](JAPANESE_SUPPORT.md)。

用户明确要求把现有操作做成交互界面。本次提供真实 PySide6 窗口，复用 M0–M2 后台；不替换音频、识别或翻译实现，不提供生产 Mock 模式。完整 M3 的设备/显示/长时间性能验收尚未完成。

便携分发版由启动脚本设置经过严格校验的 `ELT_PROFILE_ID=portable-<32 位 hex>`。`app.profile` 提供可选命名空间：凭据改用 `ELT/<profile>/DeepSeekAPIKey`，设置改用 `%LOCALAPPDATA%/ELT/profiles/<profile>/ui-settings.json`。该模式不继承 `DEEPSEEK_API_KEY`，不存在时不回退读取开发版凭据；首次使用为空白。未设置 profile 时，原程序的默认凭据/设置路径及环境变量优先级保持不变。包不复制这些外部持久数据，原件不删除。分发版 Python 使用相对 `python312._pth` 和本地依赖，界面/模型/后台共享同一个 profile；详见 PORTABLE_PACKAGE.md。

## 数据流与边界

`elt-gui / 启动ELT.cmd → MainWindow → BackendController / QProcess → app.ui.runner → 原有 translate-live → JSONL → SubtitleViewModel → 主窗口 / Overlay`

GUI 只读取进程元数据、配置和事件，不持有 WASAPI/COM/CUDA 对象。开始按钮显式启动后台；默认不勾选中文，即使本机有密钥也不自动发请求。`--source-only` 不读取翻译凭据、不构造 HTTP 客户端，并明确报告 translation_disabled_by_user。中文需要用户配置密钥并主动勾选。ASR 课程词表维持关闭。

用户追加的“中文翻译方式”在开始按钮上方固定显示，可选 sentence（整句后翻译，GUI 默认）或 preview（既有预览）。选择作为非秘密偏好保存，通过控制器校验及 `--translation-mode` 传给后台；运行中禁用切换，不修改正在进行的请求。后台 waiting_sentence 同时映射到主窗口和 Overlay 的等待提示，原文仍使用同一实时事件链。此处的“整句”及长度/停顿边界见 [SENTENCE_TRANSLATION.md](SENTENCE_TRANSLATION.md)。

2026-10-31 的界面整理将设置归入 QTabWidget 的课程/翻译/存稿三页，每页使用独立滚动区域；中文开关、模式与开始/停止保留在页签外。`show_transcript_settings` 先切到存稿页再定位保存控件，底部入口仍有效。语言/运行时长并排，控件使用明确的最小内容长度，避免长选项的尺寸提示挤出侧栏。小窗口和长字幕沿用滚动，不截断原始文本。主题集中于 `app/ui/theme.py`，仅三个本地 SVG 用于选中和箭头，通过 setuptools package-data 一并分发；不新增 UI 依赖或网络资源。主窗口中文改用淡蓝区域，悬窗的用户配色、字号和焦点动画仍由原有 appearance 控制。详见 [UI_POLISH.md](UI_POLISH.md)。

用户追加的翻译稿保存默认关闭。底部“翻译稿设置”滚动到左侧保存区，首次勾选时要求文件夹，取消则恢复关闭；开关和目录作为偏好保存，不会自动开始捕获。开始时将显式目录经 `--transcript-directory` 传给后台，运行中锁定本次配置。GUI 只消费 transcript_started/error/saved 和实际路径，不从最多 128 条的显示快照拼接全文。停止后未收到真实保存完成事件会提示，不能以子进程退出当作保存成功。后台接口和验收见 [TRANSCRIPT_SAVING.md](TRANSCRIPT_SAVING.md)。

用户随后授权 Chrome/Edge 音源：source_combo → 控制器的 source_kind → CLI --source → CaptureSession 推导的可执行文件来源 → native 来源校验；使用相同的进程树 Loopback、PCM 和字幕管线。浏览器选择要求匹配可执行文件且拥有桌面窗口；异步发现结果携带其原始来源，切换后旧结果被丢弃并重新发现。运行中禁止切换来源。范围为所选浏览器进程树，可能包含多个窗口/标签页，界面明确提示；不是单标签页捕获。详见 BROWSER_ACCEPTANCE.md。

| 组件 | 输入/输出 | 生命周期与错误 |
|---|---|---|
| window.MainWindow | 用户选择 → 控制器；事件 → 状态/可选择字幕 | 不自动捕获；多 VLC 要求选择；关闭时先异步停止会话 |
| controller.BackendController | PID+创建时间、语言、翻译开关、时长 → 真实后台 | 启动前再次核验身份，子进程入口再核验；本机发现/凭据操作使用单线程池、按类型合并重复任务 |
| runner | 私有 stdin STOP → KeyboardInterrupt → asyncio 正常取消 | 控制线程用 PeekNamedPipe，每 50ms 检查，控制缓冲 4096 字节；不在音频线程等待 GUI |
| lifetime | GUI 独占 Windows Job 句柄 → 后台及后代归属 | 后台在导入模型/创建子进程前自行加入 Job；GUI 消失则关闭 Job 杀掉归属进程；加入失败就退出，不继续捕获 |
| protocol.EventDecoder | UTF-8 JSONL 字节 → 事件 | 256 KiB 单行上限；格式/未完成消息明确报错并停止 |
| protocol.SubtitleViewModel | 真正 subtitle 事件 → 有界字幕快照 | 保留 128 片段；拒绝旧版本/候选版本/跨会话/Final 覆写；迟到的旧片段 Final 不跳回当前画面 |
| overlay.Overlay | 同一字幕快照 → 置顶悬浮窗 | 按片段身份复用行，保留最近 1–12 条匹配双语；顶部移动、右下角缩放；关闭只隐藏并恢复可编辑 |
| focus.FocusViewport | 已完成、版本匹配的快照 → 中心及上方历史卡片 | 520ms OutCubic 共享位移，不淡出；动画等待 8 条，突发合并记录诊断；隐藏/清空停止动画，缩放重新居中 |
| preferences.PreferencesStore | 有界且经过校验的 UISettings → 本地 JSON | 16 KiB 读取上限，原子写入；错误提示，不保存凭据、字幕、PID 或自动运行开关 |
| hotkeys.GlobalHotkeys | 自有窗口 WM_HOTKEY → 显示/隐藏、恢复编辑 | RegisterHotKey + MOD_NOREPEAT；不装键盘钩子；失败保留按钮，关闭注销 |
| diagnostics.runtime.RuntimeMetrics | 实际后台/Qt paint 事件 → 分类滚动统计 | 各指标 512 样本；绘制等待 8 项，首译对齐 128 项，已绘制身份 256 项；不混合时基或保留字幕正文 |

真实 Python 虚拟环境启动器可能再创建实际解释器进程，因此不能只把 QProcess 返回的启动器 PID 加入 Job。实现让实际后台自行加入 GUI 的命名 Job，然后立即关闭自己的 Job 句柄，GUI 保留唯一所有权。后台内部 M1 worker 的 Job 与原生捕获自身生命周期继续生效。20 秒正常停止期限后使用 Job 强制结束并明确提示本次未完成；并不伪装为正常提交了最后字幕。

UI 每 100ms 合并渲染；诊断最多 300 条，stderr 尾部最多 16000 字符，历史显示最多 16 片段/180 文本块。没有把音频或全文放入 Qt 队列。字幕通过 HTML 转义后才渲染；中文和其他状态使用纯文本。日志/历史默认不落盘，诊断只在用户选择新文件时导出，拒绝覆盖。

`asr_model_ready` 只代表模型就绪。新增 `audio_source_ready` 从捕获 helper 的真实 started 状态发出；GUI 收到后才提示继续播放。该状态仍携带 signal=unverified，不能据此声称已有非空音频。实际语音必须由后续输入/推理验证。

## 依赖与当前边界

PySide6 / Addons / Essentials / shiboken6 均固定 6.8.3，见 requirements-ui-lock.txt，延续已验证的 M2/GPU 组合。Qt 6.8.3 Windows QProcess 源码在父进程无控制台时使用 CREATE_NO_WINDOW；GUI 从 pythonw/GUI entry point 启动，后台不需要额外终端。

主窗口已支持 6–72 号字体、最近 1–12 条字幕、背景和更多外观设置。Overlay 为每个 `(session_id, segment_id)` 复用原文/中文行，按时间排列，更新旧行不跳回旧句；窗口不足时滚动。ASR 与翻译核心的版本校验保持原样，测试文字只存在于测试工具，不接入生产。隐藏中文时不等待隐藏标签的 paint 事件，启动新会话清空旧行。

外观对话框在“应用”后更新字体、颜色、宽高和条数，宽高/坐标以 Qt 逻辑像素存储。窗口恢复或屏幕增减时把几何约束到一个可用屏幕，支持负坐标屏幕的算法有测试，但不等同于真实多显示器/混合 DPI 验收。主窗口及设置区允许滚动，避免小屏隐藏开始/停止和恢复按钮。

Windows 的透明层窗口仅对自有 HWND 切换 WS_EX_TRANSPARENT。实测 Qt 6.8.3 的 WindowTransparentForInput 在撤销后仍可能保留 native QWindow 标记，后续重绘会重新穿透；因此 Windows 路径不设置该 Qt flag，其他平台测试走 Qt 回退。原生重绘回归及实际穿透点击、Ctrl+Alt+E 恢复、右下角尺寸变化已有独立证据。顶部用 Qt 鼠标全局逻辑坐标移动；Ctrl+Alt+S 显示/隐藏。穿透不持久保存，关闭/隐藏恢复可编辑。

生产入口才启用偏好文件及全局快捷键。偏好延迟 700ms 合并，通过原有有界单线程任务执行保存，关闭等待在途保存；加载错误报告并使用默认。保存外观、窗口位置、音源类型、语言、时长、术语表路径及用户选择的翻译稿保存开关/文件夹，不保存中文翻译启用、穿透、选定 PID、密钥或字幕正文。翻译术语表经验证后可由 GUI/CLI `--glossary` 显式选择，不改变 ASR 热词关闭的选择。

性能数据使用 QPC，区分 core 文本可用、请求全程、排队及 Qt 文字绘制。首条中文绘制必须能对齐首译版本和音频结束时刻，否则记为无法对齐；不能把下一版译文的绘制时间冒充首译延迟。P50/P95 仅代表有记录的最近样本，不是正式人工评测；Qt paint 完成也不代表显示器呈现。默认无磁盘诊断/字幕保存。

用量与费用通过 translation_usage 的累计快照更新：主窗口底部显示总量和预计美元费用，PerformanceDialog 显示输入/输出/缓存明细与已知部分、未知请求、价格日期及区间说明。ui.usage 是无网络的纯文本格式化模块；显示 9 位小数避免小额成本被显示为零。RuntimeMetrics 的延迟样本仍为有界滚动，Token/费用保留整次累计；新会话重建统计，正常/强制退出处理未结算请求后保留本次结果。价格与假日不确定性见 USAGE_AND_COST.md，不用余额差额冒充本次费用。

焦点显示只筛选 source_closed 且 Final、原文/中文非空、translated_revision 与 revision 对应的记录；仅原文模式筛选已结束原文。按 segment_id 推进，迟到的旧句不会倒退焦点。每个句对使用同一父卡片，从下方滑入时旧卡片同量上移，Qt 对上边界裁切；没有透明度动画或文字淡出。普通多条列表保留，开关仅影响渲染，主窗口实时预览不变。

焦点下方另有一组复用的实时原文控件，不属于完成卡片或动画队列。它取当前会话 segment_id 最新且未完成的记录，显示转义后的 source_text 与浅色 candidate_text；没有已确认前缀时也显示候选文字，识别结束等待译文时保留原文。最新记录完成后移除该预览，不回退到更早未完成的记录，避免与新焦点重复。

预览区域锚定在最下方完成/滑入卡片底部之后，不参与中央卡片布局，因此文字增长或修订不会移动焦点或重启动画；动画推进时预览随其底边上移。单独的裁切容器限制预览在下方可用区域内，过长文字通过移动完整文本控件显示最新尾部，不改写或截断原始记录。字体/颜色复用原设置，清空/新会话移除旧预览，隐藏/恢复保留正确的最新预览。预览不发出 focus settled/paint 计时，不增加翻译请求或依赖模型。

FocusViewport 将当前动画完整播放，新完成的记录最多等待 8 条；超限合并旧的待播动画并发出 focus_transitions_coalesced，字幕模型本身不变。卡片按最近条数 1–12 保留，切换时暂时多一张。隐藏时直接就位到最新已完成内容，停止定时器/动画，不在后台追播；新会话清空，窗口/字体变化重新排版并安全结束当前位移。超高卡片支持滚轮查看，下一次推进从滚动后的实际位置开始，避免复位跳动。

控制器另保留最多 128 条无正文的接收时间/版本元数据，让焦点显示较早完成片段时使用该片段自己的时间。焦点就位后才请求文字 paint，性能统计使用独立 focus 视图，标签明确“含动画”；不能把动画下方首次露字或较新的未完成片段时间冒充焦点就位时间。无法对齐首译版本时仍不生成音频至焦点延迟。具体测试见 [FOCUS_DISPLAY.md](FOCUS_DISPLAY.md)。

高 DPI/多显示器实机、VLC 普通/最大化/各种全屏方式、30 分钟延迟及 60 分钟稳定性仍待验收；长测由用户明确留到空闲时。不把普通置顶窗口等同于独占全屏兼容。

官方依据：[PySide6 6.8.3](https://pypi.org/project/PySide6/6.8.3/)、[QProcess](https://doc.qt.io/qtforpython-6.8/PySide6/QtCore/QProcess.html)、[QWidget](https://doc.qt.io/qtforpython-6.8/PySide6/QtWidgets/QWidget.html)、[Qt 6.8.3 Windows 进程实现](https://github.com/qt/qtbase/blob/v6.8.3/src/corelib/io/qprocess_win.cpp)。

## 统一应用音源（2026-11-04）

朗读模型列表现统一提供 Qwen 0.6B / 1.7B 与 Windows 系统音色，系统选择复用 web_speech_engine / web_voice 字段，Qwen 选项单独保留；系统声音异步枚举。应用音频模式新增系统 PCM worker，仍由原 SpeechController 管理有界队列、播放及退出，界面不持有 SAPI 对象。视频字幕外观通过原 playback 接口回写偏好，不与桌面悬窗混用；见 [VIDEO_CAPTION_APPEARANCE.md](VIDEO_CAPTION_APPEARANCE.md)。

桌面来源分类控件已移除，BackendController 默认枚举 Windows 应用音频 sessions，MainWindow 直接展示具体应用。旧来源偏好可读取但不恢复旧筛选，其他字段保持；CLI 的旧筛选保留。异步枚举、身份核验、原声控制及捕获协议沿用既有实现，见 [UNIFIED_AUDIO_PICKER.md](UNIFIED_AUDIO_PICKER.md)。
