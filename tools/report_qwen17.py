"""Report the actual local 0.6B/1.7B comparison, auditions and playback checks."""
import argparse
from html import escape
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.check_lecture_voice_profile import render


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();base=args.root.resolve();output=base/'report';output.mkdir(parents=True,exist_ok=False)
    old=read(base/'baseline06/results.json');new=read(base/'benchmark17/results.json')
    playback=read(base/'playback17/results.json');switch=read(base/'model-switch/results.json')
    auditions=read(base/'auditions17/results.json');manifest=read(ROOT/'models/Qwen3-TTS-12Hz-1.7B-CustomVoice/elt-manifest.json')
    metrics=[]
    for title,key in [('预热后首段音频等待 · 单独朗读','first_audio_s'),('生成一秒原始语音所需时间 · 单独朗读','generation_per_audio_s')]:
        metrics.append((title,old['summary']['tts_alone'][key]['p50'],new['summary']['tts_alone'][key]['p50'],'秒'))
    for title,key in [('首段音频等待 · 与识别并行','first_audio_s'),('生成一秒原始语音所需时间 · 与识别并行','generation_per_audio_s')]:
        metrics.append((title,old['summary']['tts_concurrent'][key]['p50'],new['summary']['tts_concurrent'][key]['p50'],'秒'))
    metrics.append(('识别响应 · 与朗读并行',old['summary']['asr_overlapping']['response_s']['p50'],new['summary']['asr_overlapping']['response_s']['p50'],'秒'))
    metrics.append(('整张显卡并行推理峰值',old['vram']['concurrent_inference']['peak_bytes']/2**30,new['vram']['concurrent_inference']['peak_bytes']/2**30,'GiB'))
    table=''.join(f'<tr><td>{escape(title)}</td><td>{before:.3f} {unit}</td><td>{after:.3f} {unit}</td></tr>' for title,before,after,unit in metrics)
    samples=[]
    for title,source,name in [
        ('0.6B：原来的讲课男声',base/'baseline06/alone-lecture.wav','06-lecture.wav'),
        ('1.7B：Aiden，未给语气指令',base/'auditions17/keywords_aiden_default.wav','17-default.wav'),
        ('1.7B：Aiden，平稳讲课指令（软件采用）',base/'benchmark17/alone-lecture.wav','17-lecture.wav'),
        ('1.7B：Uncle Fu，平稳讲课指令',base/'auditions17/keywords_uncle_fu_lecture.wav','17-uncle-fu.wav'),
        ('1.7B：较长中文课程讲解',base/'benchmark17/alone-long_chinese.wav','17-long-chinese.wav'),
        ('1.7B：中英混读',base/'benchmark17/alone-mixed.wav','17-mixed.wav'),
        ('1.7B：中文术语与条件',base/'benchmark17/alone-technical.wav','17-technical.wav'),
        ('1.7B：数字、单位与日期',base/'benchmark17/alone-numbers.wav','17-numbers.wav'),
    ]:
        sample=render(source,output/name,1.25);sample['title']=title;samples.append(sample)
    cards=''.join(f'<article><h2>{escape(s["title"])}</h2><audio controls preload="none" src="{s["file"]}"></audio>'
                  f'<p>1.25 倍 · {s["duration_seconds"]:.2f} 秒 · 近静音压缩 {s["near_silence_removed_seconds"]:.2f} 秒</p></article>' for s in samples)
    labels={'lecture':'提示词与讲解','ordinary':'普通中文','technical':'术语与条件','polyphones':'多音字','long_chinese':'长段中文','numbers':'数字与日期','mixed':'中英混读','symbols':'字母与公式'}
    readback=''.join(f'<tr><td>{labels[r["id"]]}</td><td>{escape(r["reference"])}</td><td>{escape(r["recognized"])}</td></tr>' for r in new['chinese_readback'] if r['id'] in labels)
    cpu=next(r for r in switch['cases'] if r['device']=='cpu')
    from app.speech.config import LECTURE_INSTRUCTION
    checks={'benchmark06':old['passed'],'benchmark17':new['passed'],'continuous_playback17':playback['passed'],'model_and_device_switch':switch['passed']}
    check_labels={'benchmark06':'0.6B 生成与识别并行','benchmark17':'1.7B 生成与识别并行','continuous_playback17':'1.7B 持续播放','model_and_device_switch':'模型与设备切换'}
    checktext='；'.join(f'{check_labels[k]}：{"通过" if v else "未通过"}' for k,v in checks.items())
    content=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ELT 1.7B 讲课模式测试与试听</title><style>body{{font:16px/1.7 "Microsoft YaHei",sans-serif;background:#f3f6fb;color:#182238;max-width:1080px;margin:32px auto;padding:0 20px}}article,.panel{{background:white;border-radius:14px;padding:20px 24px;margin:16px 0}}h1{{font-size:28px}}h2{{font-size:20px}}audio{{width:100%}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}a{{color:#3158cf}}</style>
<h1>ELT 1.7B 讲课模式测试与试听</h1><p>2026-11-01 · RTX 3500 Ada Laptop 12 GB · 本机真实生成和播放</p>
<div class="panel"><h2>已整合进原 ELT</h2><p>仍用“启动ELT.cmd”。在“朗读”页切换“0.6B · 快速朗读”与“1.7B · 平稳讲课”，设备仍可选择 GPU / CPU。保留原音色、原声降低、可调语速和积压追赶。切换模型或设备会清空待播并重新准备，字幕继续。</p>
<p>1.7B 使用的语气指令：{escape(LECTURE_INSTRUCTION)}</p>
<p>该模型支持指令控制；0.6B 保持原始采样设置。指令是朗读风格要求，译文保持原样。语气控制存在生成差异，以下试听用于检查效果，没有人工自然度或情绪评分。</p>
<p>1.7B 模型与解码器文件合计 {sum(r['size'] for r in manifest['files'])/1e9:.2f} GB，固定版本 {manifest['revision']}，全部文件已校验。软件一次只载入一个朗读模型；切换测试验证了旧工作进程退出。</p></div>
<div class="panel"><h2>同文、同声、相同识别负载对比</h2><p>除显存峰值外，表中数值为中位数。两种模型均使用 Aiden、相同中文／混读素材和相同逐句种子，1.7B 增加讲课语气指令；使用相同的现有 Faster-Whisper GPU 模型与公开英／德课程片段。每轮 10 段生成包含 8 种文本，其中普通中文句重复三次。每秒语音的生成耗时按原始音频时长计算。</p>
<table><tr><th>项目</th><th>0.6B</th><th>1.7B</th></tr>{table}</table>
<p>首段音频时间从最终中文文本交给模型后计时，不包含识别、翻译或模型加载。两轮首次模型加载分别为 {old['tts_ready']['load_s']:.2f} / {new['tts_ready']['load_s']:.2f} 秒，第一次生成还含初始化，分别等待 {old['tts_cold']['first_audio_s']:.2f} / {new['tts_cold']['first_audio_s']:.2f} 秒；以上预热指标不代表首次启动体验。</p></div>
<div class="panel"><h2>持续播放与切换</h2><p>{escape(checktext)}</p>
<p>1.7B 在真实识别并行、每 4 秒输入一句的条件下，共顺序播放 {playback['sentences_played']} 句。最长排队 {playback['queue_wait_max_seconds']:.2f} 秒；前三句等待中位数 {playback['first_three_wait_median_seconds']:.2f} 秒，后三句 {playback['last_three_wait_median_seconds']:.2f} 秒。播放测试整卡峰值 {playback['whole_gpu_concurrent_peak_bytes']/2**30:.2f} GiB。</p>
<p>切换测试实际经历 0.6B GPU → 1.7B GPU → 1.7B CPU → 0.6B GPU，均完成声音输出，并检查上一工作进程已释放。CPU 短句生成 {cpu['generation']['generation_seconds']:.2f} 秒，原始语音 {cpu['generation']['audio_seconds']:.2f} 秒；CPU 可用但实时建议 GPU。</p>
<p>这是受控短测，包含长中文、术语、数字、混读和实际播放；没有宣称任意课程均无积压，也没有完成小时级稳定性验收。</p></div>
<h2>试听</h2><p>前四段内容相同，均包含“请注意”和“可惜”。播放使用软件的 1.25 倍语速和讲课预设的近静音压缩。</p>{cards}
<div class="panel"><h2>中文与混读自动回读</h2><p>自动回读用于辅助核对内容，不代替母语者试听。数字格式、同音字及数学符号读法需结合原文检查。</p>
<p>待人工核对：日期样本“11月1日”在两次回读中均漏回了“1”，“雅可比”出现“牙壳比”的回读，数学符号也有改写。已保留对应原始音频与试听；仅凭同一个识别模型的回读，不能确定是朗读还是识别问题，没有将这些样本认定为逐字准确通过。</p><table><tr><th>样本</th><th>原文</th><th>Whisper 回读</th></tr>{readback}</table></div>
<p>本页及试听完全保存在本机。<a href="https://github.com/QwenLM/Qwen3-TTS">Qwen 官方模型能力说明</a></p></html>'''
    (output/'1.7B讲课模式测试与试听.html').write_text(content,encoding='utf-8')
    (output/'comparison.json').write_text(json.dumps({'checks':checks,'metrics':[dict(title=t,before=a,after=b,unit=u) for t,a,b,u in metrics],
        'samples':samples,'auditions':auditions},ensure_ascii=False,indent=2),encoding='utf-8')
    print(output/'1.7B讲课模式测试与试听.html')


if __name__=='__main__':main()
