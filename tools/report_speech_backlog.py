"""Local before/after queue measurements and pitch-preserving audition files."""
import argparse
import html
import json
from pathlib import Path
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.speech.playback import PlaybackConverter


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--audio',type=Path,required=True);args=parser.parse_args()
    root=args.directory.resolve();data=json.loads((root/'results.json').read_text(encoding='utf-8'))
    with wave.open(str(args.audio),'rb') as source:
        if source.getnchannels()!=1 or source.getsampwidth()!=2:raise ValueError('mono PCM16 audition required')
        rate=source.getframerate();pcm=source.readframes(source.getnframes())
    cards=[]
    for speed in (1.,1.25,1.8):
        converter=PlaybackConverter(rate,rate,1,'s16',speed,dynamic=speed!=1.)
        chunks=[]
        for offset in range(0,len(pcm),30720):chunks.extend(converter.convert(pcm[offset:offset+30720]))
        chunks.extend(converter.convert(b''));filename=f'uncle-fu-{speed:.2f}x.wav'
        with wave.open(str(root/filename),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(b''.join(chunks))
        cards.append(f'<p>{speed:.2f} 倍 · 同一原始声音，保持音调</p><audio controls preload="none" src="{filename}"></audio>')
    before,after=(data['results'][name] for name in ('before','after'))
    metrics=[('最长排队等待','queue_wait_max_s'),('排队等待中位数','queue_wait_p50_s'),
             ('句间空等中位数','between_sentences_p50_s'),('从第一句输入到全部播完','elapsed_from_first_input_s')]
    rows=''.join(f'<tr><td>{label}</td><td>{before[key]:.3f} 秒</td><td>{after[key]:.3f} 秒</td></tr>' for label,key in metrics)
    waits=''.join(f'<tr><td>{i+1}</td><td>{old:.2f} 秒</td><td>{new:.2f} 秒</td></tr>'
                  for i,(old,new) in enumerate(zip(before['queue_wait_by_sentence_s'],after['queue_wait_by_sentence_s'])))
    content=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>ELT 朗读积压修复复验</title>
<style>body{{font:16px/1.7 "Microsoft YaHei",sans-serif;color:#20304b;background:#f4f6fa;max-width:920px;margin:30px auto;padding:20px}}
table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #dce3ed;padding:10px;text-align:left}}audio{{width:100%;max-width:640px}}h2{{margin-top:32px}}a{{color:#315fbe}}</style>
<h1>ELT 朗读积压修复复验</h1><p>2026-11-01 · 真实 GPU 生成与声卡播放 · 不调用 API</p>
<p>每 4 秒输入一句，连续 12 句，Uncle Fu 男声；两轮逐句使用相同随机种子，音频时长完全一致。
原版本逐句等播放结束后才生成；修复后播放时预生成下一句，基础 1.25 倍，积压时自动加速。
两轮均按顺序完整播放全部 12 句。检查通过：{data['passed']}。</p>
<table><tr><th>指标</th><th>修复前</th><th>修复后</th></tr>{rows}</table>
<h2>逐句等待</h2><table><tr><th>句序</th><th>修复前</th><th>修复后</th></tr>{waits}</table>
<h2>语速试听</h2><p>今天我们学习线性代数。请先理解矩阵的含义，再看后面的计算过程。</p>{''.join(cards)}
<p>试听由此前同一原始音频变速得到，用于比较语速与音调；没有重生成不同声音。</p>
<h2>使用与边界</h2><p>当前旧窗口需先停止、保存所需内容并关闭，再通过原“启动ELT.cmd”重开。
在“朗读”页调整基础语速（0.80–2.00 倍）及“积压时自动加速”（自动最高 1.80 倍）；语速可在播放中调整。
仅预生成下一句，保留全部译文；停止或切换设备会取消待播。</p>
<p>此为受控短测，不含识别、断句与翻译等待，不代表所有课程均无积压，也不是一小时稳定性验证。
音调保持使用 <a href="https://ffmpeg.org/ffmpeg-filters.html#atempo">FFmpeg atempo</a>，本机另用固定音高信号核对了变速前后频率。</p>
<p><a href="results.json">原始数据与事件</a></p></html>'''
    (root/'修复复验.html').write_text(content,encoding='utf-8');print(root/'修复复验.html')


if __name__=='__main__':main()
