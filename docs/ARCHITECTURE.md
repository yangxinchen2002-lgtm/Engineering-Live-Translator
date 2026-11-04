# M0 架构与边界

2026-11-04：界面语言、源语言、翻译目标相互独立；本地词条覆盖 Qt、WebView2、连接页与扩展，字幕内容不参与界面本地化。会话固定 `target_language=zh/en`，贯穿提示词、术语、Qwen/SAPI 和存稿。见 [接口与验证](LANGUAGE_OPTIONS.md)。

M0 基线保留。用户已授权继续 M1；新增模块、队列、稳定状态与时钟语义见 [ARCHITECTURE_M1.md](ARCHITECTURE_M1.md)。本文件描述的 native 协议及捕获职责未变。

用户随后授权 M2，当前翻译、双阶段状态和安全配置接口见 [ARCHITECTURE_M2.md](ARCHITECTURE_M2.md)。M0 原生职责没有扩展到模型或网络。

用户追加授权交互界面，PySide6 窗口、后台控制、悬浮字幕及资源生命周期见 [ARCHITECTURE_UI.md](ARCHITECTURE_UI.md)。最新界面交付及尚未执行项见 [M3_ACCEPTANCE.md](M3_ACCEPTANCE.md)，不代表完整 M3/MVP 验收。

当前实现：VLC → Windows 进程树 Loopback → C++ `elt_capture` → 本地命名管道 → Python PCM processor → CLI diagnostics/可选短 WAV。

| 模块 | 输入 | 输出 | 生命周期/失败 |
|---|---|---|---|
| ProcessSelector | Windows 进程快照/可选 PID | PID、名称、路径、创建 FILETIME；访问错误 | 不持有长期名称绑定；多实例拒绝自动选择；watch 报告退出和新身份 |
| CaptureSession | helper 路径、选定身份 | 验证过序号的 Packet | 启动前核验身份，退出始终回收子进程；不自动重连 |
| Native capture | START、PID、创建时间 | 实际格式 PCM、状态、HRESULT 错误 | 单次会话；COM 在 MTA；事件驱动读取全部可用包；STOP/目标退出/连接断开结束 |
| NamedPipe | 二进制字节 | 有边界 Packet | exact-read、长度/版本检查，可取消 I/O，有限超时 |
| AudioProcessor | 单格式会话 Packet | 16k mono Float32、320 样本帧 | 任意缺口/格式变化失败；finish 交付不足一帧尾部；内存有界 |
| Diagnostics | 标准化音频 | RMS/峰值/有效采样数/频谱统计 | 只保留不足一秒窗口；无文件副作用 |
| CLI | 用户显式命令 | JSONL、退出码；可选指定路径短 WAV | 主动启动；默认不录音、不持久写日志；中断关闭资源 |

native 仅包含 INCLUDE_TARGET_PROCESS_TREE，不提供全系统/麦克风/排除进程模式。打开并持有目标进程句柄，核验创建 FILETIME 及 executable 为 vlc.exe，避免发现到启动之间的 PID 重用。激活回调为 FTM agile COM 对象，其参数、事件和结果由对象自身持有，激活超时不会留下指向栈的异步指针。

native 对 GetMixFormat 返回的 WAVEFORMATEX/EXTENSIBLE 进行验证，支持 S16、S24、S32、F32。仅 E_NOTIMPL 时进行**显式协商回退**，详见 DECISIONS.md；其他失败不回退。原生层不假设用户输出设备一定为 48 kHz。

混声道采用所有通道等权均值（包括 LFE），掩码保留在协议中；这适用于普通单/双声道课程，环绕声的加权语音优化不在本轮实现。Python 通过 SciPy FIR polyphase 真正低通和重采样，历史与抽取相位跨包连续，绝不以改标签替代重采样。整数转 Float32 保留符号与位深语义，浮点不静默削波；WAV 导出才裁剪到 16-bit 范围。

M0 没有建立未来模块占位。现已实现的 M1 以 AudioFrame 的采样时间轴接入，详见独立的 M1 架构文档。后续 M2 和界面初版分别维护设计，GUI 不接触 WASAPI/CUDA 对象。不存在网络上传音频的路径。
# 正式网页视频预读补充（2026-11-03）

主界面通过同一个 `BackendController` 在两种后端之间切换：原 `app.ui.runner` 应用音频流水线，以及 `app.web_follow.desktop` 网页预读。后者由 Qt QProcess 与 Windows OwnerJob 管理，使用有上限的 stdin CONFIG/STOP 控制和逐行 JSON 事件；本机配对 nonce 仅传给连接页，不进入诊断记录。退出时回收服务和所有识别子进程。

`app/web_follow` 是正式实现与资源目录，包含媒体解码、HLS、整句边界、Whisper 工作进程、本机服务、系统语音和网页扩展。`experiments/lookahead` 的 Python 文件仅保留兼容导入；已有扩展安装目录由发布同步工具维护，与正式扩展逐字节一致。正式代码不导入实验模块，移除实验目录不影响新安装。

网页插件只观察原播放器时间和媒体，音频在本地解码、混声和重采样，后台有界预读/整句翻译/合成，浏览器按原播放器时间显示与播放中文。Windows 识别互斥租约在正式 ASR 和网页 ASR 工作进程内获取，避免重复模型；网页模式的 Qwen TTS 与系统音色为显式选择；Qwen 通过有上限的独立进程/任务队列准备 WAV，不阻塞 ASR 和翻译。GPU/WASAPI 对象仍不进入 GUI。

桌面适配器只把已到播放时间的确认句段提交到既有字幕视图、完整课程内存和可选 TranscriptWriter；尚在扩展右侧上下文中的暂定原文仅作预览，不进入存稿，未来已准备句子不提前显示。用量跨来源与识别重建累计，价格沿用现有快照估算。网页预读时间不能套用实时收音的句末延迟统计，另显示预读余量与准备耗时。

---

## 内置课程窗口（2026-11-03）

主 GUI 的 WebPlayer 管理 app.web_follow.player 子窗口，用独立 OwnerJob 统一关闭 WebView2 子进程；捕获后端停止不关闭课程窗口，因此不暂停视频。主界面用有限 stdin CONFIG/CONNECT/DISCONNECT/RAISE/CLOSE 控制窗口，配对令牌仅在本地进程内存和 HTTP 请求头中，不进入网页。WebView2 只在指定课程域/子视频框架读取媒体和时钟，经现有本机服务复用整句识别、翻译和 WAV。页内随机实例 ID 隔离导航前的迟到字幕/语音。

Qwen 复用 app.speech.worker/runtime 和已装 .venv-tts，在网页工作进程的嵌套 Job 内运行；队列最多 8 句，PCM/单句 WAV/缓存与准备时间都有上限。模型预热只响应会话停止，不能绑定首句过期；过时结果不提交，正在生成的请求限时排空到 DONE 后复用模型，停止会话立即取消并释放进程。不修改源句、不静默回退系统音色。语音就绪作为独立事件更新已有 cue，先显示原文/中文，避免 TTS 阻塞流水线。启动与 1.7B 实测见 [内置窗口说明](INTEGRATED_WEB_PLAYER.md)。

## 预读与时钟修正（2026-11-03）

补充：正式内置模式可用 `AudioAlignment` 在当前播放器活动音频会话采样 8 秒，并与预读 PCM 匹配。两处独立匹配确认后，内部调度使用源时间，返回网页的句段使用换算后的播放器时间。所有原始 ASR 时间保持不变，失败不补偿；不保存采样，不改源播放器。生命周期、±4 秒上限及 1 倍速测量边界见 [WEB_AUDIO_CLOCK_ALIGNMENT.md](WEB_AUDIO_CLOCK_ALIGNMENT.md)。

源音频工作进程提交整句 ASR batch 后立即进入下一窗口；独立 CueTranslator 线程按 8 句有界队列调用文本翻译，按代际/句段 ID/原文合并迟到结果。最近 30 秒可补译，全部 cue 上限 96，未来数据不静默删除。网络用量单调累计，源音频准备与翻译耗时分别记录。

内置课程窗口的朗读快捷设置走原本机 `/api/playback`，语速/音量在浏览器 Audio 生效，开关由跨进程标志控制，模型/音色通过容量 1 的合并命令重建合成器，ASR 和字幕时钟不重建。语音文件及迟到事件带独立 speech_revision。媒体路由兼容原生请求头验证与 HTML 媒体的 URL 验证；仍拒绝错误令牌、外部 Origin 和非会话允许文件。生成、读取和真实播放事件分别诊断，接口及证据见 [WEB_READING_CONTROLS.md](WEB_READING_CONTROLS.md)。

课程窗口的原生控件构建独立在 `app/web_follow/toolbar.py`，继续调用同一个 Player 的导航/设置/字幕方法。布局按宽度调整，不接管 WebView2、模型或网络对象；相关样式及实际渲染验证见 [NATIVE_TOOLBAR_POLISH.md](NATIVE_TOOLBAR_POLISH.md)。

扩展0.5.0通过已配对的 `/bridge/settings` 与 `/bridge/playback` 读取/更新朗读设置，沿用Lab及原偏好同步。独立playback_revision隔离旧时钟回复；原声控制的共享实现统一在extension/source-volume.js，由中文实际播放事件与文档身份路由至声音框架，停止或失联恢复。浏览器后台保持受信弹窗和活动内容脚本边界，密钥仍在主程序。流程及验证见 [EXTENSION_UPDATE.md](EXTENSION_UPDATE.md)。

内置观察器分别绑定声音时钟和字幕显示画面；跨框架以最新主时钟及有界单调时间推进，原播放器播放状态、位置和倍速保持只读。依用户授权，原声音量可在中文实际播放时按比例降低，并在停止/失联/切换音源时释放；只调整声音视频元素，不调整整个 WebView2 音频会话，避免同时压低中文。细节见 [WEB_SOURCE_VOLUME.md](WEB_SOURCE_VOLUME.md)。HLS 内部时间戳缝隙最多 0.5 ms 且累计每秒最多 2 点，插值必须有两端真实样本，修复数量显式累计；其他缺口使后台进入保持的错误状态。策略、实测与仍待验证项见 [WEB_SUBTITLE_SYNC.md](WEB_SUBTITLE_SYNC.md)。

## 本地视频预读（2026-11-04）

原视频预读模式增加本地文件入口，复用相同的 MainWindow / WebPlayer / Player / Lab / Whisper / 翻译 / TTS / Presentation。原生文件选择器授权一个具体文件，播放器拥有的 LocalMediaHost 在回环随机端口提供临时能力地址、HTML video 页面和真实 Range；不接受客户端指定的任意路径。网页只得到文件名，完整路径及文件身份只在 Python 内传递。

文件服务独立于字幕后台，STOP / DISCONNECT 不关闭它；关闭播放器才回收本地服务、挂起连接和子进程。最多 8 个并发读取、64 KiB 块、选择更换时撤销旧能力，文件标识 / 大小 / 修改时间校验防止识别与播放读取不同内容。播放器发出的有界 stdout 启动事件请求原主界面按现有配置启动后台，不创建第二套配置或密钥。

本地观察器仅接受精确的播放器自有页面及其注册媒体，用真实 video 时钟驱动同一预读流水线。取消 / 跳转 / 迟到翻译与语音沿用原代际和版本校验；本地媒体不走网页音轨的额外声音对时。多音轨文件目前明确拒绝，避免浏览器和 ASR 选轨不同；推荐单音轨 H.264 / AAC MP4，不增加自动转码。实现、测试与边界见 [LOCAL_VIDEO_LOOKAHEAD.md](LOCAL_VIDEO_LOOKAHEAD.md)。

## 紧凑视频字幕与统一朗读入口（2026-11-04）

两种视频播放器共享 layout.js 的字幕 DOM / 尺寸 / 缩字实现，无内容时隐藏，× 仅停止字幕。三个有界外观字段经原认证 playback 接口及 revision 同步，不重建后台。主程序朗读模型列表统一 Qwen / Windows，系统音色在独立 PCM worker 的 COM 线程中向内存合成，复用原播放、追赶和 Job 生命周期；不加载 GPU 模型、不写临时语音文件。边界及真实验证见 [VIDEO_CAPTION_APPEARANCE.md](VIDEO_CAPTION_APPEARANCE.md)。


## 独立 AI 总结 API（2026-11-04）

存稿页独立维护 notes_provider / notes_models，复用已有四类官方 API 身份和凭据存储；不修改 translation_provider / translation_models。生成时将供应商、模型和目标语言作为非秘密字段放入有界课程请求，NotesController 在入队时序列化快照，密钥不经过命令行、IPC 或偏好文件。

notes.worker 先验证请求配置，再读取对应供应商的凭据；notes.service 再次核对凭据所属服务，始终由 provider_info 选择官方 HTTPS 地址，通过同一 create_client 路由真实协议。独立总结进程沿用 OwnerJob、最多 4 个待办、分段细节加有界总览、有限重试、取消和原子不覆盖保存。总结错误不会停止字幕或替换实时翻译设置。每份稿件记录实际选择的服务、模型及已报告 Token，按请求中的 zh / en 目标生成对应提示词、标题和文件后缀。使用说明见 [AI_NOTES.md](AI_NOTES.md)。
