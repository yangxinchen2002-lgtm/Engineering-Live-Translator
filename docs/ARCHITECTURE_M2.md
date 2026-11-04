# M2 设计与接口

2026-11-03 多API扩展：来源/模型绑定到会话，四个独立Windows凭据target；旧DeepSeek默认与target兼容。OpenAI Responses、Claude Messages、Gemini原生SSE适配为统一delta/usage/done，复用上下文/版本/队列/失败回退与显示顺序。只调用选中来源，无自动跨平台兜底；原文模式不读密钥。费用卡只用于匹配的DeepSeek模型，新来源读实际Token而金额保持未知。当前接口、官方依据与真实服务未测边界见 [MULTI_PROVIDER_TRANSLATION.md](MULTI_PROVIDER_TRANSLATION.md)，下文保留历史M2设计。

2026-11-03 加固：内存与请求共用严格最近句对裁剪，5条/2800字符之外删除最早内容；完整messages另限6000字符，不截断当前句与翻译规则。上下文按原句顺序；新 `translation_retry_pending` 区分重试与终止失败，超时诊断保留阶段/耗时/请求大小。并发不变，UI独立按原句等待，避免短句先回挤掉长句。接口、证据及真实服务未测边界见 [TRANSLATION_CONTEXT_AND_ORDER.md](TRANSLATION_CONTEXT_AND_ORDER.md)。

2026-11-03 增加日语：识别、翻译、字幕和存稿共享 `app/languages.py` 语言列表，`ja` 沿用同一 Preview/Final 与 revision/attempt 生命周期。日语按模型片段连续拼接，字符上限仍有效；不按空格词数截断。接口调整与验证边界见 [JAPANESE_SUPPORT.md](JAPANESE_SUPPORT.md)。下文原 M2 历史范围及验收不因此改为完成。

用户授权直接进入 M2。ASR 课程提示在 config/asr.toml 中显式关闭；翻译术语表独立于 ASR 热词。M3 GUI 不在本次范围。

流水线：M1 的真实采样/词稳定更新 → 有界 SubtitleCoordinator → 有界翻译调度 → DeepSeek HTTPS SSE → revision/attempt 校验 → CLI Preview/Final。网络任务不在音频捕获线程或 CUDA worker 中运行。

核心记录包含 session_id、segment_id、revision、source_language、source_text、translated_text、start_sample、end_sample、state。candidate_text 是单独的未确认原文尾部，不能作为翻译请求输入。canonical source_text 变化或封口会提升 revision；候选尾部有独立更新版本。只有封口后的完整请求正常完成且 revision/attempt 仍匹配才锁定 Final。ASR stable 本身不产生 Final。

字幕按已确认词及句末标点/停顿分段，缩写有排除规则，过长片段在词边界显式封口并记录原因。预览只翻译足够长度的已确认前缀，网络流式结果可修订；迟到、跨会话、旧 revision、旧 attempt、重复完成不得覆盖当前或已锁定字幕。

用户随后授权新增整句翻译模式。`translation.mode=preview|sentence` 在 SubtitleCoordinator 的 `_offer` 处决定提交时机：sentence 只允许 source_closed 的请求进入 worker；所有原文/候选字幕事件仍照常发布，开放片段标为 waiting_sentence。句末/ASR endpoint/输入完成、语言变化和原有长度上限仍可封口，close_reason 保留，不能把安全分段等同于语法完整句。重试、队列、流式输出及 revision/attempt 校验复用原实现，不改变音频或 ASR 调度。当前实现/验证见 [SENTENCE_TRANSLATION.md](SENTENCE_TRANSLATION.md)。

翻译服务最多 2 个请求、16 个待处理片段；同片段只保留最新待处理版本，Final 优先。任务有时效、12 秒请求总超时、最多 2 次重试。过期/积压/故障均明确记录。认证/余额/配置错误停止新请求，原文继续。关闭时有界排空后取消请求并关闭 HTTP 客户端。日志与字幕历史有独立显式保存开关。

## 可选的整次会话 TXT

`run_bilingual(..., transcript_directory=None)` 默认不写翻译稿。显式启用后，`SubtitleCoordinator.on_source_closed` 保存已封口原文，`on_final` 同时交给原有 HistoryWriter 与新增 TranscriptWriter；停止/异常时还保存当前已确认前缀。candidate_text 不写作已确认原文，旧 revision 或前缀中文不得写为完整句译文。

TranscriptWriter 只做本地文件持久化，不调用模型或网络。默认 64 项的有界队列复用 history_queue_capacity（1–256），offer 不等待磁盘；后台通过 asyncio.to_thread 串行执行 SQLite 提交和 TXT 写入，不在音频线程或 GUI 线程操作文件。单会话本地 SQLite 按 segment_id/revision 去重，封口原文与 Final 分别入库；已完成双语同时追加到进行中 TXT 并 flush/fsync，原文可从临时库保留。完整会话在磁盘上，不随 UI 128 条显示历史淘汰。

关闭时排空保存队列，以 start_sample/id 排序生成最终 TXT，将未译完的确认原文标明。文件名取本地会话开始日、固定/实际识别语言及音源就绪至结束的单调时钟整分钟（向下取整）；停止后的网络排空不计。以排他创建预留不存在的文件名，同名递增序号，再原子替换自己的空预留文件，避免覆盖已有稿件。成功后清理本次进行中文件与临时库。队列溢出、文件系统错误和保存未完成分别报告，不把部分稿标成完整；写入失败不停止 ASR/翻译。

正常退出执行最终整理；强杀/断电/20 秒 GUI 退出保护触发时可能留下进行中 TXT、SQLite 或 .ready 文件，未实现自动恢复或断电持久性保证。该开关与 JSONL 历史、诊断日志独立，所有临时正文也只保存在用户指定目录。详情见 [TRANSCRIPT_SAVING.md](TRANSCRIPT_SAVING.md)。

当前 API 按官方文档固定 deepseek-flash、thinking.type=disabled、stream=true。只发送当前文本、最近最多 5 条已确认上下文和相关术语；无原始音频、文件或全课历史上传。密钥读取进程环境或 Windows 用户凭据 ELT/DeepSeekAPIKey，不进 TOML、命令行参数或日志。

官方依据（2026-10-30 检查）：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。SSE 的 usage 可能与最后的 finish_reason 同包；需要等正常结束和 DONE 才确认请求完整。计费统计只根据实际返回 usage，取消/中断未返回 usage 的请求标为未知，不声称零费用。

自动测试使用仅存在于 tests 的可复现替身，真实客户端不提供假成功或 Mock 命令行开关。真实 DeepSeek 质量验收取决于有效凭据和人工语义核查；缺失项必须标为未执行。

## 实际模块与生命周期

| 模块 | 输入/输出 | 错误与释放 |
|---|---|---|
| translation.config / credentials | TOML 与环境/指定 Windows 用户凭据 → 非秘密配置和私有 Credential | 拒绝非官方 HTTPS 地址、密钥配置字段、无界参数；密钥值不进入 repr、日志或 CLI 参数 |
| translation.glossary / prompt | 当前文字 + 最近已确认片段 → 有界纯文字请求 | 词表最多 128 KiB/512 条，相关最多 12 条/2400 字符；保留同词不同领域解释，不机械替换 |
| subtitles.coordinator | asr_update 的确认词/候选词/endpoint → 不可变 Preview/Final 快照 | 原文版本、候选版本、请求 attempt 分开校验；句末缩写排除；40 词/800 字符到界显式封口；保留最多 128 条显示记录 |
| translation.worker | 最新待译版本 → 流式部分/完成/失败 | 队列 16、并发 2、任务 24s 时效、请求 12s 总超时、最多 2 次重试；过期、丢弃、取消和未知用量均记录 |
| translation.client | 纯文字 Chat Completions → SSE delta/usage/done | TLS 验证、禁止重定向；严格 UTF-8/帧边界/长度、正常 finish 与 DONE；关闭流和 HTTP 客户端；错误体不写日志 |
| subtitles.history | 锁定 Final → 可选本地 JSONL | 默认关闭，独立队列 64，独立异步写入，拒绝覆盖；写盘错误不撤销翻译或阻塞捕获线程，历史不完整明确报告 |
| translation.runtime / cli | 用户命令 + 原生/文件源 → 原文与双阶段字幕事件 | 强制 ASR 术语提示关闭；源流先结束清理，再有界排空翻译；取消回收网络任务、客户端、文件和 M1 进程 |

M1 新增 asr_update，包含真实确认/候选词的采样位置和 QPC 时钟，endpoint 即使没有新词也输出。M1 原始 transcript 增量保持不变，不把候选拼成已确认原文。asr_submitted 记录实际入队，用于实机测试在任务在途时触发关闭。

翻译请求只包含当前 canonical source_text；候选尾部更新不使相同前缀反复请求。当前文字变化使旧响应失效。已有前缀译文可保留，但连同自身 source/revision 标记；新流的首段会替换它，不把旧流追加到新流。封口再提升版本并请求完整译文，不将 ASR stable 直接当 Final。源码中的 candidate/stable/committed 仍表示 M1 内部状态。

`--translation-mode` 仅覆盖本次配置，不改写 TOML；CLI 默认仍沿用配置中的 preview。GUI 默认 sentence 并持久保存选择，显式传给后台；启动中文翻译仍要求用户主动启用。`translation_status`、`translation_submitted` 含 mode，最终 bilingual_summary 含 translation_mode，可审查实际运行策略；缺少用量不推断免费。

已确认上下文按原文先后存储，过滤 session、segment_id 和音频范围，后完成的较早片段不能引用未来字幕。上下文最多 5 条/2800 字符；history 文件不作为全课云上下文读取。记录淘汰、翻译队列溢出等都会使未完成计数保留，不能通过移走记录伪装完整。

## 测量语义

使用 M1 统一 QPC。translation_submitted 分开记录队列等待、请求准备和任务总年龄；每次重试的退避独立记录。translation_first_output 是网络首次有效文字，带当前版本是否仍有效的标记；subtitle_translation_first_available 只统计成功写入当前字幕状态的首次文字。后者不是 GUI 渲染完成，M3 尚未实施。translation_completed 另记请求耗时及音频片段结束后的可用时间，快速文件/手动文字不给音频实时延迟结论。

Token 按 API 实际 usage 汇总，支持最后 finish 包和独立 usage 包；失败流中已拿到用量也保留，拿不到的计入 attempts_without_usage。没有密钥时请求数为零，翻译不可用，整体返回 3。源流失败时 asr_complete 和 translation_complete 均为 false；正常无语音也不假装已经产生译文。

2026-10-31 追加 UsageLedger：每个真正提交的 attempt 在流处理的 finally 中结算一次，包括重试、取消、过时响应和内部异常。usage_fields 校验非负整型及输入/输出/总数、缓存关系；支持 prompt_tokens_details.cached_tokens，必要的互补字段只作算术推导，不以缺失值填零。同一流多个 usage 是累计快照，保留最后一份，只结算一次。累计数量为常量空间标量，不受 128 条字幕或 512 个延迟样本限制。

每次结算发布累计 translation_usage（单调 usage_revision），最终 bilingual_summary 包含同一快照。GUI 接收时替换，不再叠加 translation_completed.usage；旧/重复 revision 被忽略。后台消失后仍未结算的已提交请求由 GUI 标为未知，保留此前已知用量。网络调用与余额查询路径没有增加。

价格使用随包分发的 deepseek_pricing.json，包含核对日期、官方来源和美元/百万 Token 的峰谷价格。Decimal 计算缓存命中输入、未命中输入、输出三部分；费用是快照估算，非账单。UTC 请求起止间经过工作日峰时段时，因为中国节假日未核实而返回谷价—峰价区间；缓存拆分缺失时同样扩大范围，不冒充缓存全未命中。价格表不可用或计价字段不足时保留 Token、金额未知；无法计价的请求不计入已知部分金额，完整性明确为 false。cost_usd 仅在已结算请求均可估算且上下界相等时有字符串值，含义仍为估算；其余情况读取 cost_estimate 上下界和完整性。详见 USAGE_AND_COST.md。
