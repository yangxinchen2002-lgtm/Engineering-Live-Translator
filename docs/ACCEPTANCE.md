# 字幕同步修正补充 — 2026-11-03

2026-11-04 语言增量：中文/English 界面、中文/English 翻译及对应朗读已实现。889 项全量 Python 回归通过，后续专项通过；75 项 JS 通过。Qt 16 页、独立 WebView2/三种顶部栏宽度检查通过，真实 DeepSeek、Qwen/SAPI 英文短测和 EXE 英文偏好启动通过。证据及未执行边界见 [LANGUAGE_OPTIONS.md](LANGUAGE_OPTIONS.md)。

朗读补充：首句过期不再触发 Qwen 反复加载，热模型的过期请求排空后复用。154 项相关回归及最后 22 项界面/朗读专项通过。真实 1.7B CUDA 只载入一次，17.906 秒就绪，随后 7.047 秒生成并调用 Windows 播放 4.64 秒固定中文测试语音，过期首句未发布，退出无残留。该测试不含课程 ASR 或 DeepSeek，不代表整节课实时朗读通过，证据见 `artifacts/web-tts-startup/`。

用户重开窗口后确认原文/中文仍晚 2–3 秒，原预读回归通过不等同于偏移解决。后续真实声音比对测得 2.024 / 2.005 秒坐标差，正式后台现已自动换算；快照 `clock_calibrated=true`，源位置比播放器位置大实测偏移，双语预读 18.285 秒，无残留校准捕获进程。详见 [实测对时记录及限制](WEB_AUDIO_CLOCK_ALIGNMENT.md)，听看与长测未新增通过结论。

HLS 追加实测：修复真实 7 点时间戳微缝隙引发的预读停止；新策略仅限 0.5 ms 内部缝隙且有累计预算，最终相关测试包含拒绝较大/边缘/累计超限缺口。仅重启字幕后台后，约 75 秒快照 ready、无错误、双语预读 7.710 秒、翻译队列 0，9 个处理窗口累计修复 25 点。旧播放器脚本保持原样，实际固定偏移是否消失仍待用户重开课程窗口听看。

源音频预读与翻译解耦；原句更新、用量单调和错误保持测试通过。内置主音轨时钟修复已实现，但旧课程窗口需用户方便时重新打开载入；真实听感仍待确认。完整 Python 899 通过、3 跳过，最后相关模块 139 通过、JS 41 通过。真实公开样本以 1x 连续前进 35 秒，4 句均提前准备，跳窗 0；该测试不是浏览器或人耳延迟测量。详见 [WEB_SUBTITLE_SYNC.md](WEB_SUBTITLE_SYNC.md)。

---

# 当前融合补充 — 2026-11-03

原 ELT.exe / 主界面现已统一管理内置课程窗口、原网页预读及已有 Qwen TTS；默认内置窗口无需扩展/配对，保留 Edge 兼容和应用音频模式。完整 Python 回归 891 通过、3 跳过；最终相关模块 153 通过；JS 37 通过；真实 WebView2 MP4、受保护窗口退出、Whisper+DeepSeek+Qwen GPU 短链路通过。首次冷加载与 15 秒预读不保证赶上所有语音。新窗口的 TUM 登录及课程质量、听感、全屏/DPI/60 分钟仍待验收。见 [内置窗口验收及步骤](INTEGRATED_WEB_PLAYER.md) 和 artifacts/web-tts-player/acceptance.json。

---

# 当前补充验收：网页预读接入正式界面 — 2026-11-03

本轮已将网页预读接入 ELT.exe；以下原 M0 报告为历史证据，其“M1–M3 未实施”只描述当时状态。当前范围、使用步骤、实测与未执行项见 [WEB_FOLLOW.md](WEB_FOLLOW.md)。完整 M3/MVP 仍未验收。

- 正式界面、应用音频/网页模式切换、既有扩展安装路径兼容、原播放器只读跟随、整句和自然语速规则已接入。
- 完整回归结果及环境记录见 `artifacts/web-follow-integration/acceptance.json` 和 `final-python.xml`；浏览器逻辑 35 项通过。
- 真实 GPU 短测：正式 GUI → 后台 → 本地公开课预读 → 真实原文 → 选择保存 → 停止释放，首次准备 14.359 秒；原音频 ASR 另成功启动和释放。未调用云翻译，非真实网站延迟统计。
- 既有 ELT.exe 实际启动成功，桌面可见新模式和 Windows 中文音色。现有实验扩展更新到 0.4.0，重新加载后需在新连接页配对；本轮未重新完成网站上课的听感验收。
- 从视频中途开始、跳转、跳过积压或更换来源均保留不完整标志；预读未来句子不显示、不存稿，待确认原文不导出到诊断。
- 按用户安排，60 分钟长测继续留待空闲；全屏/混合 DPI、课程 WER、术语质量等未新增通过结论。

---

# M0 验收报告 — 2026-10-30

阶段仅限 M0。以下将自动逻辑测试、真实 Windows IPC、真实 VLC 音频测试分开记录；不以其中一项替代另一项。M1–M3 未实施。

## 环境及来源

- Windows 11 Pro x64，10.0.26300；详细硬件及工具版本见 `evidence/2026-10-30-live/environment.json`。
- Python 3.12.10 专用 `.venv`；NumPy 2.3.5、SciPy 1.17.0、pywin32 312、pytest 8.4.2。
- MSVC 19.44.35229.0 / v143 14.44.35207，Windows SDK 10.0.26100.0，CMake 3.31.6-msvc6。按用户授权通过微软签名验证为 Valid 的 Build Tools 安装器安装，退出码 0。
- VLC 3.0.24 Windows x64 便携版来自 VideoLAN。ZIP SHA-256：`fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323`，与官方校验文件一致。
- 音频测试在正常 Windows 用户环境执行。第一次受限自动化环境因 CreateFile 访问权限被拒绝，明确失败；没有放宽管道 ACL。正常用户环境中的实际捕获成功不意味着受限容器也支持音频。

## 自动测试及构建

| 项目 | 结果 | 证据/边界 |
|---|---|---|
| CMake Release x64 构建、链接 | 通过 | `native/build/Release/elt_capture.exe`，/W4 构建无警告 |
| C++ 协议 golden bytes/无效控制/超大包 | 通过 | CTest native_protocol |
| C++ SPSC 包数/字节上限、10 万条并发顺序 | 通过 | CTest native_queue |
| Python 完整测试（含真实 VLC 集成） | **55 项通过，0 失败，0 跳过，7.40 秒** | `evidence/2026-10-30-live/pytest-delivery.txt` |
| 真实 Win32 pipe 双向碎片及超时取消 | 通过 | 上述测试中的 test_named_pipe；不是 WASAPI 捕获证据 |
| PCM 16/24/32/F32、混声、跨包重采样、抗混叠、尾帧、缺口/时间戳异常 | 通过 | tests/unit/test_processing.py |
| 真 VLC 发现及重启身份变化 | 通过 | 两次 VLC 进程 PID 44592 → 29660，创建时间各不相同，发现/退出均正确；生产绑定为 PID+创建时间+路径 |

早期测试发现并修复 pywin32 无 CancelIoEx 导出的兼容问题，现使用同线程 CancelIo 并等待取消完成。pytest 默认临时目录受限，改为项目内明确的 `.test-tmp`。这些早期失败不计入通过数。

## 格式及实际数据

实机 **GetMixFormat 返回 E_NOTIMPL**。已按 DECISIONS.md D004 显式协商回退，Initialize 接受 **44100 Hz、2 声道、S16**；STATUS 记录 `format_source=Initialize_accepted`，未宣称成功查询设备 mix format。Python 流式低通重采样后为 **16000 Hz、mono、Float32**，正常帧 320 样本，结束短帧显式保留，FIR 群延迟为 10 个输出样本（0.625 ms，仅为滤波器理论群延迟，**不是端到端延迟实测**）。

首次 5 秒实测：79040 个标准化样本，4.94 秒音频，RMS 0.17638，峰值 0.25027，观察到 1000 Hz，正常 STOP，退出码 0。墙钟与采样时长差包含启动等待，未用补零掩盖。

## A–E 实机验收

### A：10 分钟连续捕获 — 本机通过

600.000 秒墙钟内收到 **9,599,200** 个 16 kHz 标准化样本（599.95 秒）。RMS **0.176951**、峰值 **0.270968**，正常 STOP、退出码 0，无序号缺口/时间戳错误/数据 discontinuity 事件。启动期间约 0.05 秒未计作采样数据，未填零伪造。每秒抽样观察到的原生队列最大 2 包/3528 字节（不是逐包峰值测量）。原始证据：`evidence/2026-10-30-live/A_B_continuous_isolation.jsonl`。

### B：音源隔离 — 10 分钟本机通过；短测有明确限制

VLC 持续播放 1000 Hz；另一应用（独立 Python 进程的 Windows WinMM PlaySound）同时循环播放 440 Hz，启用 SND_NODEFAULT 并确认渲染 API 启动。按一秒 Hann 窗比较两个频带的功率，默认上限 −50 dB。注意这验证本机本次软件/输出环境，不能外推所有音频驱动或受保护媒体。

10 分钟运行的 599 个完整频谱窗，累计功率比 **−122.41 dB**，最差窗口 **−63.87 dB**，原有 ±3 Hz / −50 dB 判据通过；没有降低阈值或改写该结果。额外负控制：目标暂停、其他 1000 Hz VLC 和 Python 440 Hz 仍播放时，目标捕获 RMS **0.000006300**，CLI 返回 3（无有效信号）；恢复该目标后功率比 −101.26 dB、最差 −95.26 dB，退出码 0。证据：`B_control_results.json`。

**未通过的补充控制组保留：** `B_final_target_only.jsonl` 在没有干扰源的 5 秒短测中，最差比值 −46.31 dB，未通过。调查重现主频约 1005–1008 Hz 随后回到 1000 Hz；在相同时间窗口，原生 44.1 kHz PCM 与标准化 16 kHz PCM 的主频一致（`raw_vs_normalized_spectrum.json`），所以未发现 Python 重采样引入频偏的证据。上游 VLC/Windows 路径的具体原因尚未完全定位，不能直接把这次失败解释成串音，也不将其改写为通过。

最终工具保留原 ±3 Hz 频带及 −50 dB 阈值，并新增主频/目标频带占比；主频在 980–1020 Hz 范围而超出目标分析带时明确标为 `inconclusive_target_frequency_outside_band`，返回 3。没有静默扩大频带、忽略窗口或将不确定视为通过。稳定播放后的控制结果另存 `stable_control_results.json`。因此本报告结论是“10 分钟该环境隔离证据通过”，不是“所有启停场景的窄带自动判据都通过”。

最终版本在播放器继续稳定播放后再次独播 6 秒：5 个完整窗主峰均为 **1000 Hz**，目标频带占比 **0.99999969**，最差比值 **−95.47 dB**，isolation_status=passed、退出码 0。之前未通过短测仍保留，不用此结果替换。测试结束检查未发现残留 VLC 或 elt_capture 进程。

### C：暂停与恢复 — 通过

14 秒重测，4 秒后暂停，4 秒后恢复。暂停稳定区间 RMS ≈ 0.000006301；恢复后连续五个区间 RMS ≈ 0.176956。捕获未崩溃、时间戳未报错，222880 个输出样本（13.93 秒），正常停止。

证据：`C_pause_resume_verified.jsonl`、`C_verified_results.json`。初次自动化使用 RC `play` 恢复，VLC 明确要求再次 `pause`，因此那次**不能验证恢复**，保留原 C_pause_resume.jsonl 供审计；工具已改正，不把原错误计为产品通过。默认信号阈值已设为 RMS 1e-4，避免将暂停底噪当成有效声音。

### D：目标异常退出及重新选择 — 通过

关闭 VLC 后，收到 `target_exited_select_again_for_new_PID` ERROR；Python 以失败状态终止捕获，符合本测试预期，并回收 helper。新 VLC 使用不同 PID，随后 10 次捕获正常运行。证据：`D_target_exit.jsonl`、`results.json` 的 D 段。

第一组 D 的目标刚经历错误恢复命令，可能仍在暂停，故最终构建又补做**正在播放**时直接退出的测试：明确 ERROR、非零退出、约 **0.109 秒**检测和清理，证据 `D_final_playing_target_exit.jsonl`、`final_checks.json`。该 JSON 内 target_only 项保留上述未通过短测，不能把整个文件当作“全部通过”。

### E：重复运行 — 通过（10 次级别）

CLI 连续十次每次两秒正常捕获/停止，无 ERROR，十次都有真实音频。额外资源检查再次运行十次，每次 helper 均以 0 退出；主动保留十个已关闭会话对象，父进程句柄第 1–10 次均为 **174**，增长 **0**；helper 活跃句柄约 109–111。首次加载前父进程 169，模块加载后平台初始化增加 5，随后无逐次增长。

证据：`E_ten_cycles.jsonl`、`E_resources.json`。此结果支持“十次运行无明显句柄泄漏”，不能据此保证无限运行或音频驱动内部不存在任何泄漏。

### 额外故障检查 — 通过

Python 连接后故意不读取，最终 helper 在 **2.375 秒**内非零退出，stderr 明确包含 `pipe_writer_error=pipe_io_timeout` 与 `transport_fault=2 audio_incomplete`。没有死锁或静默继续。证据 `final_checks.json` 的 stalled_receiver 项。最终原生构建还补全了控制/输出/紧急释放失败诊断，构建和两个 CTest 再次通过，见 `native-build-final.txt`。

## 用户复验

1. 按 README 在干净 Python 3.12 环境安装依赖；安装 Build Tools 所列三个组件，运行 `tools/build.ps1` 和 pytest。
2. 启动 VLC 播放课程，`python -m app.main list` 后选择实际 PID；多实例不指定 PID 应报错。
3. Test A：`capture --pid 实际PID --seconds 600 --log 新路径`。核查 complete、signal、RMS、样本数、序号/缺口错误及 STOP；如需听取，显式指定最多 30 秒 WAV。
4. Test B：生成两个测试音，分别在 VLC 和另一应用播放；做仅目标、仅干扰源（目标暂停）、二者同时的控制实验；同时播放运行 `--isolation --seconds 600`。确认干扰源本身确实在播放，而非因其未输出得到假阴性。
5. Test C：捕获期间暂停 4 秒、恢复，核对每秒增量能量和时间戳；不能仅核对总 RMS。
6. Test D：直接关闭 VLC，期待明确 ERROR 和非零退出；重新打开并重新 `list`/选择，验证可再次启动。
7. Test E：`capture --pid 实际PID --seconds 3 --cycles 10`，以及 `tools/resource_checks.py`；检查十个总结和无残留 helper。
8. 可直接运行 `tools/live_checks.py --output 新目录 --seconds 600` 自动驱动测试音/暂停/退出/重复启停。测试源与日志保存在明确指定目录，真实捕获音频默认不落盘。

## 当前限制

- 没有 ASR/翻译/GUI；没有做 GPU 或字幕延迟测量。
- GetMixFormat 成功返回其他设备格式的路径尚未实测；44.1/48/96 kHz、不同 PCM 位深已做数值自动测试，不冒充相应设备实测。
- 当前未进行受保护媒体、音频设备拔插/切换、睡眠唤醒和 60 分钟稳定性测试；后者不是本轮 A–E 要求，不标为通过。
- 窄带隔离工具对实测约 0.8% 的短时主频偏移会返回“不确定”；上游频偏原因未完全定位。保留此局限供用户验收，不宣称所有控制实验无失败。
- 不自动跟随同名进程重启；必须重新选定身份。环绕声当前采用全声道等权平均，未优化专业混音权重。
- 完成 M0 后等待用户验收，绝不自动进入 M1。

## 后续授权的内置网页朗读补充（2026-11-03）

2026-11-04 用户反馈启动“未知字段”：已确认并修复 desktop 启动字段白名单与新外观参数不同步的问题。41 项相关回归及真实主界面 / 子进程 / 认证 HTTP / 正常停止通过；早先 280 项回归未覆盖该完整启动配置边界，不能替代此次实测。证据见 [VIDEO_CAPTION_APPEARANCE.md](VIDEO_CAPTION_APPEARANCE.md) 的启动修复部分。本次无音频捕获、GPU、收费调用或用户视频控制。

2026-11-04 紧凑字幕及系统音色：280 项相关 Python、18 项最终 UI、72 项 JS 通过；真实 WebView2 短字幕 65.9 px / × 22 px / 状态行 0，长句高度可限且保留全文、关闭按钮滚动后仍可见。扩展 / 内置顶部外观控件与 HTTP 通过；Windows 慧慧真实内存合成 5.895 秒 PCM，正常回收，无 GPU / 付费请求。用户在朗读模型选择 Windows 系统音色即可使用；扩展需手动重新加载 / 刷新。证据和未执行的实际课程 / 听感 / 长测见 [VIDEO_CAPTION_APPEARANCE.md](VIDEO_CAPTION_APPEARANCE.md)。

2026-11-04 桌面统一音源选择：来源分类已移除，直接选 Windows 应用，旧偏好适配及其他设置保留。260 项相关自动测试通过，实际读取 6 个应用且无枚举错误，离屏布局已检查；本次无真实收音 / GPU / 付费请求，原有长测边界不变。操作和证据见 [UNIFIED_AUDIO_PICKER.md](UNIFIED_AUDIO_PICKER.md)。

2026-11-04 本地视频预读：已在原 ELT 增加文件入口与独立于字幕停止的播放服务。相关回归 182 项 Python、70 项 JS 通过，最后主界面调整专项 14 项通过。已有公开英语 MP4 在真正 WebView2 内播放，CUDA 识别产生 2 条确认原文，DeepSeek 返回 2 条中文，Qwen 1.7B / CUDA 产生并实际播放 1 条语音；真实暂停 / 倍速 / 跳转 / 停止字幕后视频继续及 ASR 释放通过。准备阶段 29.375 秒不是连续字幕延迟，媒体播放事件也不代替人工听感或整句播放完成。格式、自动测试失败修复过程、用量快照口径、复验工具和未执行项见 [LOCAL_VIDEO_LOOKAHEAD.md](LOCAL_VIDEO_LOOKAHEAD.md)。用户可重新打开 ELT，选择“视频预读（网页 / 本地）→ ELT 内置窗口”，点击“打开本地视频”选单音轨 MP4，再点“开始字幕”自行播放。未操作用户当前视频，不标记长测 / 完整 M3 / MVP 通过。

扩展0.5.0同步：171项Python / 68项JS通过，独立扩展界面的真实设置HTTP、界面渲染和原内置模式兼容通过。旧安装目录文件已同步，用户浏览器未自动重新加载或刷新；已登录TUM实机新版本待手动更新后复验，见 [EXTENSION_UPDATE.md](EXTENSION_UPDATE.md)。

顶部视觉整理：原生工具栏已分组并支持窄窗换行。33 项 Python / 55 项 JS 及独立 WebView2 控件/本地视频短测通过；800/1240/1600宽度无标签/按钮文字截断。实际图与复验见 [NATIVE_TOOLBAR_POLISH.md](NATIVE_TOOLBAR_POLISH.md)。不将其作为用户课程或混合DPI验收。

顶部原声音量功能：167 项 Python / 55 项 JS 通过；真实 Windows 控件初始化/事件、独立 MP4 按比例降低/动态调整/恢复通过。本轮没有操作用户当前课程或进行长测，范围与复验见 [WEB_SOURCE_VOLUME.md](WEB_SOURCE_VOLUME.md)。

上文保留 M0 当时的验收范围；用户后续已授权 M1/M2/M3 和正式网页预读。当前“有字幕无中文声音”的真实站点修复、顶部朗读设置、162 项 Python / 47 项 JavaScript 回归及实际播放计数见 [WEB_READING_CONTROLS.md](WEB_READING_CONTROLS.md)。本次没有暂停、重载或跳转正在播放的用户视频，没有执行 60 分钟长测；不据此标记完整 M3/MVP 已通过。
