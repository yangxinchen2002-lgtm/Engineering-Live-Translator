# DeepSeek Token 与预计费用 — 2026-10-31

**阶段：M3 用户追加信息显示。** 已实现并自动测试；本轮未发送真实 DeepSeek 请求，不等同于真实扣费核对或完整 M3 验收。

## 使用方法和本次完成

1. 正常停止并退出旧 ELT，再双击 `启动ELT.cmd`。
2. 主动启用中文翻译并开始课程。主窗口底部显示本次累计 Token / 预计美元费用；每次请求结束收到用量后更新，进行中的请求另作提示。
3. 点“性能统计”，查看输入、输出、总 Token、缓存命中/未命中、未知用量和预计金额。输入包含系统提示、相关术语及有限上下文。
4. 停止后本次数据保留；开始新会话重新统计。需保存诊断时沿用原来的手动导出，里面包含用量及估算依据；不会自动保存账户信息。

实时预览和整句两种模式都复用同一统计。重试和迟到的旧译文也可能已经消费，按实际收到的用量计入，不以是否显示译文来过滤。相同流的重复 usage 不重复计费。累计总量独立于 128 条字幕和 512 个延迟样本，不随界面历史淘汰。

缺失用量标为未知；字段不全时已报告字段保留、整体标为不完整。金额只累计可以估算的部分。强制退出仍有未结算请求时也提示不完整，不显示假完整或把它们算成免费。读取 usage 和计算费用没有新增翻译或余额接口调用。

## 官方依据与金额含义

核对日期：**2026-10-31**。[Chat Completions 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)规定流式最后一个结束包携带用量。本项目保持 `stream_options.include_usage=true`，兼容最后 finish 包或独立 usage 包，验证输入、输出、总数和缓存的一致性。

[官方价格表](https://api-docs.deepseek.com/quick_start/pricing/)的 deepseek-flash 价格快照如下，单位为 **USD / 百万 Token**：

| 类型 | 谷价 | 峰价 |
|---|---:|---:|
| 输入缓存命中 | 0.003 | 0.006 |
| 输入缓存未命中 | 0.15 | 0.30 |
| 输出 | 0.60 | 1.20 |

公式为 `(命中输入 × 命中单价 + 未命中输入 × 未命中单价 + 输出 × 输出单价) / 1,000,000`，使用 Decimal，不以总 Token 乘一个统一单价。

官方峰时段为周一至周五 UTC 01:00–04:00、06:00–10:00，排除中国公共假日；其他时间为谷价。程序没有未经验证的假日表：请求起止处于确定的谷时段则按谷价；经过工作日峰窗口或起止时钟异常时给谷价—峰价范围。缺缓存拆分时，按全部缓存命中到全部未命中的可能范围计算，不编造命中数。

这不是官方逐请求账单。显示美元，不自动换算人民币/欧元；价格固定于随包快照 `app/translation/deepseek_pricing.json`，不后台自动更新。快照超过 30 天或用于较早日期会提示核对。**实际扣费以平台账单为准**；没有使用余额差额归因本次会话。

价格表失效不阻断识别/翻译，仍统计 Token，金额未知。费用显示 9 位小数，极小非零值也不会显示成零。没有足够计价信息时显示“—”，不会填入示例消费。

## 接口与生命周期

| 组件 | 输入、输出及生命周期 |
|---|---|
| translation.usage.read_usage | 官方 usage → 校验后的计数；缓存别名及可推导总数归一化，不以缺失字段填零 |
| PriceCard | 有大小/数值限制的本地 JSON → 已核对的 Decimal 价格；读取失败禁用估算 |
| UsageLedger | 每次 attempt 的最后 usage 与 UTC 起止 → 累计数量/区间/完整性；常量空间，每会话一个实例 |
| TranslationWorker | 每个实际提交请求在 finally 结算，包括失败/取消；累计 translation_usage，结束汇总同一快照 |
| RuntimeMetrics | 按 usage_revision 替换快照，拒绝重复/旧版本；已提交未结算在进程退出时转未知；不再从成功事件重复累加 |
| ui.usage / MainWindow / PerformanceDialog | 同一快照 → 纯文本摘要/明细；无网络调用，每次新会话重建统计 |

生产流程无模拟用量开关，真实 API 请求保持 HTTPS、原有密钥读取与文本输入边界。测试的合成用量和 HTTP 替身仅在 tests 中。

## 主要文件

新增 `app/translation/usage.py`、`deepseek_pricing.json`、`app/ui/usage.py`；修改 `translation/client.py`、`worker.py`、`diagnostics/runtime.py`、`ui/controller.py`、`window.py`、`appearance.py`、`theme.py`、`pyproject.toml`。新增用量/费用、HTTP 事件与 GUI 测试，扩充既有 worker、统计及新会话重置回归。原生捕获、ASR 和字幕版本算法未改。

## 测试结果与边界

环境沿用 Windows 11 x64 10.0.26300、Python 3.12.10、PySide6 6.8.3、pytest 8.4.2，未升级依赖。

| 检查 | 实际结果 / 证据 |
|---|---|
| 用量与价格专项 | **41 通过，0.23 秒**；[usage-focused-tests.txt](evidence/usage-focused-tests.txt)，与全量有重叠，不累计相加 |
| 最终完整回归 | **412 通过、1 跳过，25.93 秒**；[usage-full-tests.txt](evidence/usage-full-tests.txt) |
| 计价正确性 | Decimal 公式、UTC 边界/周末/跨时段、缓存别名与缺失拆分、极小金额、失效/过旧价格、1200 次累计通过 |
| 请求与事件 | 真实 HTTPX/SSE 客户端 + MockTransport，preview/sentence 两种模式的失败重试、重复 usage、取消前后有无用量、断流通过；无付费调用 |
| 实时完整性 | 失败用量即时发布、过时译文仍累计、版本去重、新会话重置、进程退出未结算转未知、保留已知金额通过 |
| GUI | 主窗口与性能面板同一累计值、输入/输出/缓存、未知/部分费用提示通过；没有自动启动捕获 |
| 编译及打包 | compileall 通过；离线 wheel 构建成功且检查包含价格 JSON 和两处 usage 模块；[构建日志](evidence/usage-package-build.txt) |
| Qt 离屏预览 | [主窗口](evidence/usage-main-preview.png)、[性能面板](evidence/usage-performance-final.png)已检查；未启动翻译，显示未知而非示例消费 |
| 真实账单与课程长测 | **未执行**；未使用用户真实密钥发送请求或查询余额，未加载 GPU 模型 |

唯一跳过是需要显式启用及真实音频的 M0 smoke。最初一次受限环境的专项测试长时间没有继续输出，已只终止本轮匹配唯一标识的测试 Python；随后完成上述全量回归，未关闭用户应用或改变生产设置。

本轮没有新的实际翻译延迟、GPU、准确率或真实消费测量。正式核对需用户正常使用后，确认“性能统计”的用量和 DeepSeek 平台同一时间段记录；账户其他调用或充值不能直接归因本次 ELT。M3 的 30/60 分钟、显示兼容性和真实异常验收仍按原计划待执行，本地模型计划保持延后。
