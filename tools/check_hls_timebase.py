"""Compare real WebView2/Hls.js clocks with PyAV on a generated public-fixture HLS.

Uses a separate test window and never touches an existing course player. Only
the existing public MIT fixture is remuxed into a temporary directory.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    import av
    import webview
    from app.web_follow.media import Source,probe
    result={};errors=[]
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self,*a):pass
        def copyfile(self,*a):
            try:super().copyfile(*a)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    with tempfile.TemporaryDirectory(prefix='ELT-HLS-Timebase-') as temporary:
        directory=Path(temporary);manifest=directory/'fixture.m3u8'
        with av.open(str(ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4')) as source:
            with av.open(str(manifest),'w',format='hls',options={'hls_time':'4','hls_list_size':'0',
                'hls_segment_filename':str(directory/'part-%03d.ts')}) as output:
                streams={s.index:output.add_stream_from_template(s) for s in source.streams if s.type in ('video','audio')}
                for packet in source.demux():
                    if packet.dts is None or packet.stream.index not in streams:continue
                    if float(packet.dts*packet.time_base)>35:break
                    # Nonzero transport timestamps, preserving A/V relationships.
                    delta=round(2.4/float(packet.time_base))
                    packet.dts+=delta
                    if packet.pts is not None:packet.pts+=delta
                    packet.stream=streams[packet.stream.index];output.mux(packet)
        (directory/'hls.js').write_bytes((ROOT/'app/web_follow/web/vendor/hls.light.min.js').read_bytes())
        (directory/'index.html').write_text('''<!doctype html><meta charset="utf-8">
<h2>ELT HLS 时间基准测试 · 公开样本</h2><video id="v" controls autoplay muted width="900"></video>
<script src="hls.js"></script><script>
window.check={events:[]};const v=document.querySelector('video'),h=new Hls();
h.on(Hls.Events.FRAG_CHANGED,(_,data)=>{check.fragment={start:data.frag.start,startPTS:data.frag.startPTS,endPTS:data.frag.endPTS};});
h.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal)check.error=data.details;});
h.loadSource('fixture.m3u8');h.attachMedia(v);
</script>''',encoding='utf-8')
        http=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(directory)))
        threading.Thread(target=http.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{http.server_port}/fixture.m3u8'
        result['pyav']=probe(Source.parse(url))
        window=webview.create_window('ELT · HLS 时间基准测试',url=f'http://127.0.0.1:{http.server_port}/index.html',width=1000,height=720)
        def run():
            try:
                limit=time.monotonic()+25
                while time.monotonic()<limit:
                    state=window.evaluate_js("(()=>{const v=document.querySelector('video');return {...window.check,position:v.currentTime,ready:v.readyState,seekable:v.seekable.length?v.seekable.start(0):null,duration:v.duration};})()")
                    if state and state.get('position',0)>1 and state.get('fragment'):break
                    time.sleep(.15)
                result['browser']=state
                assert state.get('fragment') and not state.get('error'),'real HLS playback failed'
            except BaseException as error:errors.append(type(error).__name__+': '+str(error))
            finally:window.destroy()
        try:webview.start(run,gui='edgechromium',private_mode=True,storage_path=str(directory/'profile'))
        finally:http.shutdown();http.server_close()
    result['errors']=errors;result['method']='Remuxed public MIT fixture with transport timestamps shifted +2.4 seconds; no user video or cloud API'
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
