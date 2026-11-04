"""Reference-cue timing from saved *real-time file* traces, with explicit coverage.

Never use on accelerated input or assume word timestamps prove recognition correctness.
Only completely/equally aligned cues without inserted words receive a matched-cue latency.
All other reference cues remain counted in the denominator of deadline coverage.
"""
from __future__ import annotations
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
from .evaluation import read_cues,tokens
from .types import RATE


def reference_latency(log: Path, reference: Path, seconds: float) -> dict:
    from jiwer import process_words
    rows=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()]
    session=next(r for r in rows if r['event']=='asr_session')
    if not session['realtime']:
        raise ValueError('accelerated input has no real-time latency')
    events=[r for r in rows if r['event']=='transcript']
    finals=[r for r in events if r['state'] in ('stable','committed')]
    cues=read_cues(reference,seconds)
    hyp=[];positions=[]
    for event in finals:
        for word in event['words']:
            for token in tokens(word['text']):
                hyp.append(token);positions.append((word['start'],word['end']))
    ref=[];cue_ranges=[]
    for cue in cues:
        first=len(ref);ref.extend(tokens(cue.text));cue_ranges.append((first,len(ref)))
    if not hyp:
        return {'reference_cues':len(cues),'fully_matched_cues':0,'matched_preview':None,'all_cue_preview_within_2s_fraction':0.0}
    alignment=process_words(' '.join(ref),' '.join(hyp))
    matched={}
    for chunk in alignment.alignments[0]:
        if chunk.type=='equal':
            matched.update(zip(range(chunk.ref_start_idx,chunk.ref_end_idx),range(chunk.hyp_start_idx,chunk.hyp_end_idx)))
    by_token=defaultdict(list)
    for i,t in enumerate(hyp):by_token[t].append(i)
    first_seen={};stable_seen={};commit_seen={}
    for event in events:
        last=-1
        for word in event['words']:
            for token in tokens(word['text']):
                candidates=[i for i in by_token[token] if i>last and abs(positions[i][0]-word['start'])<=int(.6*RATE)]
                if not candidates:continue
                i=min(candidates,key=lambda j:abs(positions[j][0]-word['start']))
                last=i
                for mapping in ([first_seen,stable_seen,commit_seen] if event['state']=='stable' else
                                [first_seen,commit_seen] if event['state']=='committed' else [first_seen]):
                    mapping[i]=min(mapping.get(i,event['displayed_ns']),event['displayed_ns'])
    origin=events[0]['audio_end_ns']-events[0]['end_sample']*1_000_000_000//RATE
    preview=[];stable=[];committed=[];details=[]
    for cue,(first,end) in zip(cues,cue_ranges):
        if first==end or any(i not in matched for i in range(first,end)):continue
        indices=[matched[i] for i in range(first,end)]
        if indices!=list(range(indices[0],indices[0]+len(indices))):continue
        baseline=origin+round(cue.end*1e9)
        values={}
        for name,mapping,output in [('preview',first_seen,preview),('stable_agreement',stable_seen,stable),('committed',commit_seen,committed)]:
            if all(i in mapping for i in indices):
                value=(max(mapping[i] for i in indices)-baseline)/1e9
                output.append(value);values[name+'_seconds']=value
        details.append({'start':cue.start,'end':cue.end,**values})
    def distribution(v):
        return {'count':len(v),'p50':float(np.percentile(v,50)) if v else None,
                'p95':float(np.percentile(v,95)) if v else None,'minimum':min(v) if v else None}
    return {'reference_cues':len(cues),'fully_matched_cues':len(details),
            'exact_cue_match_fraction':len(details)/len(cues),
            'matched_preview':distribution(preview),'matched_stable_agreement':distribution(stable),
            'matched_committed':distribution(committed),
            'all_cue_preview_within_2s_fraction':sum(v<=2 for v in preview)/len(cues),
            'all_cue_stable_agreement_within_3s_fraction':sum(v<=3 for v in stable)/len(cues),
            'all_cue_committed_within_3s_fraction':sum(v<=3 for v in committed)/len(cues),
            'details':details,
            'method':'exact WER alignment; timestamp-constrained event matching (0.6s); reference cue end; matched-only percentiles plus ALL-cue deadline coverage',
            'limits':'publisher cue timing and word alignment uncertainty; matched-only percentiles cannot establish overall target attainment; negative values retained'}
