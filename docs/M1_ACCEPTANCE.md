# M1 验收报告 — 2026-10-30

阶段：M1，本地德语/英语转写。本轮没有 DeepSeek、翻译队列、双语字幕协调器或 GUI；没有把项目标记为最终 MVP 完成。

后续用户授权的课程术语提示试验见 [M1_COURSE_TERMS.md](M1_COURSE_TERMS.md)。本文原始 900s 性能/质量记录保留为未启用术语提示的阶段基线；新增试验不改写这些历史结果。

## 环境与版本

Windows 11 Pro x64 Build 26300；Intel Core i7-13850HX；NVIDIA RTX 3500 Ada Laptop GPU，12282 MiB；驱动 597.16（nvidia-smi 显示的 CUDA 13.2 为驱动兼容能力）。

实际加载的项目本地运行库为 CUDA Runtime 12.4.127、cuBLAS 12.4.5.8、cuDNN 9.1.0.70，均从 NVIDIA 官方 redistrib 获取并核对 SHA-256，清单位于 tools/gpu-runtime/manifest.json。没有更改系统驱动或全局 PATH。

Python 3.12.10；Faster-Whisper 1.2.1；CTranslate2 4.6.0；ONNX Runtime CPU 1.23.2；PyAV 16.0.1；NumPy 2.3.5；SciPy 1.17.0；Hugging Face Hub 0.36.0；Tokenizers 0.22.1；setuptools 80.9.0；jiwer 4.0.0/rapidfuzz 3.14.3。完整依赖在 requirements-m1-lock.txt。

模型来自 mobiuslabsgmbh/faster-whisper-large-v3-turbo，revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`，本地目录加载。实际 device=cuda、compute_type=float16；beam_size=1、temperature=0、task=transcribe、word_timestamps=True、vad_filter=False、condition_on_previous_text=False。外部 Silero v6 ONNX 在 CPU 上持续运行；同一模型会话只加载一次。

兼容性是真实推理验证，不是只根据显存猜测。最初安装的 setuptools 84 缺失 CTranslate2 4.6 需要的 pkg_resources，明确失败后固定 80.9.0，未静默升级模型或转 CPU。该依赖的 deprecation warning 保留；后续升级需要重新验证组合。

## 实际实现

- 复用 M0 原生进程树捕获、命名管道与 PCM 标准化。
- 独立音频接收线程、asyncio 调度、独立 spawn GPU worker，模型启动完成后才主动开始捕获。
- 512 样本 Silero 流式 VAD，保留 LSTM/context 状态、滞回、最短语音、静音结束。
- 默认 8s 窗口/2s 重叠/1s 调度；有限必须窗口队列与可替换预览，过载明确失败。
- Local Agreement、词时间戳对齐、复合词/缩写/标点归一、重复/重叠处理；候选、稳定与启发式提交分开输出。
- 固定 de/en 和 Auto 会话语言锁；窗口边界未确认词不丢失，也不冒充已确认词。
- 有限重复幻觉重试、超时、取消、Windows Job Object 父进程死亡保护。
- 原文 CLI、配置、公开素材下载、WER/术语/重复事件/延迟覆盖率评估和 GPU/队列诊断。

## 素材、范围与评分

来源及许可/文本等级见 [M1_SOURCES.md](M1_SOURCES.md)。英语主样本是 Gilbert Strang 的 MIT 线性代数第一讲（原文件 2388.842s）；德语主样本是 zaolin 的 Open Source Firmware（原文件 2978.88s）。各取最初 900 秒；音频文件均为 48kHz，文件源通过 PyAV 真实解码为 16k mono Float32。

这些是官方发布字幕参考，德语正式 SRT 署名 c3subtitles.de、2019，无 DRAFT 标记；未由本项目对整段逐字重新人工审校。存在非语音标记、说话人标签、数学数字与口头语编辑差异。神经网络讲座的 DRAFT 仅用于 smoke，未作为主验收准确率基准。参考文本没有输入 ASR 模型。

WER 的标准化及术语分母固定；所有错误类型、各词出现次数完整记录。没有根据输出修改字幕或删掉识别错误。时戳重叠的重复词事件比例与 excess 3-gram 诊断是代理指标，不能宣称为人工判定的完整重复字幕率。

## 已完成的测试和证据

最终自动回归：**95 passed, 1 skipped，11.05s**，证据为 `evidence/m1-pytest-final.txt`，stderr 为空。跳过的是需要显式 `ELT_RUN_HARDWARE=1` 的 M0 五秒捕获测试；本次另用下述独立工具执行了真实 M1 VLC/GPU 链路，不能把这项跳过写为 pytest 通过。M0 原生源码未修改，既有 2 项 CTest 结果见 M0 报告。

覆盖 PCM/协议回归、Ring 时间映射/溢出、VAD 防抖、真实 ONNX 状态连续性、调度覆盖/预览替换/必须队列溢出、词稳定/复合词/缩写/重复、边界保留、Auto 防抖、缺 GPU 禁止回退、模型/推理超时、取消清理、解码重试控制逻辑、参考评分、延迟覆盖率和跨时基错误拒绝。解码重试的单元测试使用测试替身；下面的英语长测另有一次真实模型重试证据。`pip check` 无依赖冲突，Python 编译检查通过。CTranslate2 的 pkg_resources 弃用提示仍存在，不作为运行错误忽略或删除。

### 15 分钟加速文件测试（不是实时延迟结论）

初始德语运行完整处理 900s，154 个推理任务，49.203s 会话墙钟（包含启动），推理 P50 0.250s/P95 0.281s；对官方原始字幕 WER 13.55%、所列术语 76.54%。预览被有意替换 729 次，必须窗口全部处理；启发式提交 2133/2622 词，因此不把这个模式的稳定数量当作实时体验。

初始英语加速运行出现一次极短结尾音频的重复幻觉；旧日志保留 `m1-en-900-fast.jsonl`，其原始 WER 19.01% **不是最终改进后结果**。没有正则删除重复词来伪装成功，而是加入有限、可诊断的真实重新解码。最终真实时间运行会独立评分并记录重试。

### 15 分钟德语真实时间测试 — 已完成

证据：`evidence/m1-realtime-15min-v1/de.jsonl`、`de-final-report.json`、`environment.json`。final-report 在原始日志上补算参考覆盖率和重复事件，未重新写入识别结果。

- 按采样时钟输入全部 900s（14,400,000 样本），883 次真实推理；会话 910.469s，含约 10.5s 启动/关闭开销。
- 队列无溢出，预览跳过 0，未报告音频缺口；输出 2652 个提交词，其中 2546 为 LA 确认，106 为显式启发式提交。
- WER **12.979%**：替换 183 / 删除 71 / 插入 88；参考 2635 词。
- 术语逐次准确匹配 **66/81 = 81.481%**。Firmware 40/50，Prozessor 3/5，Speicher 4/4，BIOS 6/6，Intel 8/8，Kernel **0/3**，Betriebssystem 5/5；UEFI 未出现，不计分母。
- 模型词结束时钟口径：VAD 段首次显示 31 个样本，P50 **0.253s** / P95 **0.861s**；LA 提交 687 个事件，P50 **1.341s** / P95 **2.016s**。
- 推理 P50 **0.203s** / P95 **0.265s**。GPU 总设备显存观测峰值 **3831 MiB**，包含其他应用，非模型独占显存。
- 时戳重叠重复词事件 **0/2652**；这是时戳代理指标，不是人工核查的字幕重复率。
- 参考字幕口径：204 cue 中 59 条完全匹配（28.92%）；此子集预览 P50 **0.530s** / P95 **1.457s**。50 条可全量追溯至 LA 的子集，P50 **1.391s** / P95 **2.413s**。全部 cue 在 2s 内完全匹配并可见为 **58/204**；不能只凭子集 P50 宣布整个样本达标。负值原样保留，反映字幕时间或对齐误差。

德语测试后补齐了“暂停时没有音频包”的分段时钟保存；对连续等间隔文件时钟，原换算与分段换算相同。英语及最终 VLC 链路使用分段实现。原始源文件散列和英语运行时源文件快照都保留，未将不同采样路径混为同一设备验收。

### 15 分钟英语真实时间测试 — 已完成

证据：`evidence/m1-realtime-15min-v1/en.jsonl`、`en-final-report.json`、`en-source-snapshot.json`。

- 按采样时钟输入全部 900s（14,400,000 样本），916 次真实推理；会话 **911.485s**，包含启动/关闭。
- 无队列溢出、无预览跳过、无报告的音频缺口。1963 个提交词事件，其中 1734 为 LA，229 为显式启发式提交；去空白/标点归一后的评分词数为 1960。
- WER **6.510%**：替换 49 / 删除 18 / 插入 58；参考 1920 词。
- 术语逐次准确匹配 **85/86 = 98.837%**：matrix 13/13，vector 10/10，vectors 2/2，linear 13/13，equation 12/12，equations 10/10，column 18/18，row 7/8；matrices 未出现，不计分母。
- 模型词结束时钟口径：VAD 段首次显示 117 个样本，P50 **0.305s** / P95 **0.719s**；LA 提交 625 个事件，P50 **1.294s** / P95 **1.787s**。
- 推理 P50 **0.187s** / P95 **0.234s**。GPU 总设备观测峰值 **3834 MiB**。重复幻觉重试 **1 次**，真实重新解码后继续，无参考文本注入。
- 时戳重叠重复词事件 **2/1960 = 0.102%**，保留错误，未宣称零重复。
- 252 个参考 cue 中 194 条完全匹配（76.98%）；匹配子集预览 P50 **−0.092s** / P95 **0.728s**；118 条可追溯至 LA 的子集 P50 **1.153s** / P95 **1.754s**。全部 cue 的 2s 预览覆盖为 **194/252**，3s LA 覆盖为 **118/252**。负参考延迟没有裁零，可能来自字幕时间滞后或对齐误差，不代表模型能预知未来语音。

两个 15 分钟测试串行运行，没有另一 ASR 实例同时争用 GPU。其输入和输出同用当时的 GetTickCount64，时基一致，**分辨率为 15.625ms**；不当作最终高精度 QPC 测量。下述最终版本另对真实 VLC 和按时钟文件输入重验。

### 最终 VLC → C++ → Python → GPU、Auto、退出/强制终止 — 已完成

证据：`evidence/m1-live-v2-qpc/results.json` 及同目录各语言 JSONL；英语 Auto 补充证据 `evidence/m1-auto-en-qpc/results.json`。

每种模式使用工具自行创建的 VLC 实例播放公开讲座，模型 ready 后恢复播放；约第 28 秒暂停、31 秒恢复，总计 60 秒捕获。没有以 mock 代替 Windows 捕获或 GPU 推理。

| 模式 | 接收音频秒数 | 推理次数 | 首次原文 P50 / P95 | LA 提交 P50 / P95 | Auto 锁定 |
|---|---:|---:|---:|---:|---|
| 固定德语 | 59.99 | 41 | 0.773 / 0.999s | 1.390 / 2.479s | 固定 de |
| 固定英语 | 59.98 | 54 | 0.213 / 0.445s | 1.274 / 1.748s | 固定 en |
| Auto，德语素材 | 59.96 | 39 | 0.940 / 1.064s | 1.343 / 1.688s | de |
| Auto，英语素材 | 59.98 | 54 | 0.435 / 0.628s | 1.273 / 1.793s | en |

以上延迟以识别词组的结束时刻为基准，首次原文按 VAD 段统计，样本数量分别为 4/8/3/8，LA 事件数为 22/30/24/32。短测规模有限，不能替代人工片段延迟或长时间稳定性验收。四次均完整结束、无报告的音频缺口/溢出/预览跳过/计时错误，恢复后继续产生原文；GPU 总设备峰值均为 3797 MiB。

- **目标关闭**：返回预期错误码 1、complete=false，明确 `target_exited_select_again_for_new_PID`；0.594s 内完成关闭。不是成功转写完整课程。
- **强制终止主程序**：对工具自己的实际主进程终止，原生 helper 和 GPU worker 的进程句柄都在 **0.375s** 内观察到退出；Windows Job Object 生效，没有把仅退出 venv 启动器误认为关闭主程序。
- **计时修复**：最初 Live V1 将 WASAPI QPC 与 Python 3.12 的 GetTickCount64 混算，出现约 −35s 的虚假模型延迟；Auto 还暴露了滚动窗口之外候选的时钟历史缺失。这些旧失败保留于 `m1-live-v1`，**不计为通过**。当前 M1 全链路统一 `perf_counter_ns`/QPC，记录时钟实现并检查包龄、拒绝异常负模型延迟，保留有界历史映射。上表来自修复后的重新运行。

最终按时钟文件输入检查见 `evidence/m1-final-file-qpc`：当前版本完整处理英语 **45s / 720,000 样本 / 38 次推理**，无计时错误或预览跳过；LA 提交 P50 **1.302s** / P95 **1.795s**，推理 P50 **0.174s** / P95 **0.212s**。这是最终 QPC 文件路径回归，与 900s 基准区分版本，不把短测准确率冒充长测准确率。

最终审计 `evidence/m1-delivery-audit.json` 包含代码/配置 SHA-256、时钟实现、恢复后输出及采样的队列长度。四次真实 VLC 测试在恢复两秒后分别还有 42/43/42/45 条原文事件。所检查的 7 个最终测试 GPU worker 均已不存在；原生 helper 残留 **0**，见 `m1-cleanup-final.json`。DLL/设备检查、依赖与编译检查见 `m1-runtime-final.json`、`m1-dependencies-final.txt`、`m1-static-checks-final.json`。设备枚举本身不当作推理通过依据。

## 主要新增和修改文件

- `app/asr/`：配置、输入、缓冲、VAD、调度、GPU worker、Local Agreement、语言、时钟、评估与 CLI；`app/main.py` 接入命令，不加载 CUDA 到界面线程。
- `config/asr.toml`、`pyproject.toml`、`requirements-m1-lock.txt`：集中参数和实际验证依赖。
- `tools/setup_gpu.py`、`prepare_model.py`、`check_m1.py`：本地环境准备与诊断。
- `tools/fetch_m1_samples.py`、`benchmark_m1.py`、`evaluate_asr.py`、`live_m1_checks.py`：真实素材、评分与实机复验。
- `tests/unit/test_asr_*.py`、`test_reference_latency.py`、`tests/integration/test_silero_cpu.py`：自动回归。
- README、ARCHITECTURE_M1、M1_SOURCES、本报告、DEVELOPMENT_PLAN、DECISIONS 与 `docs/evidence/`：接口、来源、验收及保留的失败/重跑证据。

## 已知局限与验收判断

**交付判断：M1 功能与上述实测已完成，等待用户验收；完整人工质量验收仍有待执行项。** 德语 Firmware、Kernel 等专业词仍有实质错误；原始参考还有字幕编辑和数学记法差异，应逐条核查关键否定、数字、变量和术语。公开素材没有经本项目逐字重新人工审校，不能将本报告当作任务书所要求的最终人工 gold 质量认证。没有把 Whisper 词分数当作可靠正确概率。

模型词时钟和匹配参考子集的延迟结果不可直接代替全部可理解语音片段的人工测量。M1 的 2s/3s 是优化目标，此报告不无条件宣布总体达标。没有进行新的 60 分钟稳定性测试，也没有实现翻译/GUI，未标为通过。

M1 未重新执行完整的 10 分钟双音源隔离；相关 M0 实机证据与窄带频偏局限继续有效，见 ACCEPTANCE.md。Auto 采用会话语言锁；不会逐词切换语言，也不保证任意比例的德英混讲均准确。当前为 JSONL 调试 CLI，用户界面留给后续阶段。

日志保存默认关闭；本报告证据是测试时显式启用的文字/诊断文件，没有新录制原始课程音频。素材是用户授权下载的公开文件。

## 用户复验

1. 按 README 安装锁定环境、本地运行库和固定模型，运行 tools/check_m1.py。
2. 暂停 VLC，list 选择实际 PID；运行 asr-live，模型 ready 后恢复课程，观察 UTF-8 原文事件。
3. 验证 candidate 修订、stable（LA）与 committed（停顿/边界）原因；不要把每条候选重复追加为字幕历史。
4. 分别运行 de/en/auto；Auto 锁定后短外语术语不应使会话语言跳变。
5. tools/fetch_m1_samples.py 后，tools/benchmark_m1.py --output 新目录 --seconds 900 执行两个 15min RT 测试；加速文件命令仅用于吞吐/质量。
6. 用 tools/evaluate_asr.py 复算 WER/术语，并用 --reference-latency 报告覆盖率；核查数字和否定等关键语义。
7. tools/live_m1_checks.py --output 新目录 --seconds 60 --include-auto --failures 进行真实链路及故障检查（会播放测试讲座）。
8. 本阶段结束后等待用户验收；不自动进入 M2。
