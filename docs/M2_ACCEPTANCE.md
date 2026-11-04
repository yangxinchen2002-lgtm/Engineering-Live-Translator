# M2 实现及无密钥验收报告 — 2026-10-30

**阶段：M2。实现和本轮无密钥测试已交付，真实 DeepSeek 与人工质量验收待执行。** 用户明确选择“本轮先做无密钥测试”。没有请求真实翻译、没有把 Mock 译文接到生产流程，也没有进入 M3 或宣布 MVP 完成。

## 本次完成

- 用户要求关闭的 ASR 课程术语提示已在 config/asr.toml 中显式关闭；M2 入口再次强制关闭，实机 course_terms_jobs=0。
- 实现真实 DeepSeek HTTPS Chat Completions/SSE 客户端，固定 deepseek-flash、thinking.type=disabled、stream=true、include_usage=true。没有其他模型或 CPU/云 ASR 回退。
- 字幕原文确认前缀与候选尾部分离，Preview 流式更新，封口后以更完整文本再翻译；只有正常完成且 session/revision/attempt 匹配才锁定 Final。
- 旧版本、跨会话、旧重试、重复完成不能覆盖新内容或锁定字幕。原文前缀译文保留自身对应文字与版本，不冒充新全句译文。
- 独立、可维护的 48 条翻译术语，覆盖控制、机器人学、数学、机器学习，另含信号处理。相关项才发送，同词多义保留领域与注释，不机械替换。
- 有界翻译队列/并发/任务时效/超时/重试，认证及余额错误停止新请求，原文继续；过载/过期/丢弃/取消明确报告。
- 密钥读取进程环境或指定 Windows 用户凭据，隐藏输入设置入口；不接受密钥 CLI 参数，不在配置、repr、错误体日志中输出密钥。
- 字幕历史与诊断日志独立开关，默认不保存；Final 历史只写一次，失败不假装保存成功。没有录制或上传原始音频。
- 100 句评估草案和人工复核工具，默认只准备评估，不生成伪译文。

## 修改文件

| 文件 | 用途 |
|---|---|
| app/translation/config.py、credentials.py | 有界参数、官方 HTTPS 地址、安全凭据读取/管理 |
| app/translation/client.py | 真实 TLS/SSE、严格 UTF-8、结束校验、错误分类与 usage |
| app/translation/worker.py | 有界调度、过期/重试/取消、流式状态与诊断 |
| app/translation/glossary.py、prompt.py | 相关术语与有限上下文、专业翻译约束 |
| app/subtitles/models.py、coordinator.py、history.py | 版本状态、原文分段、不可变 Final、独立历史 |
| app/translation/runtime.py、cli.py、app/main.py | M2 生命周期、translate-live/file/text、凭据命令 |
| app/asr/pipeline.py | 实际确认/候选更新与空 endpoint；实际任务提交诊断；保留 M1 transcript |
| config/translation.toml、terminology/engineering.json | 默认参数和翻译词库 |
| tests/fixtures/m2_engineering_sentences.json | 100 句工科评估草案 |
| tools/evaluate_translation.py、live_m2_checks.py | 人工评估准备/显式真实评估及无密钥实机测试 |
| tests/unit/test_*m2*、test_subtitle_coordinator.py、test_translation_worker.py、test_deepseek_client.py、tests/integration/test_m2_pipeline.py | 自动测试 |
| requirements-m2-lock.txt、pyproject.toml、README 与阶段文档 | 已验证依赖、构建运行与验收维护 |

## 环境

Windows 11 Pro x64 Build 26300；Intel Core i7-13850HX；NVIDIA RTX 3500 Ada Laptop GPU，12282 MiB；驱动沿用 M1 的 597.16。Python 3.12.10。

本地 ASR 沿用固定 large-v3-turbo、Faster-Whisper 1.2.1、CTranslate2 4.6.0、CUDA Runtime 12.4.127/cuBLAS 12.4.5.8/cuDNN 9.1.0.70，cuda/float16；未更改模型、beam1、VAD 或窗口参数来宣称准确率提升。

HTTPX 0.28.1、httpcore 1.0.9、AnyIO 4.15.1、h11 0.16.0。完整 40 项实际依赖固定在 requirements-m2-lock.txt。可编辑安装、pip check、Python 编译检查通过。普通受限环境的 pip 临时目录访问曾失败，改用正常用户执行环境安装成功；不是生产代码假成功。用户终端不要求管理员身份。

当前官方文档支持上述模型及请求参数，见 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)、[错误代码](https://api-docs.deepseek.com/quick_start/error_codes/)。没有密钥，因此未核验真实服务器当前返回的模型版本、TLS/代理兼容性或账户额度。

## 自动测试结果

最终交付回归：**191 passed, 1 skipped，12.01s**。证据：`docs/evidence/m2-pytest-delivery.txt`，对应 stderr 为空。跳过项仍是需要 ELT_RUN_HARDWARE 显式启用的 M0 五秒 smoke；下列独立真实 VLC 测试已另行执行，不把 pytest 跳过项写为通过。原生 C++ 未修改，既有 CTest 结果保留在 M0 报告。

包含原 M0/M1 逻辑及以下 M2 覆盖：

- Unicode/数学符号跨 UTF-8 分片、SSE 消息边界/注释/多行、真正提前流式输出、同包及独立 usage。
- 截断、缺 DONE、空译文、长度超限、意外思考/工具输出、未知结束原因安全处理。
- 401/402/429/503、总请求超时、有限重试、重试后旧部分/旧 attempt、取消后释放流和客户端。
- 真实异步乱序、旧 Preview 晚于新 Final、重复完成、跨会话、不可变 Final、确认原文和候选尾部独立。
- 不重复请求相同版本、队列有界/显式丢弃、时效、原文持续更新、未来字幕不得进入较早请求的上下文。
- 词库字段/大小/领域/匹配、上下文预算、禁止密钥配置字段及 CLI 泄露、凭据编码错误不打印秘密。
- 历史有界/拒绝覆盖/写盘失败、启动输出失败仍释放资源、源流失败时不报告翻译完成。
- 100 句语种/领域/覆盖完整性、准备评估不调用 API、不填入参考假译文。

API 响应均来自 tests 中的替身或 HTTPX MockTransport，**这些测试不能证明真实 DeepSeek 翻译正确或延迟达标**。生产 CLI 没有 Mock 开关。

## 实机验证和性能数据

证据：`docs/evidence/m2-live-no-key-v2/results.json` 和同目录原始 JSONL。工具以自建 VLC 播放此前下载的 MIT 英语讲座，按 PID/创建身份捕获。正式证据使用 v2；v1 也保留，随后补齐了源流异常的明确事件，并将空输出的“翻译完成”状态收紧为未完成。

### 无密钥、暂停恢复

- 接收 **59.98s / 959,680 样本**的真实标准化音频；55 个 GPU 推理任务，ASR complete=true。
- 第约 28s 暂停，31s 恢复；恢复后仍有 57 条字幕状态事件。
- 共 100 条字幕更新；中文非空事件 **0**，Final 事件 **0**，翻译请求 **0**，明确 translation_available=false、translation_complete=false。
- 返回 **3**，表示原文工作完成但翻译未完成；不是 API 成功。显式启用的历史文件为空，history_written=0。
- ASR 课程提示使用次数 **0**。无报告的音频缺口、接收/必须队列溢出或预览跳过。
- 模型词结束口径：原文首次预览 P50 **0.369s** / P95 **0.560s**；LA 稳定提交 P50 **1.256s** / P95 **1.795s**。推理 P50 **0.175s** / P95 **0.207s**。
- 总会话 **70.328s**，包含约 10s 模型启动/关闭；GPU 总设备观测峰值 **3969 MiB**，包含其他应用，不是模型独占显存。

这些数据只描述本地原文与降级路径，**中文首字/首次可读/最终显示延迟均未测量**；不把本地原文延迟当成中文延迟。

### 任务在途时退出

- 目标退出：实际 ASR 任务提交后 **25.69ms** 触发关闭 VLC；0.669s 内结束，返回 1。明确源流 target_exited_select_again_for_new_PID，asr_complete=false、translation_complete=false。
- 强制结束自有主进程：任务提交后 **23.83ms** 执行；GPU worker 与 native helper 均在 **0.332s** 内观察到退出，未只终止 venv 启动器。描述的是已提交在途任务，没有声称测到了 GPU 内核执行的精确瞬间。
- 最终审计：本次列出的 GPU worker/子进程均已不存在，原生捕获 helper 残留 **0**。见 `m2-delivery-audit.json`、`m2-cleanup-final.json`。

## 100 句评估与未执行项目

评估集为本项目原创草案：德语 50、英语 50；控制、机器人学、数学、机器学习各 25。覆盖术语、符号、变量、否定、条件、因果、德语从句/长句及德英混用。参考译文**尚未由人工专业审校**，不是 gold 质量认证。

`docs/evidence/m2-review-final/summary.json` 明确：case_count=100、completed=0、not_run=100、real_api_requested=false、real_api_executed=false、human_quality_status=not_reviewed。review.json 中实际译文均为 null，人工审核均为 pending。没有将参考译文复制成 API 返回。

未执行：真实 DeepSeek 翻译、真实服务断网/限流/余额故障实机联动、100 句人工语义/严重工程错误核查、真实 Token/费用与中文延迟、带翻译的长期运行。故障逻辑已由 Mock 覆盖，但不能等同于这些实测通过。60 分钟稳定性与最终 GUI 性能目标也未验收。

## 已知限制

- Final 表示当前版本锁定，不是语义正确认证。ASR 的已有误识别仍会传给翻译，德语长句、否定、公式和强制有界分段需要实际质量评审。
- 预览在不断新增的稳定前缀上请求翻译，旧响应可能被丢弃；真实首个有效中文是否足够快尚未测量。
- 长片段达到 40 词/800 字符会在词边界显式封口，原因 bounded_phrase 可诊断；它不保证恰为完整德语语法句。
- 工程评估的数字/否定自动筛查只是待人工检查标记，不是正确率。当前不报告翻译准确率。
- history 默认关闭，仅保存已锁定 Final；正常本地文件的写入故障已测试，阻塞网络共享写入未验收。
- CLI 输出 JSONL，尚无 M3 双语悬浮窗。没有在本次做 ASR 模型/beam 调优或 GUI 开发。

## 用户验收步骤

1. 按 README 使用锁定环境和已构建 native helper；运行 deepseek-key status 可确认无密钥，值不会显示。
2. 暂停 VLC，运行 list 选择 PID，然后 translate-live --pid 实际PID --language de/en --seconds 60；模型 ready 后恢复。
3. 本轮无密钥预期只出现原文/candidate、翻译不可用，最终返回 3；不能出现伪造中文或 Final。
4. 用 tools/live_m2_checks.py --output 新目录复验暂停恢复、任务在途退出和无残留；工具会播放自己的讲座实例。
5. pytest 命令见 README，安装 translation extra 后可运行全部 M2 Mock 测试。
6. tools/evaluate_translation.py --output 新目录只准备复核表；当前不加 --run。
7. 后续用户选择配置有效密钥时，用本机隐藏输入 deepseek-key set，再用 translate-text 做真实小样本；之后显式 --run 执行 100 句，保留实际输出并人工核查术语、数值、否定、因果和严重错误。

## 下一阶段建议

先完成真实 DeepSeek 与人工质量验收，再决定进入 M3。此次停止在 M2，实现和无密钥测试已交付；没有把未执行项标为通过。
