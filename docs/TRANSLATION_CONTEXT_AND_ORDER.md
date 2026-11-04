# 翻译上下文限制与长短句乱序显示修复 — 2026-11-03

阶段：M2/M3 已授权范围内的翻译与显示修正。重启当前桌面快捷方式或根目录 `ELT.exe` 生效，沿用现有密钥、模型和用户设置。没有调用付费 API、下载模型或修改原生捕获程序。

## 检查结论

原实现每次请求已经只包含系统规则、当前原句、最多5条已确认句对（历史预算2800字符）和相关术语，不会随整节课无限增长。DeepSeek 的 Chat Completions 本身是无状态接口，请求之间的上下文取决于本地发送内容。[官方说明](https://api-docs.deepseek.com/guides/multi_round_chat/)

原有裁剪存在两个可改善点：内存中的已完成上下文只按条数裁剪；发送时遇到放不下的新句会跳过它，可能重新选择更早的短句。现在内存和发送阶段均严格删除最早的完整句对，保留连续的最近内容，并增加完整 messages 的长度上限。

没有找到足以将用户先前实际超时与逐次请求大小关联的证据：原诊断不记录这些大小，GUI 诊断默认只在内存中保存，结束后不会自动写文件。因此**不能认定之前超时就是上下文过长**。原配置仍为连接3秒、单次请求12秒、任务总有效期24秒，服务排队、连接/读写延迟、生成耗时及剩余任务有效期都可能影响结果。限流和服务繁忙也是官方列出的独立失败原因。[错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/)

另外确认了显示路径的风险：并发翻译允许后面的短句先完成。原焦点选取较新的已完成片段，晚到的长句中文可能只补在上方旧卡片，尤其“最近1条”时已看不到；普通列表提前只取最近N条，也可能把仍等待的长句排除。这属于显示遗漏，不能等同于请求没有翻译。

## 当前行为

- 历史上下文最多 **5条 / 2800字符**，任一上限超出就删除最早的整对原文/中文。预算含JSON结构，空历史记0。过大的最新句对也不会让更老的内容重新进入；下一条较短内容完成后可重新积累。
- 完整 `messages` 序列化后最多 **6000字符**。超过时先删除最早历史，再减少排序靠后的参考术语；当前待译句、否定/公式/变量和系统规则不截断。如果只剩当前原句和规则仍放不下，明确报告 `translation_prompt_too_large`，不发请求、不当作翻译成功，原文保留。
- 字符预算是Unicode字符/JSON长度，**不是Token估算**。实际计费Token仍读取接口usage；另记录真实UTF-8字节数。界面实时预览和整句后翻译两种模式都经过同一限制。
- 上下文删除只影响以后请求，不删除字幕历史、翻译稿或已完成译文。异步完成时，历史按原句顺序排序，不把后文当作前文上下文。
- 焦点和普通列表按原句顺序等待未完成的前句。后句可继续并发翻译并缓存，不能提前替掉前句。下方实时原文继续更新，标题可显示“后续N句已译”。普通列表等待时可额外显示一行最新原文预览，不受最近N条正文挤占。
- 等待后的译文补齐时，按可读字数保留 **1.5–8秒**，再展示下一句；恢复中每个排队完成片段也保留阅读时间。焦点保留原520ms OutCubic上推动画。只有发生等待/乱序恢复时增加该阅读时间，不对所有正常更新固定加延迟。
- 焦点恢复队列仍最多8条，从最多128条显示记录中分批补充，恢复时不合并跳过已排队译文。若已等待的记录超出显示历史边界，明确发布显示过期事件和原文回退，不无限卡住。隐藏悬窗或切换显示模式仍允许直接跳到当前内容，不追播隐藏期间的历史。
- 临时超时/限流仍会有限重试；新增 `translation_retry_pending` 区分重试与终止失败。重试期间继续等待前句并显示原文；最终失败会先保留原文/不可用提示，再继续后句。朗读队列也使用这个区分，避免一个超时头项永久卡住后续声音。

等待和阅读保留可能让中文显示落后于最新识别；这是避免后句抢位的明确取舍。显示队列不是永久保存，整节课需启用自动存稿。没有把终止失败改成无限重试，也没有增加默认并发或付费请求次数。

## 诊断与排查

在主窗口“诊断详情”查看或手动导出新文件；不自动保存课程内容或诊断。

| 事件 | 可判断的信息 |
|---|---|
| `translation_context_pruned` | 删除/保留条数、历史长度、限制，无正文 |
| `translation_submitted` | segment/revision/attempt、当前原文字符数、上下文条数/字符数、术语数、完整messages字符/UTF-8字节数、队列等待、有效超时秒数 |
| `translation_error` | 失败码、实际耗时、请求大小、是否已开始输出；超时阶段为connect/read/write/pool/request等 |
| `translation_completed` | 是否应用于当前版本、对应原句/attempt、译文字符数和请求耗时；不是显示完成 |
| `subtitle_presentation_waiting` | 当前等待/阅读的句子、后续已译句数、视图；区别于API未返回 |
| `subtitle_presentation_issue` | 显示历史过期等异常，无正文 |
| `translation_backlog_drop` / `translation_expired` | 任务因积压或过期未完成；主窗口现也明确提示 |

`request` 超时是整个请求期限，并不等同于连接失败。`read` 是等待响应数据，不自动意味着输入过长。任务剩余有效期不足12秒时有效期限会更短，日志保留该值。不记录请求正文、返回正文或密钥；现有可选字幕/稿件保存策略保持独立。

若日志显示某句 `translation_completed.applied=true`，随后 `subtitle_presentation_waiting`，说明已译、正在等前句/阅读顺序。若是超时、输出长度截断、过期或队列丢弃，则属于未完成中文，保留原文，不将部分流当作完整译文。真正的模型语义漏译仍需结合原文和译文人工核查，本次未进行真实服务质量评估。

## 修改文件

- `app/translation/context.py`、`prompt.py`、`config.py`、`config/translation.toml`：严格最近历史、完整输入预算、纯长度诊断。
- `app/subtitles/coordinator.py`、`models.py`：上下文同时按字符裁剪，原句顺序，明确重试状态。
- `app/translation/client.py`、`worker.py`、`app/diagnostics/runtime.py`：保留超时阶段、请求大小/输出状态/译文字符数，不额外调用接口。
- `app/ui/captions.py`、`focus.py`、`overlay.py`、`window.py`、`speech.py`：等待前句、阅读停留、有界恢复、实时原文和朗读失败释放。
- `tests/unit/test_translation_context.py`、`test_translation_display_order.py`，更新既有原文保留测试以符合新的顺序要求。

## 测试与证据

环境沿用本机Windows11 x64、Python3.12.10、PySide6 6.8.3、HTTPX0.28.1及现有固定依赖。未升级运行库。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 完整回归 | **661通过，1项现场音频测试未启用，49.43秒** | [完整输出](evidence/context-order-release-pytest-20261103.txt) |
| 最后等待提示的专项回归 | 75通过，4.54秒 | [输出](evidence/context-order-final-targeted-pytest-20261103.txt) |
| 500句算法重放 | 测试文字；500次最终记录回调完整保留，上下文/完整请求没有随课程线性增长；默认参数下观察到历史最高1176字符、完整请求最高1986字符 | [算法重放](evidence/context-policy-replay-20261103.json) |
| 长历史/长术语压力 | 300次完成、较小历史预算、完整输入超限、JSON边界、最新句过大、禁用上下文、当前句完整保护全部通过 | `test_translation_context.py` |
| 长句慢回/短句先回 | 两个并发请求经真实DeepSeekClient、HTTPX MockTransport、SSE解码、Worker、Coordinator到两个真实Qt视图，逆序响应后仍先完整显示长句，再显示短句 | `test_translation_display_order.py` |
| 有界乱序恢复 | 21条按序进入焦点，不因8条批次而合并跳过；重试、终止失败、历史过期和真实Qt计时释放通过 | 同上 |
| 实际Qt布局 | 两种视图均保留长句、显示实时原文、随后显示短句；图片是标注的测试文字，非真实识别/翻译 | [结果](evidence/context-order-layout-20261103/results.json)、[焦点长句](evidence/context-order-layout-20261103/focus-long-visible.png)、[列表长句](evidence/context-order-layout-20261103/list-long-visible.png) |
| EXE入口 | 退出码0，窗口创建，未开始捕获 | [启动结果](evidence/context-order-exe-startup-20261103.json) |

MockTransport不会访问真实DeepSeek；测试使用明确的测试文本和响应。未声称修复服务端延迟、真实翻译准确率或所有长句语义遗漏。GPU联合推理、真实故障服务测试、30/60分钟稳定性仍待执行。

## 验收

重启ELT并用原有课程开始字幕。先保持正常原始语言/翻译模式；观察长句等待时原文仍更新、后一句先完成时标题提示、长句译文显示并停留后再推进。需要回看时使用“最近字幕”或自动存稿。

开发者可离线复现，不需要密钥：

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_translation_context.py tests/unit/test_translation_display_order.py -q -p no:cacheprovider --capture=sys --basetemp docs/evidence/my-new-context-order-test
```

上下文上限集中在 `config/translation.toml`。原有5条/2800字符保留，新增 `max_prompt_chars=6000`；修改配置后下次启动翻译会话读取。只调整上下文不需要重载或下载模型。
