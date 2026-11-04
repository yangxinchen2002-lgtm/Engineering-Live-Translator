"""Create a local, self-contained audition report from actual lab measurements."""
import argparse
import html
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    fast = json.loads((root/'fast-benchmark/results.json').read_text(encoding='utf-8'))
    official_path = root/'official-smoke/results.json'
    official = json.loads(official_path.read_text(encoding='utf-8')) if official_path.exists() else None
    cpu=json.loads((root/'cpu-benchmark/results.json').read_text(encoding='utf-8'))
    integrations=sorted(root.glob('integrated-course*/results.json'))
    integrated=next((json.loads(p.read_text(encoding='utf-8')) for p in reversed(integrations)
                     if json.loads(p.read_text(encoding='utf-8')).get('passed')),None)
    escape = html.escape
    def memory(stage):
        return fast['vram'].get(stage, {}).get('peak_bytes', 0)/2**30
    def p50(section, key):
        return fast['summary'].get(section, {}).get(key, {}).get('p50', 0)
    def ms(section, key, quantile):
        return fast['summary'].get(section, {}).get(key, {}).get(quantile, 0)*1000
    memory_rows = ''.join(f'<tr><td>{name}</td><td>{memory(stage):.2f} GiB</td></tr>' for stage,name in [
        ('baseline','运行前整机显存'),('asr_alone','仅语音识别'),('tts_cold','朗读首次生成与预热'),('tts_alone','仅语音朗读（已预热）'),
        ('both_resident','两模型加载后待机'),('concurrent_inference','两者并行推理')])
    latency_rows = ''.join(f'<tr><td>{name}</td><td>{ms(section,"response_s","p50"):.0f} ms</td>'
                           f'<td>{ms(section,"response_s","p95"):.0f} ms</td>'
                           f'<td>{ms(section,"schedule_lag_s","max"):.0f} ms</td></tr>'
                           for section,name in [('asr_alone','识别单独运行'),('asr_overlapping','识别与朗读推理重叠')])
    tts_rows = ''.join(f'<tr><td>{name}</td><td>{p50(section,"first_audio_s"):.2f} s</td>'
                       f'<td>{p50(section,"minimum_gapless_prebuffer_s"):.2f} s</td>'
                       f'<td>{p50(section,"generation_per_audio_s"):.2f} s</td></tr>'
                       for section,name in [('tts_alone','仅朗读'),('tts_concurrent','同时持续识别')])
    labels = {'ordinary':'普通中文 · Serena 女声','technical':'工科术语 · Serena 女声',
              'polyphones':'中文多音字 · Serena 女声','long_chinese':'中文长段落与语调 · Serena 女声',
              'mixed':'中英混读 · Serena 女声','numbers':'数字与单位 · Serena 女声',
              'symbols':'公式符号 · Serena 女声','vivian':'同文对比 · Vivian 女声',
              'uncle_fu':'同文对比 · Uncle Fu 男声'}
    readback = {x['id']: x['recognized'] for x in fast.get('chinese_readback', [])}
    cards = []
    for row in fast['tts_alone']:
        filename = 'fast-benchmark/'+Path(row['output']).name
        cards.append(f'<article><h3>{labels.get(row["id"],escape(row["id"]))}</h3>'
                     f'<p>{escape(row["text"])}</p><audio controls preload="none" src="{escape(filename)}"></audio>'
                     f'<p class="small">音频 {row["duration_s"]:.2f} 秒；首段可用 {row["first_audio_s"]:.2f} 秒；'
                     f'全部生成 {row["generation_s"]:.2f} 秒。</p>'
                     f'<details><summary>自动回读检查（语音识别也可能读错）</summary>'
                     f'<p>{escape(readback.get(row["id"],"未执行"))}</p></details></article>')
    extra_path=root/'extra-presets/results.json'
    if extra_path.is_file():
        extra=json.loads(extra_path.read_text(encoding='utf-8'))
        names={'dylan':'Dylan · 北京口音','eric':'Eric · 四川口音','ryan':'Ryan · 英语音色',
               'aiden':'Aiden · 英语音色','ono_anna':'Anna · 日语音色','sohee':'Sohee · 韩语音色'}
        for row in extra['voices']:
            cards.append(f'<article><h3>{names[row["speaker"]]}</h3><p>{escape(row["text"])}</p>'
                         f'<audio controls preload="none" src="extra-presets/{escape(Path(row["output"]).name)}"></audio>'
                         '<p class="small">预设音色可生成检查；外语音色的中文读法请试听比较。</p></article>')
    official_note = ''
    if official and official['tts_alone']:
        row = official['tts_alone'][0]
        official_note = f'<p>官方普通推理，同样的普通中文：音频 {row["duration_s"]:.2f} 秒，'
        official_note += f'整段可用等待 {row["first_audio_s"]:.2f} 秒。</p>'
        official_note += '<audio controls preload="none" src="official-smoke/alone-ordinary.wav"></audio>'
    integrated_note='<p>完整课程验收尚未通过，请检查原始记录。</p>'
    if integrated:
        links=' · '.join(f'<a href="{escape(Path(row["path"]).relative_to(root).as_posix())}">AI 稿 {i+1}</a>'
                        for i,row in enumerate(integrated['ai_outputs']))
        integrated_note=f'<p>真实公开课程捕获、DeepSeek 中文翻译、扬声器完整播放、双语 TXT、自动 AI 稿和手动 AI 稿均通过。'
        integrated_note+=f'取得 {integrated["translated_segments"]} 个中文片段，完整播放 {integrated["playback_finished"]} 段。{links}</p>'
    content = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Qwen3-TTS 中文试听与本机测试</title>
<style>body{{font:16px/1.7 "Segoe UI","Microsoft YaHei",sans-serif;background:#f4f6fa;color:#18253a;margin:0}}
main{{max-width:1000px;margin:36px auto;padding:0 24px 60px}}h1{{font-size:30px}}h2{{margin-top:36px}}
article,.panel{{background:white;border:1px solid #dce3ed;border-radius:14px;padding:22px;margin:16px 0}}
table{{border-collapse:collapse;width:100%;background:white}}th,td{{border:1px solid #dce3ed;text-align:left;padding:10px}}
audio{{width:100%;max-width:660px}}.small,summary{{color:#53647c;font-size:14px}}.badge{{color:#155a40}}
code{{word-break:break-all}}a{{color:#215fc0}}</style><main>
<h1>Qwen3-TTS 中文试听与本机测试</h1><p>2026 年 11 月 1 日 · 语音生成完全本地 · 课程翻译及 AI 整理使用现有 DeepSeek</p>
<div class="panel"><strong>已整合进原 ELT</strong><p>双击原来的“启动ELT.cmd”。在“朗读”页选择音色和 GPU / CPU，可直接试听，或开启自动朗读中文译文。
在“存稿”页勾选“结束翻译后自动生成详细 AI 稿”，也可结束后点击“生成本次 AI 稿”，或选择已有 TXT 整理。</p>{integrated_note}</div>
<div class="panel"><strong class="badge">生成与并行运行检查：{str(fast['passed'])}</strong>
<p>朗读：Qwen3-TTS-12Hz-0.6B-CustomVoice，BF16，GPU，faster-qwen3-tts 0.2.6。<br>
识别：现有 Faster-Whisper large-v3-turbo，FP16，独立进程。<br>
显卡：{escape(fast['tts_ready']['gpu'])}。此状态只表示程序生成与并行流程完成；中文声音自然度请以下方试听为准，未编造人工听感评分。</p></div>
<h2>显存占用</h2><table><tr><th>场景</th><th>整张显卡采样峰值</th></tr>{memory_rows}</table>
<p class="small">NVML 每 20 ms 采样，包含桌面、其他程序、模型、缓存和运行库，不是模型独占显存。加载和首次预热峰值见原始结果。</p>
<h2>延迟</h2><table><tr><th>识别场景</th><th>响应 P50</th><th>响应 P95</th><th>最大调度落后</th></tr>{latency_rows}</table>
<p class="small">基准中模型加载阶段 {fast['tts_ready']['load_s']:.2f} 秒（不含 Python 与依赖启动）；首次生成的首段等待 {fast['tts_cold']['first_audio_s']:.2f} 秒。
两项不计入下方已经预热的统计。实际首次打开模型随磁盘缓存等波动，请等待界面就绪。</p>
<p>识别采用相同的 24 个德语/英语八秒窗口，每秒提交一次。共 {fast['overlapped_asr_count']} 次识别与朗读推理时间重叠；
前后转写完全一致 {fast.get('asr_identical_transcripts',0)}/{len(fast['asr_concurrent'])} 条。</p>
<table><tr><th>朗读场景</th><th>首段音频可用 P50</th><th>无间断播放所需预缓冲 P50</th><th>每生成一秒语音所用时间 P50</th></tr>{tts_rows}</table>
<p class="small">最后一列越小越快，小于 1 表示生成快于播放。首段可用不等于耳机实际发声；未测音频设备延迟。
并行测试连续发起朗读，负载高于等上一句播完再生成。首段之外也检查了后续分块是否来得及供应播放。</p>
<details><summary>官方实现的同文短测</summary>{official_note}</details>
<h2>CPU 模式</h2><p>模型与语音解码器实际均在 CPU，FP32，6 个推理线程。两条短中文与原 GPU 识别并行时：
朗读首段等待 P50 {cpu['summary']['tts_concurrent']['first_audio_s']['p50']:.2f} 秒；每生成一秒语音需要
{cpu['summary']['tts_concurrent']['generation_per_audio_s']['p50']:.2f} 秒；识别响应 P50
{cpu['summary']['asr_overlapping']['response_s']['p50']:.2f} 秒。整张显卡峰值
{cpu['vram']['concurrent_inference']['peak_bytes']/2**30:.2f} GiB，主要是原有识别模型。
CPU 可以使用，但无法跟上实时播放；推荐 GPU。此处 CPU 与 GPU 使用不同长度测试文本，不作为同文速度对比。</p>
<h2>中文试听</h2><p>先比较三种声音，再检查英文缩写、数字、单位和公式的读法。以下全部为本机生成的原始结果，未做人工修音。</p>
{''.join(cards)}
<h2>测试边界</h2><ul><li>这是短测，不代表已完成一小时稳定性验证。</li>
<li>识别时间按已收到音频后的推理/进程响应计算，没有计入课程等待、语音断句、DeepSeek 翻译或字幕绘制。</li>
<li>自动回读仅辅助检查内容，不能代替母语者对自然度、公式和术语的试听。</li>
<li>已接入原 ELT；GPU / CPU 均实测通过当前声卡完整播放，播放格式会自动转换。</li>
<li>GPU 首段可用约半秒是预热后的模型耗时，完整同传还包含识别、断句、翻译、音频缓冲和播放排队。</li>
<li>AI 稿生成会产生单独的 DeepSeek Token 用量；界面和稿件中显示该任务已报告用量。未完成的请求不会保存成正式 AI 稿。</li></ul>
<details><summary>原始证据与复现</summary><p><a href="fast-benchmark/results.json">完整测试结果</a> ·
<a href="fast-benchmark/memory-samples.json">显存采样</a> · <a href="fast-benchmark/tts-process.log">朗读进程日志</a> ·
<a href="cpu-benchmark/results.json">CPU 实测</a> · <a href="real-playback-fixed/results.json">实际播放与设备切换</a></p>
<p>模型文件的固定版本与 SHA-256 清单位于项目 models/Qwen3-TTS-12Hz-0.6B-CustomVoice/elt-manifest.json。
独立环境为 .venv-tts，原有 .venv 未安装或升级 TTS 依赖。</p></details></main></html>'''
    # Keep this HTML local: no CDN, analytics, network requests or autoplay.
    (root/'试听与测试报告.html').write_text(content, encoding='utf-8')
    print(root/'试听与测试报告.html')


if __name__ == '__main__':
    main()
