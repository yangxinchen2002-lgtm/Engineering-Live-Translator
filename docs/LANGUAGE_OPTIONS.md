# 界面语言与英文翻译 / Interface and translation languages

2026-11-04，正式程序增量更新。沿用现有 ELT.exe 和桌面快捷方式。

## 使用 / Usage

1. 主窗口右上角选择 **English**，关闭并重新打开 ELT 后应用英文界面。选择 **Chinese / 简体中文** 可切回中文，偏好自动保存。
2. 原“启用中文翻译”现为 **启用翻译 / Enable translation**，右侧选择 **中文 / Chinese** 或 **English**。在开始字幕前选择目标，会话运行中锁定。
3. **原始语言 / Source language** 仍是讲课语言，与界面语言、翻译目标分别设置。八种既有原始语言继续可用。
4. 两种方式继续保留：**整句后翻译 / Full sentences (lower usage)**、**实时预览翻译 / Live preview translation**。原文继续实时显示。
5. **朗读 / Speech** 使用所选翻译目标。Qwen 英文可选 Aiden 或 Ryan；交互切换到英文目标时，原中文预设会优先切到 Aiden。Windows 音色按中文或英文筛选。
6. Edge 扩展：方便时在扩展管理页重新加载 **ELT Web Subtitles**，再刷新课程页、从 ELT 连接页重新连接。安装目录仍为 `experiments/lookahead/extension`；权限没有增加。更新没有自动刷新正在播放的课程。

Choose **English** at the top right and reopen ELT. Enable translation, then select **Chinese** or **English** beside the checkbox before starting. Source language, interface language and translation target are independent. Full-sentence and live-preview translation both remain available. Narration follows the translation target. Reload and reconnect the Edge extension when convenient.

## 界面覆盖及排版

覆盖主窗口课程、翻译、朗读、存稿设置，API 密钥、外观、性能、历史、诊断弹窗，普通与焦点悬窗，内置课程工具栏、本地播放器、网页连接页、扩展设置，以及状态和异常提示。启动器错误提示读取同一语言偏好。动态默认消息在使用时翻译，避免模块载入后固定为中文。

英文侧栏加宽为 386 逻辑像素，主窗口默认 1240×860、最小 1040×620；设置标签间距减小。缩短启动按钮、模型及顶部栏提示，英文扩展弹窗加宽为 480 CSS 像素。内容区保留滚动，长原文与译文可以完整查看。

本地化只处理 ELT 界面。课程网页、识别原文、译文、用户路径、音源应用和系统提供的名称保留实际内容；操作系统文件选择窗口沿用系统语言。原有文件命名、已保存稿件与 AI 课程梳理模板没有批量改写。

## 实现边界

| 部分 | 实现 |
|---|---|
| 界面 | `app/i18n.py`、`app/locales/en.json`；本地静态词条，无在线界面翻译请求；词条随 wheel 打包 |
| 配置 | `UISettings.ui_language/target_language`；旧偏好缺少新字段时默认中文；密钥与稿件保留 |
| 翻译 | `TranslationConfig.target_language=zh/en` 选择工程提示词，所有既有 API 来源共用目标设置 |
| 术语 | 英文目标使用同领域、相同中文释义关联的英文词；没有英文对应的自定义条目不作为中文目标指令送入英文请求 |
| 朗读 | 工作进程显式接收 `--language zh/en`；Qwen 使用实际 `language='English'`，1.7B 使用英文讲课指令；SAPI 按 LCID 筛选校验 |
| 网页 | 启动、配对、播放状态传递两种语言设置；界面词条仅作用于 ELT 自身页面，字幕节点不参加替换；设置请求失败提示也预先获得界面语言 |
| 存稿 | 按目标标注“中文 / 英文”；英文界面导出头部为英文，日期-原始语言-分钟命名保持兼容 |

Qwen 支持英语：[官方模型说明](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)、[发布说明](https://qwen.ai/blog?id=qwen3tts-0115)。本轮未下载或部署新的本地翻译模型。

## 验证与证据

本机 Windows x64、Python 3.12.10、PySide6 6.8.3、现有 WebView2、MSVC 19.44 / SDK 10.0.26100；Qwen 使用既有 `.venv-tts` 与 0.6B GPU 模型。

| 检查 | 实际结果 |
|---|---|
| 完整 Python 回归 | 889 通过，2 项硬件测试未选择；1 条既有 pkg_resources 弃用提示；[报告](evidence/language-options/python-regression.xml) |
| 后续语言/EXE/存稿 | 30 通过，含真实 EXE 从临时英文偏好启动；[报告](evidence/language-options/english-exe-transcript-tests.xml) |
| 最后默认提示及焦点/朗读 | 71 通过；最后中性译文提示复测 70 通过；这些专项与全量有重叠，不累计为独立用例数 |
| 最终网页与英文配置 | 49 通过，含真实服务生命周期；[报告](evidence/language-options/web-final-tests.xml) |
| JavaScript | 75 通过，含界面/字幕数据隔离、重复本地化、媒体时钟与朗读；[报告](evidence/language-options/javascript-tests.txt) |
| Qt 界面 | 16 个页面/状态，中文残留 0、按钮截断 0；[记录](evidence/language-options/desktop-layout.json)、[主界面](evidence/language-options/main-en.png) |
| WebView2 渲染 | 扩展、连接页、本地播放器无中文残留/横向溢出；顶部栏 800/1240/1600 宽度无标签截断；[记录](evidence/language-options/web-layout.json)、[扩展](evidence/language-options/extension-en.png)、[窄工具栏](evidence/language-options/toolbar-en-800.png) |
| 原生入口 | Release 构建成功，两个 EXE 已更新；[构建记录](evidence/language-options/launcher-build.txt) |
| 真实网页启动 | 界面→后台→HTTP 配置/本地化资源→正常退出，无媒体、模型或云请求；[记录](evidence/language-options/web-startup-en.json) |
| Qwen 英文短测 | Aiden、0.6B、CUDA，24kHz / 71,040 样本 / 2.96 秒，RMS 0.1118，正常退出；冷启动至退出 27.743 秒，不能当作持续推理延迟；[记录](evidence/language-options/qwen-en.json) |
| Windows 英文短测 | David、CPU，16kHz / 80,800 样本 / 5.05 秒，RMS 0.0877，正常退出；[记录](evidence/language-options/system-en.json) |
| 真实 DeepSeek 英文 | 两种模式各一次固定德语短句，均返回 “The matrix is not invertible.”，各报告 197 Token，共 394；仅测试文字，无课程音频；[记录](evidence/language-options/deepseek-en.json) |

音频短测验证真实合成及非静音 PCM，没有人工英文发音质量打分。1.7B 英文参数/指令有自动测试，未另做该模型真实英文合成。用户课程新版本听感、混合 DPI、60 分钟长测未执行，不据此标记完整 M3/MVP 验收。

## 维护

词条测试检查 `_tr` 调用与默认参数。`tools/audit_english_ui.py` 生成 Qt 页面并检查文字；`tools/render_english_web_ui.py` 在独立 WebView2 页面与原生控件上验证布局，不连接用户课程。改词条后运行 `tools/sync_web_extension.py`，同步已安装扩展目录与网页词条；新增界面文字同时补英文。
