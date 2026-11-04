# 整句后 DeepSeek 翻译模式 — 2026-10-30

**阶段：M3 追加功能。** 用户明确要求“等一句话完整说完以后再调用 DeepSeek，原文还是实时显示”。当前交付该模式及可切回的预览模式，未实施本地翻译模型，也未启动用户暂缓的长测。

## 本次完成与接口

- 左侧开始按钮上方新增“中文翻译方式”，默认“整句后翻译（节省用量）”，另有“实时预览翻译”。仍需用户主动启用中文；原文模式不访问翻译凭据或创建 HTTP 客户端。
- sentence 模式不发送句中稳定前缀翻译，候选和已确认原文照常更新；中文区域显示“等待整句结束后翻译…”。source_closed 后才提交，译文仍可流式显示。
- preview 保留原来的稳定短语预览及片段结束后的确认翻译。运行中选择禁用，避免改变在途请求；先停止再切换。选择会持久保存，旧偏好文件缺少该字段仍可加载。
- CLI `translate-live`、`translate-file`、`translate-text` 支持 `--translation-mode sentence|preview`。未指定沿用 TOML `mode`，当前 CLI 默认保持 preview；GUI 显式传递所选方式。手动文字本来就是完整输入，任一模式都一次提交。
- 模式值只允许上述两项，传入错误在启动前拒绝；诊断的 translation_status/translation_submitted 含 mode，summary 含 translation_mode。沿用队列、超时、有限重试、版本检查和关闭清理。

## 句子结束的实际边界

翻译依据确认词里的句末标点，或 ASR 停顿/端点、正常输入结束封口。候选标点不触发，常见缩写继续排除。语音停顿并不保证句子语法完整，ASR 标点也可能有误；不宣称可以完美判断德语从句结束。

原有安全边界保持：默认 40 词/800 字符、语言变化等也会结束一个片段，原因保存在 close_reason。这样长时间没有句末时不会无限积压或静默丢失文字。正常每个封口片段一次提交，失败的有限重试可能增加实际请求；没有固定节费比例承诺。

## 主要修改文件

`app/translation/config.py`、`config/translation.toml`、`app/subtitles/coordinator.py`、`app/translation/worker.py`、`cli.py`、`app/main.py`；`app/ui/window.py`、`controller.py`、`preferences.py`、`overlay.py`；对应 coordinator/config/GUI/CLI 单元测试及 `tests/integration/test_m2_pipeline.py`。README、架构、计划、决策和验收文档同步更新。

## 测试结果与证据

环境沿用 Windows 11 10.0.26300、Python 3.12.10、PySide6 6.8.3、HTTPX 0.28.1、pytest 8.4.2；未修改 CUDA/ASR 模型或 API 参数，未新增依赖。

| 检查 | 实际结果 | 证据/边界 |
|---|---|---|
| 相关 coordinator/config/GUI/CLI/HTTP 集成回归 | **114 通过，2.30 秒** | [focused final](evidence/sentence-mode-focused-final-tests.txt) |
| 全量回归 | **320 通过、2 跳过，14.76 秒** | [full tests](evidence/sentence-mode-full-tests.txt) |
| 跳过项 | M0 硬件 smoke 未显式启用；全局快捷键被其他应用占用 | [skip details](evidence/sentence-mode-skip-details.txt)；不为测试关闭用户应用或抢占快捷键 |
| 原文持续更新、候选修订 | 通过 | sentence 句中不提交，subtitle 仍更新 source_text/candidate_text；等待提示在主窗口和悬窗一致 |
| 句末/无标点停顿/EOF、重复 EOF、候选标点/缩写 | 通过 | 仅封口时提交；重复更新不新增请求，Final 锁定保持 |
| 极长无标点内容 | 通过 | 有界分段，拼合提交内容与输入一致，保留 bounded_phrase 原因，不静默丢字 |
| HTTP SSE 请求数对照 | preview **3 次**；sentence **1 次** | 同一测试句分三批输入，使用真实 coordinator/worker/prompt/HTTP/SSE 代码，只有 ASR 输入和 HTTP 服务是测试替身 |
| GUI 模式→控制器→CLI、偏好兼容/恢复、运行中禁用 | 通过 | GUI/CLI 两种模式和三种翻译命令，原文模式云端边界仍通过 |
| 实际界面组件排版 | 已检查 | [布局预览](evidence/sentence-mode-ui-preview.png)，离屏组件渲染，不是实时翻译截图 |
| Python 编译检查 | 通过 | `compileall -q app tests` |
| 真实 DeepSeek 费用/延迟、VLC/浏览器音频联动 | 本轮未执行 | 未读取用户密钥发请求；不能以 Mock 数据宣称实际省费或质量提升 |

初版相关测试为 113 通过、1 失败，请求数对照中的 preview 等待超时；证据 [首次 focused](evidence/sentence-mode-focused-tests.txt)。定位为测试把 1ms 节流门槛与 Windows asyncio/QPC 时间分辨率混用，现将模式请求数测试与节流等待分开，生产 1.5s 预览间隔未改。最终完整回归通过，不隐藏首次失败，也不将测试的 3→1 换算成真实账单节省率。

## 性能数据与已知限制

本轮只有上述自动测试耗时和受控请求计数，没有真实 Token 用量、金额、翻译延迟或专业准确率数据。中文会比预览模式更晚出现；若停顿判断较早、长句触发上限，仍可能按片段翻译。M3 原有显示兼容、30/60 分钟及工科人工质量验收仍未完成。

## 用户验收步骤

1. 完全退出旧 ELT，双击 `启动ELT.cmd`。确认开始按钮上方“中文翻译方式”为“整句后翻译（节省用量）”。
2. 选择 VLC/Chrome/Edge、课程语言和进程，主动勾选中文，点击开始；音频就绪后继续播放。
3. 观察原文继续更新，中文先显示等待整句。句末或停顿确认后出现译文，核对它仍对应自己的原文。
4. 停止，切换“实时预览翻译”，再开始，确认原有预览行为可用；模式不可在运行中切换。
5. 如需核对实际请求，在“诊断详情”检查 translation_submitted 的 mode/phase，或显式导出到新文件；句中 candidate 更新不应产生 sentence 模式的 preview 请求。异常重试需单独计数。

CLI 示例（PID 换成实际值）：

```powershell
.\.venv\Scripts\python.exe -m app.main translate-live --source chrome --pid 1234 --language de --translation-mode sentence
.\.venv\Scripts\python.exe -m app.main translate-file --input 'D:\MyTests\course.mp3' --language en --translation-mode sentence
```

## 下一步

先确认句末等待是否符合课程阅读习惯，再根据真实 usage 和请求记录比较两种模式。该比较及长测须单独留证；本轮到新模式交付停止，不自动下载或部署本地翻译模型。
