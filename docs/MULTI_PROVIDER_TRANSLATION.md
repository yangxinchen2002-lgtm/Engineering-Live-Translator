# 多来源密钥与翻译 API 选择 — 2026-11-03

阶段：已授权的 M2/M3 扩展。现有桌面 EXE 沿用当前源码，重启即可使用。没有迁移或覆盖原 DeepSeek 密钥，没有下载模型、升级依赖或调用真实付费接口。

## 怎么使用

1. 重启 ELT，进入左侧 **“翻译”** 页，点击 **“设置翻译密钥”**。
2. 在弹窗“密钥来源”选择 DeepSeek、OpenAI · GPT、Anthropic · Claude 或 Google · Gemini，粘贴该平台的 API Key 后保存。可以重复操作，为不同来源分别保存密钥。
3. 回到翻译页，在 **“翻译 API 来源”** 选择这次要使用的服务，再选择或填写该服务支持的文本模型 ID。勾选“启用中文翻译”，按原步骤开始字幕。
4. 同时保留实时预览、整句后翻译两种模式；原文仍由本地 ASR 实时产生。切换服务和模型前先停止当前字幕会话；选项会记住，每个来源的模型分别保存。

每个来源目前保存一个密钥；再次保存只更新该来源，不影响其他三个来源。密钥弹窗只负责保存，**不会自动替你切换翻译来源**。来源后的“已配置”表示本机已读取到密钥，不表示已验证账号权限或余额；开始后的真实响应才能验证连接。切换弹窗来源会清空输入框，避免把一个平台的密钥误存到另一个来源。

已有 DeepSeek 密钥继续读取原位置，无需重填。默认仍选 DeepSeek，打开软件不会自动收音或调用云端。首次选中尚未配置密钥的来源时，可以先保存密钥，或继续使用本地原文模式。

本次 API 选择仅控制字幕翻译。现有“AI课程梳理”仍使用 DeepSeek，需单独保留它的密钥；不会把其他来源密钥拿去调用 DeepSeek。

## 已接入的官方接口

| 来源 | 协议/地址 | 内置默认模型 | 鉴权 |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com/chat/completions` | `deepseek-flash` | Bearer |
| OpenAI · GPT | `https://api.openai.com/v1/responses` | `gpt-4.1-mini` | Bearer |
| Anthropic · Claude | `https://api.anthropic.com/v1/messages` | `claude-haiku-5-5` | `x-api-key`，版本 `2023-06-01` |
| Google · Gemini | `https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse` | `gemini-3.5-flash-lite` | `x-goog-api-key`请求头 |

模型是预设，不是账号可用性检查，也未对上述默认模型的翻译质量/延迟作横向实测。可自行填写同来源的其他文本模型ID；不静默换模型、换密钥或切换服务。Anthropic 另预设 Sonnet 5.5，Gemini 另预设3.8 Flash。只接标准官方 API，本次不包含 Azure、Bedrock、Vertex、网页会员登录或第三方代理地址。

接口及模型核对来源：[OpenAI 流式响应](https://developers.openai.com/api/docs/guides/streaming-responses)、[GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[OpenAI 流事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)；[Claude 流式 Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)、[Claude 模型](https://platform.claude.com/docs/en/models/overview)、[Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview)；[Gemini 生成接口](https://aistudio.google.com/api-reference/generate-content)、[Gemini 3.5 Flash-Lite](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite)、[Gemini 鉴权示例](https://aistudio.google.com/docs/get-started)。

OpenAI 明确设置 `store=false`，不传 conversation/previous_response_id；DeepSeek 保留 `thinking.type=disabled`。其他新来源使用模型的默认推理设置，只向字幕输出正文、不输出思考块。没有启用工具、搜索、文件或多模态输入；只发送当前原文、有限上下文和相关术语。原始音频留在本机。

## 生命周期和安全边界

- 四个来源使用独立 Windows Generic Credential target：`ELT/DeepSeekAPIKey`、`ELT/OpenAIAPIKey`、`ELT/ClaudeAPIKey`、`ELT/GeminiAPIKey`。原 DeepSeek 名称不变；便携 profile 继续使用 `ELT/{profile}/…` 隔离，不读取主配置的密钥。
- 普通本机模式可分别读取 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`，对应来源的环境变量优先。密钥不放进 UISettings、TOML、日志、模型参数或进程命令行。Gemini 密钥也不放在 URL 查询中。
- 保存/读取在现有有界后台任务池进行，GUI 不执行网络验证。结果带来源标识，旧来源的异步返回不覆盖当前选中来源。取消后再次保存同一来源时，前一次未结束会明确提示，不将旧保存成功误报为新密钥保存成功。
- 模型设置只接受匹配来源的有限 ASCII 模型 ID。空值、半截前缀和常见密钥字符串不会被持久化为模型。配置只允许各家已注册的官方 HTTPS 地址，不跟随重定向；客户端校验 credential.provider 与所选来源一致。
- 一个字幕会话固定来源/模型。后台只读取所选来源密钥，构造一个对应客户端；原文模式不读取任何 API 密钥。选项通过非敏感命令行字段传给后台，密钥留在凭据库/进程内存。
- 三个新适配器继续输出统一 `delta / usage / done`，接入既有有界队列、上下文裁剪、revision/attempt校验、有限重试、原文回退和长短句显示顺序。OpenAI/Claude必须收到完整结束事件；Gemini必须收到STOP并正常读到EOF，保留末尾usage。截断、拒绝、工具输出、畸形流、断流和超时均不伪装Final。
- 取消、停止和异常会关闭流及HTTP客户端。连接/读写/池等待/整体期限继续独立诊断。默认连接3秒、单次12秒、任务有效期24秒及并发2沿用原配置；未声称这些参数对所有模型都达到实时目标。

## 用量和金额

四个来源都读取接口实际返回的 Token，累计快照只结算每个 attempt 一次。缺失字段保持未知，不用文本长度估Token，也不把未知金额记成零。

- OpenAI：读取 input/output/total，以及可用的缓存明细；输出包括接口计入的推理Token。
- Claude：合并 message_start/message_delta 的累计快照，输入包含已报告的缓存读取/写入，避免把同一快照重复相加。
- Gemini：按 totalTokenCount/promptTokenCount计算包含思考在内的输出；不把仅可见候选文本的Token当作全部输出。缺少必要字段时保留部分用量状态。
- **DeepSeek 原费用估算保留。其他来源目前显示“费用未估算”，金额以平台账单为准**，不会套用 DeepSeek 价格。自填的未匹配模型同样不会猜测价格。

## 修改文件

- `app/translation/providers.py`：来源、官方地址、模型预设和校验。
- `credentials.py`：分来源凭据，兼容旧target/profile/环境变量。
- `official_client.py`、`factory.py`：OpenAI Responses、Claude Messages、Gemini 原生流协议；DeepSeek既有适配器保留。
- `config.py`、`cli.py`、`app/main.py`、`config/translation.toml`：来源/模型配置、CLI选择和来源密钥命令。
- `worker.py`、`usage.py`、`app/ui/usage.py`：统一事件、来源对应的Token与未知金额显示。
- `app/ui/window.py`、`controller.py`、`preferences.py`：密钥来源弹窗、翻译API/模型选择、状态隔离、持久化及运行中锁定。
- `app/notes/service.py`：固定现有课程梳理的DeepSeek边界，防止翻译配置改变造成误用密钥。
- `tests/unit/test_multi_provider_api.py`、`test_multi_provider_settings.py`，`tools/render_gui.py`新增来源渲染选项。

## 真实测试记录

本机Windows11 x64、Python3.12.10、HTTPX0.28.1、PySide6 6.8.3及现有固定依赖；没有安装新的SDK。

| 检查 | 结果 | 证据 |
|---|---|---|
| 最终完整回归 | **775通过、1项显式现场音频测试未启用；84.92秒** | [完整记录](evidence/multi-api-final-release-pytest-20261103.txt) |
| 前一批完整回归 | 769通过、1项显式现场音频测试未启用；75.09秒 | [完整记录](evidence/multi-api-release-pytest-20261103.txt) |
| 密钥/接口最终专项 | 101通过；2.84秒，含取消/重复保存竞争检查 | [专项记录](evidence/multi-api-credential-final-20261103.txt) |
| 接口/设置/旧凭据/费用专项 | 155通过；2.65秒 | [记录](evidence/multi-api-final-targeted-20261103.txt) |
| 真实Qt布局 | 新来源/模型下拉及分来源密钥弹窗实际渲染，检查显示完整 | [GPT界面](evidence/multi-api-gpt-ui-20261103.png)、[Gemini密钥弹窗](evidence/multi-api-gemini-key-ui-20261103.png) |
| 现有EXE入口 | 退出码0，窗口创建，未开始收音或翻译 | [入口检查](evidence/multi-api-exe-startup-20261103.json) |

本地测试使用真实HTTPX/SSE解析器和标准MockTransport，覆盖官方地址/鉴权、任意字节分段、隐藏思考不显示、末尾usage、完整结束、断流、重定向拒绝、401/402/403/429/5xx、输出截断、取消、超时、畸形结构、Worker到Coordinator，以及四家密钥隔离、状态乱序、偏好、模型传递、重复保存与命令行防泄漏。Windows存储测试使用内存替身，不以测试值覆盖真实用户凭据。

**新来源的真实账号连接、余额/权限、翻译质量和延迟尚未执行。** 本轮没有使用这些服务的真实密钥进行计费测试，不把Mock通过视为真实服务验收。M3的30/60分钟与多显示器/混合DPI验收仍待执行。

## CLI与人工验收

推荐使用GUI保存密钥。CLI可在本机交互终端隐藏输入，禁止把密钥写在命令后：

```powershell
.\.venv\Scripts\python.exe -m app.main api-key set --provider openai
.\.venv\Scripts\python.exe -m app.main api-key status --provider claude
```

`--provider` 可选 `deepseek / openai / claude / gemini`；原 `deepseek-key set/status/delete` 继续可用。

只有准备进行真实计费测试时，再自行运行例如：

```powershell
.\.venv\Scripts\python.exe -m app.main translate-text --language en --text "The matrix is not invertible." --translation-provider openai --translation-model gpt-4.1-mini
```

字幕实时CLI对应增加同名 `--translation-provider` / `--translation-model`；原 `--model` 仍指ASR模型，不混用。GUI选择优先于配置默认，CLI不传覆盖参数时沿用 `config/translation.toml`。

人工验收时先为两个不同来源保存自己的密钥，在停止状态切换翻译来源/模型，确认状态和模型记忆正确；使用同一段短视频分别启动两次，核对原文连续、译文对应、实际Token变化、停止释放和错误时原文保留。不要把真实密钥发送到聊天或诊断文件。
