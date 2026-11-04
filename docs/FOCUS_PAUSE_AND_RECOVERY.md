# 焦点位置、会话暂停与翻译故障原文保留 — 2026-11-03

阶段：M3 追加交互与恢复功能。当前源码已更新，直接重启现有桌面快捷方式或根目录 `ELT.exe`，不需要重新配置密钥或下载模型。未重打历史便携包。完整 M3/MVP 验收仍未完成。

## 操作

1. 启用“置顶字幕窗”和“焦点显示”，悬窗上方点击“定位”显示蓝色焦点标识。上下左右拖动改变焦点，双击标识回到中央，再点击“定位”可隐藏标识。焦点按窗口比例保存，改变尺寸后仍使用相同比例。贴近边缘时，正文和标识会限制在可阅读范围内；底部有正在识别的原文时，为它预留空间。鼠标穿透时不能操作控件，先用“恢复可编辑”或 Ctrl+Alt+E 恢复。
2. 焦点句对继续采用 520ms OutCubic 位移；旧句上推，无淡出。超长正文可滚轮查看。下方实时原文不再因为焦点正文过长而没有空间。
3. 开始并连接音频后，可按“暂停”。收到真实收音关闭确认后，按钮变成“继续”。暂停收音和朗读，保留字幕、识别模型、会话及待播内容；暂停前已收音的尾句和已发出的翻译请求仍可补齐。继续时重新连接同一 PID/创建时间/路径的进程，再恢复朗读。
4. **暂停 ELT 不会控制视频。请同时手动暂停播放器。暂停期间的新声音不会被缓存或转写。** 运行时长上限和稿件文件名分钟数仍按会话墙钟计算，包含暂停；稿件正文会注明手动暂停次数/秒数及未处理音频的边界。
5. 悬窗右上角“基础”直接调整朗读基础速度，范围 0.80–2.00 倍，每步 0.05，与主窗口双向同步并保存。自动追赶仍按积压门槛和缓冲期生效，最多基础速度的 1.5 倍；不增加翻译请求或重合成已有声音。
6. 翻译超时、连接错误、限流或服务不可用时，已确认原文继续显示。较早的已结束原文仍等待中文、而下一句开始识别时，也会保留为原文卡片。实时识别继续更新下方预览。对应 revision 的完整中文后来返回时，在原卡片补上；迟到的旧句不会把焦点拉回去。

“中文暂不可用 · 原文已保留”不表示翻译成功。仍在重试时显示等待中文，不显示不完整流或旧 revision 的中文为最终结果。显示历史继续受“最近条数”限制（1–12），控制器保留最多128条；需要整节课记录时单独启用自动存稿。

## 实现与生命周期

- GUI → 后台 stdin 增加 `PAUSE`、`RESUME`，保留 `STOP`。指令串行，连接前、等待确认时和停止中禁用暂停按钮；10秒未确认则明确报错并停止，不能伪造已暂停。
- runner 控制线程设置显式传给 LiveSource 的线程事件，不操作 Qt、模型或网络。原生 ELT/1 协议不变。暂停通过原协议 STOP 排空已收音 PCM 并回收 helper；恢复创建新的捕获连接和 AudioProcessor，复核完整进程身份。ASR/VAD 模型没有重载。
- 分段重采样完成后，下一连接的样本索引接续上段；每帧仍用真实 WASAPI QPC 映射，暂停的墙钟间隔保留。生产线程不写日志或等待模型。音频队列维持原上限，暂停边界队列及流水线待应用边界各最多8项，溢出明确失败。
- 流水线先消费暂停前队列，再按准确采样边界提交结束窗口；任务持有 PCM 副本，然后清空滚动缓冲与 Silero LSTM/上下文，避免把两侧语音拼在同一窗口。继续沿用同一 ASR worker。
- 朗读通过 QAudioSink 的 suspend/resume 挂起/继续，保留当前播放缓冲与有界待播；不再提交下一条合成。正在生成的当前声音可以完成，仍受原32MiB上限约束。用户暂停和朗读错误是独立状态，继续不会撤销错误；继续后重新计算加速缓冲期。暂停时恢复原声音量，继续后按原设置降音量。
- 每次可重试翻译失败立即发布原文回退，再做原有有限重试，不增加重试次数、并发量或请求数量。焦点卡片按 segment/revision 更新，回退不更改后端 Final/历史成功状态。有效迟到译文原位更新，动画期间延后重排，保持推送过程连续。
- 焦点位置由 UISettings 验证为有限的0–1坐标，旧配置缺省为(.5,.5)，恢复外观默认值也重置坐标。渲染层只发出位置/语速信号，仍不管理捕获、CUDA 或 API。

官方接口核对：[Qt QAudioSink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QAudioSink.html)。本机继续使用已安装的 PySide6 6.8.3，无依赖升级。

## 修改文件

- 界面：`app/ui/focus.py`、`overlay.py`、`captions.py`、`preferences.py`、`window.py`、`appearance.py`、`controller.py`、`runner.py`。
- 收音/识别：`app/main.py`、`app/asr/cli.py`、`source.py`、`pipeline.py`、`vad.py`。
- 翻译/存稿：`app/translation/cli.py`、`worker.py`、`runtime.py`、`app/subtitles/transcript.py`。
- 验证：`tests/unit/test_capture_pause.py`、`test_pause_and_focus_controls.py`，旧 CLI 测试替身更新为接收新增可选参数；`tools/check_capture_pause.py`、`tools/check_focus_overlay.py`。

## 实际结果

环境：本机 Windows 11 x64，Python3.12.10、PySide6 6.8.3，现有原生捕获程序。以下不加载 ASR/TTS 大模型，不调用 DeepSeek，不保存 PCM。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 最终全量自动回归 | 624通过，1项显式现场音频测试未启用，44.57秒；包括暂停边界两侧时钟归属检查 | [完整输出](evidence/focus-pause-pytest-release-20261103.txt) |
| 队列边界/控件专项回归 | 97通过，7.60秒，含新增溢出测试 | [输出](evidence/focus-pause-final-targeted-20261103.txt) |
| 真实 Windows stdin 控制 | PAUSE/RESUME/STOP 均收到真实子进程响应，通过 | 自动测试 `test_real_windows_runner_control_pipe_pause_resume_stop` |
| 10次开始/暂停/继续的生命周期逻辑 | 测试替身下连接全部释放、采样连续，通过；不冒充真实设备10次验收 | `test_ten_pause_resume_cycles_close_helper_and_keep_sample_axis_contiguous` |
| 真实进程音频三次暂停/继续 | 通过；4个真实helper，暂停无PCM入队且helper已回收，重新连接后采样连续，墙钟间隙保留，捕获1.6秒非零归一化音频 | [真实音频报告](evidence/focus-pause-real-capture-20261103.json) |
| 暂停时停止、暂停时目标退出 | 真实短测通过，无残留连接；不绑定重启后的新PID | 同上 |
| 实际Qt动画/排版 | 自选(.65,.40)焦点、上推、原文回退、下方预览、迟到中文同卡补齐通过；明确标注测试文字 | [结果](evidence/focus-controls-layout-final-20261103/results.json)、[超时布局](evidence/focus-controls-layout-final-20261103/fallback.png) |
| EXE启动 | 退出码0，真实窗口创建，无捕获启动 | [启动结果](evidence/focus-pause-exe-startup-20261103.json) |

恢复指令到收到15帧（约0.3秒音频）的三次墙钟观察为0.406/0.421/0.437秒，包含连接准备和收音；样本极短，不能作为识别、中文或朗读端到端延迟指标。未重新执行付费 DeepSeek 真网故障测试或 GPU 联合推理。完整课程质量、30/60分钟、混合DPI、多显示器和独占全屏验收仍待执行。

## 复现

在项目目录运行（报告路径/测试临时目录选择不存在的新名字）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests -q -rs -p no:cacheprovider --capture=sys --basetemp docs/evidence/my-new-pause-tests
.\.venv\Scripts\python.exe -B tools/check_capture_pause.py --output docs/evidence/my-new-pause-audio.json
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -B tools/check_focus_overlay.py --output docs/evidence/my-new-focus-layout --focus-x 0.65 --focus-y 0.4
```

第二条会播放本工具自己的短测试音，不操作用户播放器。人工验收时选中实际音源并正常开始，拖动焦点、调语速、暂停/继续；确认暂停时视频由自己控制，恢复后不重播暂停内容。若需要检验真实服务故障，可在自己的会话中临时断开网络，观察原文继续，然后恢复网络；仅尚未过期、仍允许重试的请求可补齐，不承诺永久失败的旧字幕自动补译。
