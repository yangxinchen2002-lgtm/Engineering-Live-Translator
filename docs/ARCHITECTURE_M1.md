# M1 本地转写架构

2026-11-03 用户授权新增日语；固定/Auto 接受 ja，同一个现有模型做 transcribe。日语时间戳片段合并及拼接规则见 [JAPANESE_SUPPORT.md](JAPANESE_SUPPORT.md)，原德英性能/质量报告不作为日语测试结果。

M0 的 native API、帧协议、PID 身份校验和 PCM 转换保持不变。M1 只增加本地 ASR，不创建翻译、字幕协调器或 GUI。

数据流：LiveSource（M0 捕获/标准化）或 FileSource（PyAV）→ 有界接收队列 → AudioRing + SileroStream → Scheduler → 独立 spawn ASRWorker → TranscriptStabilizer → UTF-8 CLI 事件。

## 输入输出与生命周期

| 模块 | 输入/输出 | 失败及关闭 |
|---|---|---|
| ASRConfig | TOML/显式覆盖 → 校验后的固定配置 | 未知键、无效范围拒绝，不选择替代模型 |
| CourseTerms | 显式本地课程词表 → 有界 hotwords / 身份散列 | 默认关闭；启动时读取一次、检查真实 token 数；错语言/超限失败；Auto 锁定前不提示 |
| LiveSource | 目标身份 → 16k Float32 InputFrame/每帧单调时钟 | 单一自有线程负责 pipe；不写控制台；溢出单独标记错误；STOP/退出回收 helper |
| FileSource | 显式本地文件/第一音轨 → 相同 InputFrame | PyAV 真实解码/重采样；RT 模式按时钟，快速模式允许阻塞磁盘生产；EOF 显式尾帧 |
| AudioRing | 连续样本 → 音频副本与分段时钟映射 | 严格检查采样间隙、有限容量；不覆盖未使用区间 |
| SileroStream | 任意 20ms 帧 → start/end speech 事件 | CPU ONNX 一次加载，512 样本推理 + 64 样本 context，保留 h/c 状态；滞回/最短语音/静音 |
| Scheduler | VAD/样本时间轴 → 必须处理窗口与可替换预览 | 窗口默认 8s、重叠 2s、每 1s 预览；必须窗口满则明确失败 |
| ASRWorker | 单个 ASRJob → 带全局词时间戳的 ASRResult | CUDA/float16、beam1、transcribe；一次加载；真实 warmup 后就绪；推理/启动超时，异常回传 |
| TranscriptStabilizer | 连续假设 → candidate / stable / committed 增量 | 比较词与时间，不截字符串；拒绝乱序；保留边界候选并标注未确认 |
| LanguagePolicy | 固定语言或检测输出 → 会话语言锁 | Auto 需要间隔至少 1s 的 3 次高分同语言检测；锁定后不因短术语切换；新会话重置 |
| Diagnostics/evaluation | 事件/参考字幕 → 性能/质量统计 | 单调时钟；网络未参与推理；日志仅显式保存；参考文本从不输入模型 |

## 并发与容量

Python 主程序使用 asyncio；阻塞音频 IPC/解码在自有接收线程；CUDA 推理在独立进程。C++ 音频线程不等待 ASR、控制台或未来 GUI。

| 位置 | 默认容量/策略 |
|---|---|
| M0 native SPSC | 256 包 / 4 MiB，溢出错误 |
| Python 接收队列 | 256 个 20ms 帧，RT 不等待，满即错误 |
| AudioRing | 16 秒，只丢弃当前窗口之前的已复制区间 |
| 必须处理 ASR 窗口 | 最多 3 个，顺序处理，不能替换 |
| 待处理预览 | 最多 1 个，替换时记录 skipped 事件 |
| worker 输入/输出 | 1 / 2 个消息；同一时间只运行一个推理 |
| 稳定器 | 1024 词假设上限、256 词已提交边界历史 |

实时过载时不会默默扩大队列或静默删除未经处理的语音。快速文件模式可以暂停读取并等待队列，是测试磁盘输入时明确的背压策略；不能据此推出实时性能。

## 稳定与提交

比较使用 Unicode NFKC、casefold、忽略标点的词键，显示保留最新文字。首词通过时间约束找相邻假设中的锚点，之后只确认连续一致前缀；保留尾部 0.3s，处理复合词修订、缩写、大小写和重叠窗口。真实重复词依靠时间区间区分。

LA 确认的词为 `stable`，同时进入已提交历史。VAD/EOF 的尾部可按 `endpoint_commit` 提交，状态为 `committed`；它不是双次确认。若预览被替换、前一候选离开新窗口，则显式发出 `window_boundary_unconfirmed` 的 committed 增量，不丢失该文字，也不把它伪装成稳定确认。候选更新允许修订，已提交增量不重复追加。没有使用 Whisper 分数作为词级正确率。

异常重复不是稳定算法能修正的可靠事实。检测到极不合理的词速率/短 n-gram 循环时，最多再调用一次真实模型，显式启用 repetition_penalty=1.05 / no_repeat_ngram_size=4，并记录重试。不会正则删掉错误词；第二次仍异常则返回错误。该守卫不是识别准确率模型。

## 时钟、指标和真实边界

M1 全链路统一使用 `perf_counter_ns()`：在本机 Python 3.12 上它是单调的 QueryPerformanceCounter。**不使用 GetTickCount64 的 monotonic_ns 与 WASAPI 混算。** LiveSource 验证 WASAPI QPC 的 100ns 时间戳年龄/时基，显示时禁止明显负的模型延迟。采样坐标与墙钟分别保存。每个推理任务携带帧级时钟跨度；另保留有限历史时钟以支持离开当前 PCM 窗口的旧候选，因此暂停无包造成的时间间隔不会被连续采样数抹平。因果 FIR 群延迟计入采样到时间的映射。

快速文件的时钟只是标注，不给实时延迟。RT 文件源以每帧结束时刻喂入，基于真实 monotonic 时钟。在线 preview_latency_seconds 是每个 VAD 段首次可见文字的延迟分布；stable_commit_latency_seconds 只含 LA 提交。候选修订、停顿尾部提交和未确认边界提交单独可审计。延迟基准是识别词组结束，不是请求开始或整句开头；另记音频开始至显示时间。不能把在线值称为人工参照片段的正式延迟。

参考评估通过 WER 对齐和带时间约束的事件匹配，另算字幕 cue 结束至显示时间；完整匹配的子集有 P50/P95，但同时必须公布未匹配数量和 ALL-cue 时限覆盖率。字幕时间、文字删改和非语音标签本身带来误差，不隐瞒覆盖率，不用匹配子集单独宣布目标达成。

GPU 监测为 nvidia-smi 的**总设备显存**，包含其他应用，不能当作模型专属显存。模型加载、warmup、推理、队列等候和文字显示分别记录；模型开始采集前的启动时间另列。

## 清理与故障

正常结束先排空必须窗口；取消/错误不宣称完整。finally 停止音频线程/捕获 helper、监测和模型工作进程；工作进程超时后终止。Windows Job Object 启用 KILL_ON_JOB_CLOSE，即使父进程被强制结束，也不会让模型 worker 永久孤立。不会默认切换 CPU、量化类型或更小模型。
