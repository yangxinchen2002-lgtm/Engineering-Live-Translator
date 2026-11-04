from pathlib import Path
import json
import httpx
import numpy as np
import pytest
from app.web_follow.local_media import LocalMediaHost
from app.web_follow.media import Source,probe,decode_window
from app.web_follow.player import observation,Player
from types import SimpleNamespace as NS


@pytest.fixture
def host():
    value=LocalMediaHost()
    try:yield value
    finally:value.close()


def test_only_explicit_file_is_served_with_range_and_no_path_disclosure(host,tmp_path):
    path=tmp_path/'课程 # 文件.mp4';data=bytes(range(256))*16;path.write_bytes(data)
    page=host.select(str(path));source=host.source_for(host.origin+'/m/'+host.selection.token)
    assert source.value==str(path.resolve()) and source.local_identity
    with httpx.Client(base_url=host.origin,trust_env=False) as client:
        document=client.get(page);assert document.status_code==200 and str(path).encode() not in document.content
        assert client.get(page.replace('player.html','info.json')).json()['name']==path.name
        media=host.origin+'/m/'+host.selection.token
        response=client.get(media,headers={'Range':'bytes=10-29'})
        assert response.status_code==206 and response.content==data[10:30]
        assert response.headers['content-range']==f'bytes 10-29/{len(data)}'
        assert client.get(media,headers={'Range':'bytes=-10'}).content==data[-10:]
        assert client.head(media).headers['content-length']==str(len(data))
        assert client.get(media,headers={'Range':'bytes=99999-'}).status_code==416
        assert client.get('/m/wrong').status_code==404
        assert client.get(media,headers={'Origin':'https://evil.example'}).status_code==403
        assert client.get(media,headers={'Host':'evil.example'}).status_code==403
        assert client.get('/p/'+host.selection.token+'/../../private').status_code==404
        assert client.get(media+'?path='+str(path)).status_code==403


def test_replacement_or_modification_invalidates_old_media_and_file_selection(host,tmp_path):
    first=tmp_path/'first.mp4';second=tmp_path/'second.mp4';first.write_bytes(b'first');second.write_bytes(b'second')
    old_page=host.select(str(first));old_url=host.origin+'/m/'+host.selection.token
    first.write_bytes(b'changed local file')
    with pytest.raises(ValueError,match='更改'):host.source_for(old_url)
    with httpx.Client(trust_env=False) as client:assert client.get(old_url).status_code==409
    host.select(str(second));assert not host.is_page(old_page)
    with httpx.Client(trust_env=False) as client:assert client.get(old_url).status_code==404
    with pytest.raises(ValueError):host.select('https://video.opencast.tum.de/test.mp4')


def test_local_observation_is_bound_to_the_exact_owned_player_page(host,tmp_path):
    path=tmp_path/'video.mp4';path.write_bytes(b'fixture')
    page=host.select(str(path));media=host.origin+'/m/'+host.selection.token
    value=dict(page=page,source=media,position=1,rate=1,paused=False,seek=False,area=300,audible=True)
    observed=observation(value,host);assert observed['source']==str(path.resolve())
    assert observed['source_identity']==list(host.selection.source.local_identity)
    with pytest.raises(ValueError):observation(value)
    with pytest.raises(ValueError):observation({**value,'source':host.origin+'/m/wrong'},host)
    with pytest.raises(ValueError):observation({**value,'page':page+'?other=true'},host)


def test_selected_local_file_uses_real_decode_and_resampling_and_changed_file_is_rejected(tmp_path):
    import wave
    path=tmp_path/'真实 音频.wav';rate=48000
    samples=np.sin(np.arange(rate*3)*2*np.pi*1000/rate)*.2
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes((samples*32767).astype('<i2').tobytes())
    source=Source.parse(str(path));metadata=probe(source);audio,stats=decode_window(source,1,2)
    assert metadata['input_rate']==rate and len(audio)==16000 and stats['rate']==16000
    assert .13<stats['rms']<.15
    spectrum=np.abs(np.fft.rfft(audio));assert abs(np.argmax(spectrum)-1000)<=1
    with pytest.raises(InterruptedError):decode_window(source,0,1,lambda:True)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='更改'):decode_window(source,0,1)


def test_stopping_subtitles_does_not_close_local_media_host(host,tmp_path):
    path=tmp_path/'course.mp4';path.write_bytes(b'actual file bytes')
    host.select(str(path));player=Player(NS());player.local_host=host;player.execute=lambda *a:None
    player._stop()
    with httpx.Client(trust_env=False) as client:assert client.get(host.origin+'/m/'+host.selection.token).content==path.read_bytes()


def test_native_media_messages_require_selected_origin_and_explicit_errors_stop_following(host,tmp_path):
    path=tmp_path/'course.mp4';path.write_bytes(b'fixture');page=host.select(str(path))
    player=Player(NS());player.local_host=host
    message={'elt':player.nonce,'frame':'a'*36,'kind':'media_error','code':4}
    player.message(None,NS(Source='http://127.0.0.1:1/foreign',WebMessageAsJson=json.dumps(message)))
    assert player.commands.empty()
    player.message(None,NS(Source=page,WebMessageAsJson=json.dumps(message)))
    assert player.commands.get_nowait()['command']=='LOCAL_ERROR'


def test_close_aborts_a_suspended_large_media_read_and_releases_socket_threads(tmp_path):
    import socket,time
    path=tmp_path/'large.mp4'
    with path.open('wb') as out:out.truncate(16*1024*1024)
    host=LocalMediaHost();host.select(str(path));peer=None
    try:
        port=host.server.server_port;peer=socket.create_connection(('127.0.0.1',port),timeout=2)
        peer.sendall((f'GET /m/{host.selection.token} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n').encode())
        assert b'200 OK' in peer.recv(1024)
        start=time.monotonic();host.close();assert time.monotonic()-start<3
        deadline=time.monotonic()+2
        while host.server.connections and time.monotonic()<deadline:time.sleep(.01)
        assert not host.server.connections and not host.thread.is_alive()
    finally:
        if peer:peer.close()
        host.close()


def test_multiple_local_audio_tracks_are_explicit_instead_of_transcribing_a_different_track(tmp_path):
    import av
    from fractions import Fraction
    path=tmp_path/'two-tracks.mp4'
    with av.open(str(path),'w') as output:
        streams=[output.add_stream('aac',rate=48000) for _ in range(2)]
        for stream in streams:stream.layout='mono'
        for stream in streams:
            for index in range(3):
                frame=av.AudioFrame.from_ndarray(np.zeros((1,1024),dtype=np.float32),format='fltp',layout='mono')
                frame.sample_rate=48000;frame.pts=index*1024;frame.time_base=Fraction(1,48000)
                for packet in stream.encode(frame):output.mux(packet)
            for packet in stream.encode(None):output.mux(packet)
    with pytest.raises(ValueError,match='多条音轨'):probe(Source.parse(str(path)))
