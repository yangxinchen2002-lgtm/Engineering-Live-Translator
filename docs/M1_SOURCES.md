# M1 评估素材与参考依据

本项目只对公开素材做本地个人工程评估；没有把它们用来训练/微调模型，也不把视频、完整字幕或新录音作为源码发布。下载文件位于被忽略的 `tests/fixtures/public-m1`，SHA-256/大小/确切 URL 在其 manifest.json 中。脚本为 `tools/fetch_m1_samples.py`。

## 英语主样本

Gilbert Strang，MIT 18.06，Lecture 1: The geometry of linear equations。主题是线性方程、矩阵、行列与向量。选取文件前 900 秒。

- [MIT 官方课程视频与字幕页](https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/resources/lecture-1-the-geometry-of-linear-equations/)
- [官方页面链接的视频](https://archive.org/download/MIT18.06S05_MP4/01.mp4)
- [MIT 英语 VTT](https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/d292ec07b3ed5124ae1409dc520e61fe_J7DzL2_Na80.vtt)
- [MIT 使用条款/CC BY-NC-SA 4.0](https://ocw.mit.edu/pages/privacy-and-terms-of-use/)

音视频 SHA-256：a3fa5bb22fa65d96f95452ae8ef80cd0a743f24ff6d47b7a24332598fa316a31；字幕 SHA-256：9fa6200af463b9e099735faf930e08ff55d4f9e13e09e107be19fe870d6e3d93。

这是官方发布参考，不是本项目新增的逐字人工 gold 标注。数学符号/数字写法、口头语和字幕编辑可能与逐字语音不同。公开常见教材也可能出现在模型训练资料中，不能宣称是未见测试集。与 MIT 不存在合作或背书关系。

## 德语主样本

zaolin，35C3，Open Source Firmware — Eine Liebesgeschichte（2018-12-27）。主题包含固件、处理器、BIOS、操作系统、coreboot/LinuxBoot 等计算机工程内容。选取文件前 900 秒。

- [CCC 官方讲座页/下载列表](https://media.ccc.de/v/35c3-9778-open_source_firmware)
- [德语 MP3](https://cdn.media.ccc.de/congress/2018/mp3/35c3-9778-deu-Open_Source_Firmware_mp3.mp3)
- [正式德语 SRT](https://media.ccc.de/srt/congress/2018/35c3-9778-deu-eng-Open_Source_Firmware.de.srt)
- [CCC 官方字幕工作流程说明](https://events.ccc.de/en/tag/subtitles/)

音频 SHA-256：c5fa993be52366167e37992cfd5f2f8f3f7ada2257e172a62758527f32d5d157；字幕 SHA-256：47f0412fd32182d65d36da56c28cd806a1405f4d5a79071e38747cb75246c8d8。

该 SRT 没有 DRAFT/todo 标记，末尾署名为 c3subtitles.de、2019。官方字幕流程包含从自动稿经志愿者改进/校正；这些来源支持把正式发布字幕用作参考，但不能证明本文件每个词都已独立核对。本项目不声称完成了新的整段人工审校。字幕中含非语音音乐标记、Herald 标签、口语省略与术语拼写问题，原始评分保留这些局限。重新分发素材前按原发布者的具体许可办理；当前仓库只发布获取脚本和来源说明。

## 德语辅助样本（不作为正式 gold）

Annika Rüll，37C3，[Lass mal das Innere eines Neuronalen Netzes ansehen!](https://media.ccc.de/v/37c3-11784-lass_mal_das_innere_eines_neuronalen_netzes_ansehen)。主题为神经网络和可解释机器学习。官方字幕明确含 DRAFT/todo，因此用于早期链路 smoke，不据此宣布正式准确率验收通过。

## 评估约定

只使用样本区间中完整结束的字幕 cue；Unicode NFKC、大小写归一、去标点，不展开数学数字，不根据模型输出改写参考。WER 的替换/删除/插入由固定版本 jiwer/rapidfuzz 对齐计算。术语表在 benchmark 脚本中预先列明，按参考实际出现次数和完全正确对齐计分；没有出现的词不计入分母。参考全文从不作为模型提示词、hotwords 或字幕答案输入。

参考时间分析仅适用于 paced-file --realtime 记录。完整匹配 cue 的延迟必须连同匹配覆盖率发布，不能以该子集代替全部音频的表现。未匹配 cue 仍计入 ALL-cue 时限覆盖率的分母。负延迟不裁掉，可能反映字幕延后或时间对齐误差。
