"""Build a local audition page using real recordings and the production playback path."""
import argparse
from html import escape
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.check_lecture_voice_profile import render


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();directory=args.output.resolve();directory.mkdir(parents=True,exist_ok=False)
    first=ROOT/'artifacts/lecture-voice-20261101'
    follow=ROOT/'artifacts/lecture-voice-followup-20261101'
    gpu=ROOT/'artifacts/lecture-profile-gpu-20261101-retry'
    cpu=ROOT/'artifacts/lecture-profile-cpu-20261101'
    rows=[]
    for title,source,filename,compact in [
        ('原来的 Ryan：同文对照',first/'ryan_original.wav','ryan-1.25x.wav',False),
        ('已选定的讲课男声：Aiden',first/'aiden_original.wav','lecture-male-1.25x.wav',True),
        ('较长的中文讲解',follow/'lecture_aiden_original.wav','lecture-long-1.25x.wav',True),
        ('中英混读、数字和单位',gpu/'mixed_raw.wav','lecture-mixed-1.25x.wav',True),
        ('CPU 版本短句',cpu/'chinese_raw.wav','lecture-cpu-1.25x.wav',True),
    ]:
        row=render(source,directory/filename,1.25,compact_pauses=compact);row['title']=title;rows.append(row)
    cards=''.join(f'<article><h2>{escape(r["title"])}</h2><audio controls preload="none" src="{r["file"]}"></audio>'
                  f'<p>{r["duration_seconds"]:.2f} 秒 · 1.25 倍；近静音压缩 {r["near_silence_removed_seconds"]:.2f} 秒</p></article>' for r in rows)
    content='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ELT 讲课男声试听</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;background:#f4f6fa;color:#182238;max-width:900px;margin:32px auto;padding:0 22px}article,.panel{background:white;border-radius:14px;padding:20px 24px;margin:16px 0}h1{font-size:28px}h2{font-size:20px}audio{width:100%}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}a{color:#3158cf}</style>
<h1>ELT 讲课男声试听</h1><p>2026-11-01 · 已整合进原软件，仍使用“启动ELT.cmd”</p>
<div class="panel"><p><strong>已选定：讲课男声 · Aiden（试用）</strong></p>
<p>本轮优先选择 Aiden，并对超过约 400 毫秒、低于 −60 dBFS 的连续近静音做压缩，保留约 320 毫秒。语速继续由原来的基础语速和积压追赶控制。该预设保留原有模型、其他音色和 CPU / GPU 选择，不增加模型体积。</p>
<p>目标是为长时间讲解提供一个可试听的候选。它不是新训练的模型，也没有使用声音克隆；没有强行拉平汉语声调、删改译文，或声称每个“可惜”都能按指定情绪朗读。</p>
<p>当前 0.6B 实现会忽略 instruct 语气指令。降低采样随机性在多段对照中也没有稳定改善停顿和语调，因此选定预设沿用 Aiden 的原始采样设置。原音色仍可随时切换。<a href="https://github.com/QwenLM/Qwen3-TTS">官方模型能力表</a></p></div>
<p>前两段内容相同：“请注意，这里的矩阵必须是方阵。可惜，这个方法只适用于线性系统。现在先把条件说明清楚，再按顺序介绍计算步骤。”均以 1.25 倍播放；只有讲课预设压缩近静音停顿。</p>'''+cards+'''
<div class="panel"><h2>本机复验</h2><p>测试显卡为 RTX 3500 Ada Laptop 12 GB。GPU 预热后的中英样本：首段约 0.28 秒，生成约 6.26 秒，原始音频 18.16 秒。该次独立生成的 PyTorch 峰值分配约 2.32 GiB；不是与识别模型并行的显存复测。</p>
<p>CPU 的中文短句：生成约 33.93 秒，原始音频 7.68 秒；压缩停顿后为 6.84 秒，以 1.25 倍播放约 5.47 秒。CPU 与 GPU 推理后端不同，节奏也可能不同。实时使用 GPU 更合适。</p>
<p>新预设的 CPU / GPU 中文短句在原始、停顿压缩后和 1.25 倍三个版本中均被 Whisper 完整回读。中英样本回读包含 Transformer、CPU、GPU、PID、48000 赫兹与 0.5%；“分担”被回读成同音的“分单”，不能仅据此判断朗读有误。未做课程长时稳定性复测。</p>
<p>实际本地工作进程 → 停顿压缩 → Qt 声音播放测试通过，无播放错误；451 项单元测试通过。音高统计和自动回读只作辅助，不能代替人工听感判断；这里没有人工自然度或情绪评分。</p></div>
<p>软件“朗读”页已提供该预设。“试听音色”也改为包含“请注意”“可惜”的讲解段落，便于之后反复比较。</p></html>'''
    (directory/'讲课男声试听.html').write_text(content,encoding='utf-8')
    (directory/'samples.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(directory/'讲课男声试听.html')


if __name__=='__main__':main()
