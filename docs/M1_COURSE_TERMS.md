# M1 课程术语提示试验

用户明确授权在 M1 中尝试课程专用术语。没有进入 M2。范围是本地 ASR 的可选 hotwords，不是翻译术语表、规则替换、训练或微调。

## 接口与生命周期

`--course-terms 文件.toml` / `[asr].course_terms` 选择词表，默认关闭；`--no-course-terms` 覆盖配置关闭。CLI 路径相对当前目录，配置中的路径相对配置文件所在目录。

文件格式：

```toml
version = 1
name = "Control engineering"
language = "de"
sources = ["自己的课程讲义或公开课程页面"]
terms = ["Eigenwert", "Eigenvektor", "Übertragungsfunktion", "Zustandsraum"]
```

仅使用源语言术语，不写中文解释或参考答案。每次模型工作进程启动时读取一次，保留本次文件散列；运行中修改不会悄悄改变当前会话，下次启动生效。读取上限 16 KiB / 48 条 / 每条 80 字符；拒绝重复、控制字符、未知字段、错误版本及错误语言。模型加载后用实际 tokenizer 检查最多 128 token，超过即报错，不使用 Faster-Whisper 内部的静默提示截断。

固定语言必须匹配。Auto 的最初检测窗口不带 hotwords；会话语言锁定后，匹配词表语言才应用，不因选择词表而强行指定检测语言。`asr_model_ready.course_terms` 记录身份，`asr_result.course_terms_applied` 和 `asr_summary.course_terms_jobs` 记录实际使用情况。

热词只通过 `model.transcribe(hotwords=...)` 传入每次推理；有限重复重试保留相同提示。没有添加 initial_prompt、prefix 或前文提示；没有改 beam_size、模型、窗口或 VAD 参数。关闭时不传 hotwords，保留原始基线。词表验证和 token 检查发生在主动捕获之前，不给捕获线程增加文件或 tokenizer 工作。

依据：[Faster-Whisper 1.2.1 transcribe/get_prompt 实现](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)。

## 两套试验词表

- `config/courses/de-firmware.toml`：16 条。项目名称参考 [CCC 讲座概述](https://media.ccc.de/v/35c3-9778-open_source_firmware)，加常用固件/系统术语，包括 Firmware、BIOS、UEFI、Kernel、Prozessor、Speicher、Betriebssystem 等。
- `config/courses/en-linear-algebra.toml`：12 条。课程范围参考 [MIT 第一讲简介](https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/resources/lecture-1-the-geometry-of-linear-equations/)，包括方程、矩阵、向量、行、列等词形和短语。

这不是盲测词表：选择时已知上一轮前 900 秒的薄弱术语，因此原区间明确属于开发集。没有复制参考字幕句子、变量值或预期答案。另选后续 900–1200 秒中的完整字幕区间作为本次未调参验证；它仍来自相同讲者/课程，不能代表所有新课程的泛化。

## 对照方法

```powershell
.\.venv\Scripts\python tools/compare_course_terms.py --output 'D:\MyTests\new-course-trial'
```

要求已经按 M1 README 获取素材并完成基线 benchmark。默认读取 `docs/evidence/m1-realtime-15min-v1` 的原始 job 计划；也可用 `--baseline-dir` 指定自己完整的 900 秒基线目录。

前 900 秒重放已记录的全部窗口（包含预览），每个窗口依次执行关闭/开启提示两次真实 GPU 推理，轮换两者先后次序，使用同一已加载模型。两组各自维护原样的 Local Agreement 稳定器。参考仅用于评分，不输入模型。

后续验证区间以参考 cue 边界截取，用相同 VAD/滚动调度生成新计划，再对两组重放完全相同的窗口。此计划不依赖模型输出；没有用两组各自运行速度产生不同窗口。区间边界、计划、词表内容与散列、源代码散列、逐窗口推理及评分全部保留。

这是**离线受控质量对照**，不是又一次实时采集。仅发布模型推理耗时，不把加速重放计为字幕显示延迟。真实 CLI/VLC 另行验证。

指标保留原始 WER（替换/删除/插入）；既有术语的正确匹配出现次数，另统计词表中所有提示词。补充术语 precision 与未对齐预测次数，避免只提高术语召回却增加多余术语。未对齐次数包含拼写/对齐差异，不能全部直接称为幻觉。原始字幕的口语、数学记法和标签局限仍适用。

## 结果

证据目录：`docs/evidence/m1-course-terms-paired-v1`，`comparison.json.complete=true`，工具返回 0。逐窗口记录见 decodes.jsonl，确切窗口见各语言 plan.json。总计 **2410 个相同窗口 × 两组 = 4820 次主解码任务**，另有明确记录的有限重试。没有替换参考或删除错误输出。

德语词表 16 条 / 实际 63 token；英语词表 12 条 / 实际 27 token。测试使用本机 M1 的 RTX 3500 Ada、固定 large-v3-turbo、CUDA Float16 及已验证依赖组合。关闭组的前 900s WER 完全复现上一轮基线。

| 区间 | 关闭 WER | 开启 WER | 关闭/开启所选术语匹配 | 关闭/开启未对齐预测术语 |
|---|---:|---:|---|---|
| 前 900s，883 个相同窗口 | 12.979% | 13.510% | 66/81 → 66/81 | 3 → 4 |
| 后续完整字幕区间，305 个窗口 | 11.218% | 11.111% | 13/17 → 13/17 | 0 → 3 |

上表为德语；后续完整区间为 **901.949–1198.679s**。英语结果如下，后续区间为 **902.680–1198.820s**：

| 区间 | 关闭 WER | 开启 WER | 关闭/开启所选术语匹配 | 关闭/开启未对齐预测术语 |
|---|---:|---:|---|---|
| 前 900s，916 个相同窗口 | 6.510% | 6.406% | 85/86 → 86/86 | 0 → 0 |
| 后续完整字幕区间，306 个窗口 | 10.379% | 10.708% | 28/28 → 28/28 | 0 → 0 |

开发集的替换/删除/插入：183/71/88 → 188/81/87，总错误增加 14 个。Firmware 从 40/50 到 41/50，Prozessor 从 3/5 到 2/5；Kernel 仍为 0/3，没有用总数掩盖局部退步。验证区间总错误仅减少 1 个（105 → 104 / 936 参考词），同时插入从 19 增至 23。该差异不足以证明实用改善，暂不推荐把此德语词表默认开启。

英语开发集从 125 到 123 个词错误（1920 参考词），验证集从 63 到 65 个错误（607 参考词）。开发集的小幅收益没有在后续片段保持；没有因局部术语 100% 就宣称整段字幕正确率 100%。表中术语匹配仅覆盖预先列明的少量词，完整词表计分另见 prompted_terms_score。

解码 P50 约 **0.19–0.22s**，具体 P50/P95/总耗时在 comparison.json；不凭毫秒级差异宣称性能提升。开启提示触发的重复重试在德语开发/验证为 2/5 次，英语为 2/1 次；关闭组对应为 0/0、1/0 次。均为真实重解码后继续，未发生第二次仍异常的失败。更多重试说明仅看中位耗时会遗漏代价。

**结论：这两套样例词表没有稳定降低整体 WER。** 功能实现与效果改善分开验收：可选词表可运行，仍保持默认关闭，不把这些样例推广为通用准确率提升。后续如另选词表，应另留新的未调参音频评估，不反复用已经查看的验证区间挑选最佳参数。

最终自动回归：**116 passed, 1 skipped，12.06s**，stderr 为空。证据为 `docs/evidence/course-terms-pytest-final.txt`。跳过项仍为需显式启用的 M0 五秒实机 smoke；本次真实词表链路另行执行。覆盖词表 schema/文件/条目/token 边界、相对路径/关闭覆盖、语言保护、worker 实际选词表逻辑、重试保留提示、关闭时原参数不变、术语多报统计、窗口计划的顺序和全局采样坐标。

## 真实 VLC 链路与清理 — 已完成

质量对照结束后才开始实机链路，未并行启动第二个 GPU 识别实例。工具只控制自己创建的 VLC、CLI 与模型进程：

```powershell
.\.venv\Scripts\python tools/live_m1_checks.py --output 'D:\MyTests\new-hinted-en' --seconds 60 --languages en --course-terms config/courses/en-linear-algebra.toml --failures
.\.venv\Scripts\python tools/live_m1_checks.py --output 'D:\MyTests\new-hinted-auto' --seconds 60 --languages auto --auto-sample de --course-terms config/courses/de-firmware.toml
```

证据：`docs/evidence/m1-course-terms-live-en/results.json`、`m1-course-terms-live-auto-de/results.json` 和各目录 JSONL。

| 模式 | 音频 | 推理/实际加提示 | LA 提交 P50/P95 | 结果 |
|---|---:|---:|---:|---|
| 固定英语 | 59.99s | 53/53 | 1.286/1.782s | 完整结束，暂停恢复通过 |
| Auto 德语 | 59.99s | 39/34 | 1.501/2.524s | 前 5 次未加提示，锁定 de 后加入；暂停恢复通过 |

两次均无报告的音频缺口/队列溢出/预览跳过/计时错误；恢复两秒后仍分别有 47/40 条原文事件。实际词表 SHA 与质量对照完全一致。上表延迟仍以模型识别词组结束为基准，不能替代人工片段延迟。GPU 总设备显存观测峰值为 3901/3900 MiB，包含其他应用。

目标退出按预期返回错误码 1、complete=false，明确要求重新选择 PID，0.547s 内结束。强制结束测试工具自己的主进程后，GPU worker 与 native helper 均在 0.266s 内观察到退出。故障用例在模型就绪并开始捕获约 3s 后触发，覆盖加载和捕获状态，推理繁忙状态的故障压力测试仍待执行。

最终审计见 `docs/evidence/course-terms-delivery-audit.json`：Auto 的实际提示任务提交时间均在语言锁定之后；两个词表身份匹配；所有配对试验期间 app 源码散列与交付一致；本次四个 GPU worker 均已不存在。原生 helper 残留为 0，见 `course-terms-cleanup-final.json`。依赖、编译和新参数帮助检查全部返回 0，见 `course-terms-static-final.json`。

## 修改文件及交付判断

- `app/asr/course_terms.py` 与 `config/courses/*.toml`：有界词表与两套样例。
- `app/asr/config.py`、`cli.py`、`worker.py`、`decoding.py`、`types.py`、`pipeline.py`、`app/main.py`：显式开关、实际参数传递、语言保护和诊断。
- `app/asr/evaluation.py`：额外报告预测术语次数与 precision，保留原 WER 算法。
- `tools/compare_course_terms.py`、`live_m1_checks.py`：配对质量和真实链路验证。
- `tests/unit/test_course_terms.py`、`test_asr_decoding.py`、`test_asr_evaluation.py`、`test_asr_worker_failure.py`：新增自动覆盖；README、架构、决策与开发计划同步更新。

课程词表功能已交付、可测试，质量收益未通过本次对照。保持默认关闭，用户可明确指定自己的课程词表试用；不能据此承诺降低所有课程的错误率。下一步可另行对照 beam_size=3/5 或更长上下文，本次没有改动这些参数。工作仍停留在 M1。
