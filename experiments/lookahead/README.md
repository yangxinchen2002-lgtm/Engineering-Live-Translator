# 网页视频预读兼容入口

网页跟随已接入正式 ELT，核心实现位于 `app/web_follow`。请使用项目根目录 `ELT.exe`，在课程页选择“网页视频预读”。本目录保留测试、既有扩展安装路径和旧快捷入口兼容；旧 EXE 也会转到正式界面的网页模式，不再另起实验应用。扩展目录由 `tools/sync_web_extension.py` 同步为正式版。下方保留早期实验使用说明，当前流程以正式 README 为准。

## 早期 v0.3.3 说明

在原 Edge 课程播放器上显示双语字幕、朗读中文，提前尝试准备未来约 15 秒的内容。**ELT 不控制原视频的播放、暂停、跳转、倍速或音量。** 这是独立实验，没有合入正式 ELT，不修改正式版源码、配置或桌面入口。

## 使用

扩展已经安装过，无需重新选择文件夹。更新后，在 `edge://extensions` 的“ELT 网页跟随 · 隔离实验”卡片点一次重新加载，再在方便时手动刷新课程页。

1. 保持正式 ELT 的字幕和朗读停止，避免加载两份模型。
2. 双击本目录 **ELT视频预读实验.exe**，打开 Edge 中的本机设置页，不显示命令窗口。实验目录需留在原项目内，沿用现有 Python 环境和模型。
3. 选择翻译服务，需要中文时勾选云翻译和中文朗读。**视频来源留空。** 点“连接网页跟随扩展”。非敏感选项会保存在本实验目录，供下次恢复。
4. 在 TUM-Live 或 Moodle 原网页正常播放课程，点工具栏中的 ELT 扩展，选择语言，点“开始跟随当前课程页”。无需复制媒体链接。
5. 用原网页控制播放、暂停、拖动和倍速。首次加载模型或网络较慢时，视频继续播放，字幕可能暂时跟不上。
6. 点字幕面板或扩展中的“停止 ELT”，停止字幕、朗读并释放模型；原视频保持用户选择的状态。设置页的“关闭实验服务”可结束本地服务。

服务、浏览器重启或扩展重新加载后，需要再次连接。关闭设置页不会停止已开始的原网页跟随。源视频页关闭或持续 120 秒没有源播放器心跳时释放工作进程。配对后本地服务无任何心跳超过 180 秒退出，未配对时为 60 秒。

扩展重新加载后，已经打开的课程页和实验设置页也需要由用户手动刷新。旧内容脚本的扩展上下文已失效，不能通过仅点击“重新开始”恢复。v0.3.1 会接住消息接口的同步异常和异步拒绝，停止旧计时器、清理自己的朗读并提示刷新，不自动刷新或暂停视频；普通连接失败仍可重试。错误列表中的旧记录不会自行消失，页面更新后可手动清除。参见 [Chrome 官方重载说明](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#reload-the-extension)。

v0.3.2 在点击开始时先验证本机服务和配对，再等待网页实际建立来源会话；未开服务、配对过期、会话失效、服务超时和未找到媒体会给出不同提示，不再仅凭网页脚本已启用就显示“已开始”。首次建会话失败不会把后续重试误当作时钟更新；临时本机连接失败时保留已有识别原文。扩展不能独自启动 Python 服务，每次使用需先打开实验 EXE 并在设置页连接。

## 同步与错误处理

- 原网页 `video.currentTime`、暂停状态和倍速驱动字幕与朗读。不会暂停视频等待识别、翻译或朗读。
- 按句末标点和明显停顿跨识别片段合并，不按 Whisper 片段、40 个词或 6 秒补充窗口直接拆句。同一识别片段中的两句话也分开处理，保护常用缩写、小数和序号。
- 先读目标窗口之后 8 秒的右侧上下文；句子未结束或句号紧贴音频切口时，再扩到本批起点后最多 30 秒（另带 1 秒左侧上下文）。不会因为窗口到头就立即翻译半句话。首次加载/跳到句中时，第一句仍可能缺少此前内容。
- 中文整句只翻译、合成一次。默认以正常 1 倍朗读；只有按剩余原句时长来不及读完时才加速，最高 4 倍，不为了填满原句时间而减速。提前读完就安静等待下一句，不重复、不抢读下一句。句中保持语速稳定；用户改变视频倍速时，仅根据本句剩余语音和剩余时间重新判断是否需要加快，最低仍为 1 倍。提前最多 8 秒准备下一句音频，缓存仅一条，不提前出声。
- 极长译文或迟到音频仍可能读不完；到句段结束即停止自己的朗读并记录超时，不挤占下一句，不暂停视频。超过上下文/长度上限时优先在逗号或停顿处分段，实在没有才按词边界切分，并记录 `long_clause` / `limit`，不宣称这些都是完整语法句。
- 识别先产生原文，译文与语音逐条补充，不等待整批云请求结束。翻译超时保留原文和错误提示；晚于视频当前时间的字幕不能保证补显示。
- 原文和中文各自优先显示两行，按字幕宽度自动缩小到最低 10 px；窗口变宽或下一句较短时恢复合适字号。极窄窗口或极长文本在最小字号下仍超过两行时继续换行显示全文，不裁切句尾。排版只影响显示，不再为了放进一行拆开翻译或朗读。
- 跳转或换来源使旧字幕、语音请求和识别结果失效。一次只跟随用户主动选择的一个视频页。
- 处理落后时跳过过时窗口，显式记录次数、秒数和 `source_complete=false`，不能宣称全文翻译完整。
- 工作进程异常退出时记录退出码，最多自动重建一次；再次失败显示错误。恢复机制通过独立真实 GPU 故障注入测试，仍不代表长期稳定性已验证。

## 网站与隐私边界

已经实测用户指定的 TUM-Live 英语课（HLS）和 Moodle 内嵌 Opencast 德语课（MP4）。扩展通过视频 `currentSrc` 或当前文档资源时间记录发现媒体；跨域播放器由相应 iframe 内的内容脚本读取。

网页权限限 `live.rbg.tum.de`、`edge.live.rbg.tum.de`、`moodle.tum.de` / `www.moodle.tum.de`、`video.opencast.tum.de` 和 `127.0.0.1`。额外 API 权限只有 `storage`，配对令牌保存在浏览器会话内存。没有 Cookie、密码、麦克风、调试器、WebRequest、历史记录、下载或所有网站权限。找不到媒体会明确提示。

不支持任意网站、直播、DASH、DRM、加密 HLS、任意 blob 链接或无法正常直读的媒体。网站改版、链接过期和其他编码需重新验证。备用本地播放器可手动输入文件路径或直达媒体，其代理依赖实验服务；关闭服务后不能保证继续加载。主要验收对象是原网页跟随模式。

API Key 通过正式版凭据接口使用，不复制到实验配置或扩展。云翻译仅发送必要文字、有限上下文和术语，不上传原始音频。中文使用 Windows SAPI 音色，临时 WAV 缓存最多 16 MiB、停止清理，不默认保存课程录音或字幕稿。

## 实现与复测

`bridge.py` 管理配对和源会话；`extension/content.js` 只观察视频，`core.js` 只控制自己的朗读。Python 仅监听本机随机端口，页面与扩展分别鉴权。一个 spawn GPU 进程加载 large-v3-turbo / CUDA / float16。PyAV 读取真实格式和时间戳、平均混合声道并重采样至 16 kHz Float32。

初始目标预读 15 秒，后续每批约 5–6 秒；`sentences.py` 使用原始单词时间戳确认句末，一句话可越过补充窗口并由前一批完整拥有，下一批从该句结束位置继续，避免前句尾巴与后句开头粘连。句末确认最多两次识别，因此首次准备可能更慢，不承诺延迟降低。缺少标点时，以至少 1 秒停顿或文件末尾确认边界；最多 30 秒、760 字符、160 个识别词为一个单元，达到上限必须显式分段。`sentence_context_passes`、`decoded_until`、`sentence_boundaries` 记录确认和降级情况。

翻译复用现有客户端、术语和用量统计，单条超时 12 秒、不重试，上下文最多 5 条且有字符预算。HTTP 并发 16、任务队列 1、结果队列 6、字幕最多 96 条、HLS 映射最多 8192 项、播放列表最多 2 MiB。

HLS 按音轨定位并读取窗口前 6 秒再裁剪。初始无时间戳 AAC 预备帧可跳过并计数，中途无时间戳报错。只修复单个不超过 2 样本、累计不超过每秒 2 样本的舍入间隙并记录，更大缺口直接报错。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -B -m experiments.lookahead.server --open --edge
.\.venv\Scripts\python.exe -B -m pytest experiments/lookahead/tests -p no:cacheprovider
node --test experiments/lookahead/tests/follow.test.mjs experiments/lookahead/tests/runtime.test.mjs experiments/lookahead/tests/connection.test.mjs experiments/lookahead/tests/sync.test.mjs
.\.venv\Scripts\python.exe -B -m experiments.lookahead.sentence_smoke --output experiments/lookahead/evidence/real-sentence-smoke.json
.\.venv\Scripts\python.exe -B -m experiments.lookahead.recovery_smoke --output experiments/lookahead/evidence/real-worker-recovery.json
```

恢复测试只终止自己创建的公开文件测试进程，不调用云 API、不操作网页。测试 GPU 前请先停止其他识别任务。`smoke.py` 可测文件和 SAPI；`snapshot.py` 显式保存计数、耗时和用量，不保存媒体地址或课程文字。验收见 [ACCEPTANCE.md](ACCEPTANCE.md)，扩展说明见 [extension/INSTALL.md](extension/INSTALL.md)。

参考：[Edge 本地扩展](https://learn.microsoft.com/en-us/microsoft-edge/extensions-chromium/getting-started/extension-sideloading)、[扩展网络请求](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)、[storage.session](https://developer.chrome.com/docs/extensions/reference/api/storage)、[currentTime](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/currentTime)、[playbackRate](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/playbackRate)。
