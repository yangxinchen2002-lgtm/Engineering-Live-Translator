from dataclasses import asdict,replace
import queue
import threading
import time
import json
from types import SimpleNamespace as NS
import httpx
import tempfile
import wave
from app.web_follow.server import Lab,Server,options_from
from app.web_follow.timeline import Cue
from app.web_follow.translation import CueTranslator
from app.web_follow.player import Player,configure_audio_playback


def test_native_player_fetches_real_wav_with_header_and_media_keeps_token_required(tmp_path):
    lab=Lab();server=Server(lab)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    lab.temp=tempfile.TemporaryDirectory(dir=tmp_path)
    name='0-1-0-1000.wav'
    from pathlib import Path
    file=Path(lab.temp.name)/name
    with wave.open(str(file),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
        wav.writeframes(b'\x01\x00'*2400)
    lab.timeline.cues=[Cue('1-0-1000',0,1,'Test.',translation='测试。',speech=name)]
    try:
        with httpx.Client(base_url=server.origin,headers={'X-ELT-Lab-Token':server.token},trust_env=False) as client:
            player=Player(NS());player.client=client
            response=player._request('/speech/'+name)
            assert response.headers['content-type']=='audio/wav'
            assert response.content==file.read_bytes()
        with httpx.Client(base_url=server.origin,trust_env=False) as client:
            assert client.get('/speech/'+name).status_code==403
            assert client.get('/speech/'+name,headers={'X-ELT-Lab-Token':'wrong'}).status_code==403
            assert client.get('/speech/'+name,params={'token':server.token}).content==file.read_bytes()
            assert client.get('/speech/0-999.wav',headers={'X-ELT-Lab-Token':server.token}).status_code==404
            assert client.get('/speech/'+name,headers={'X-ELT-Lab-Token':server.token,'Origin':'https://example.org'}).status_code==403
    finally:server.shutdown();server.server_close();lab.close();thread.join(2)


def test_real_authenticated_reading_api_updates_only_allowed_settings_without_starting_asr():
    lab=Lab();server=Server(lab,desktop_options=options_from({'translate':True,'narrate':True,'speech_engine':'qwen'}))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with httpx.Client(base_url=server.origin,headers={'X-ELT-Lab-Token':server.token},trust_env=False) as client:
            before=lab.timeline.generation
            result=client.post('/api/playback',json={'volume':33,'base_speed':1.4,'tts_model':'0.6B','tts_voice':'serena','narrate':False})
            assert result.status_code==200
            playback=result.json()['playback']
            assert playback['volume']==33 and playback['base_speed']==1.4 and not playback['narrate']
            assert lab.process is None and lab.timeline.generation==before
            assert client.post('/api/playback',json={'volume':101}).status_code==400
            assert client.post('/api/playback',json={'language':'ru'}).status_code==400
            assert lab.options['volume']==33
            revision=lab.options['speech_revision']
            result=client.post('/api/playback',json={'duck_source':True,'source_percent':35})
            assert result.status_code==200 and result.json()['playback']['source_percent']==35
            assert lab.options['duck_source'] is True and lab.options['speech_revision']==revision
            assert lab.process is None and lab.timeline.generation==before
            for invalid in ({'duck_source':1},{'source_percent':9},{'source_percent':101},{'source_percent':'20'}):
                assert client.post('/api/playback',json=invalid).status_code==400
            assert lab.options['source_percent']==35
            result=client.post('/api/playback',json={'caption_width':64,'caption_height':96,'caption_font_size':14})
            assert result.status_code==200 and result.json()['playback']['caption_width']==64
            assert result.json()['playback']['caption_height']==96 and result.json()['playback']['caption_font_size']==14
            assert lab.options['speech_revision']==revision and lab.process is None and lab.timeline.generation==before
            for invalid in ({'caption_width':29},{'caption_width':True},{'caption_height':601},{'caption_font_size':7},{'caption_font_size':'18'}):
                assert client.post('/api/playback',json=invalid).status_code==400
            assert lab.options['caption_width']==64
    finally:server.shutdown();server.server_close();lab.close();thread.join(2)


def test_close_caption_message_requires_the_active_document_identity():
    player=Player(NS());player.active_frame='a'*36
    def send(identity):
        player.message(None,NS(Source='https://live.rbg.tum.de/w/test',WebMessageAsJson=json.dumps(
            dict(elt=player.nonce,frame=identity,kind='stop'))))
    send('b'*36);assert player.commands.empty()
    send('a'*36);assert player.commands.get_nowait()['command']=='STOP'


def test_voice_change_invalidates_old_audio_without_changing_subtitle_or_asr_generation():
    lab=Lab();commands=queue.Queue(maxsize=1)
    try:
        lab.options=options_from({'translate':True,'narrate':True,'speech_engine':'qwen','tts_model':'1.7B'})
        cue=Cue('1-0-1000',1,20,'Original.',translation='原文。',speech='0-1-0-1000.wav')
        lab.timeline.cues=[cue];lab.timeline.prepared_until=25;lab.reading_commands=commands
        lab.update_playback({'tts_model':'0.6B'})
        assert lab.timeline.generation==1 and lab.timeline.prepared_until==25 and lab.timeline.cues[0].source==cue.source
        assert not lab.timeline.cues[0].speech and lab.options['speech_revision']==1
        command=commands.get_nowait();assert command['options']['tts_model']=='0.6B' and len(command['cues'])==1
        assert not lab.apply_speech(asdict(cue),0)
        assert lab.apply_speech(asdict(replace(cue,speech='1-1-0-1000.wav')),1)
        assert lab.timeline.cues[0].speech=='1-1-0-1000.wav'
    finally:lab.reading_commands=None;lab.close()


def test_switching_voice_releases_previous_model_before_creating_next(monkeypatch,tmp_path):
    from app.web_follow import tts
    instances=[];commands=queue.Queue(maxsize=1);flag=NS(value=False)
    class Speech:
        def __init__(self,options,*a):self.options=dict(options);self.closed=False;self.offers=[];instances.append(self)
        def offer(self,generation,cue):self.offers.append(cue)
        def close(self):self.closed=True
    monkeypatch.setattr(tts,'SpeechQueue',Speech)
    options=options_from({'translate':True,'narrate':False,'speech_engine':'qwen','tts_model':'1.7B'})
    translator=CueTranslator(options,NS(value=1),lambda *a,**k:None,tmp_path,narration=flag,reading_commands=commands)
    cue=Cue('1-0-1000',1,20,'Original.',translation='原文。')
    def wait(condition):
        deadline=time.monotonic()+2
        while not condition():
            if time.monotonic()>deadline:raise AssertionError('control was not applied')
            time.sleep(.01)
    try:
        translator.speech_for(1,cue);assert not instances
        flag.value=True
        commands.put({'options':{**options,'narrate':True,'speech_revision':0},'generation':1,'cues':[asdict(cue)]})
        wait(lambda:len(instances)==1 and bool(instances[0].offers))
        commands.put({'options':{**options,'tts_model':'0.6B','narrate':True,'speech_revision':1},'generation':1,'cues':[asdict(cue)]})
        wait(lambda:len(instances)==2)
        assert instances[0].closed and instances[1].options['tts_model']=='0.6B'
    finally:translator.close()
    assert instances[1].closed


def test_native_slider_changes_are_coalesced_and_do_not_enqueue_unbounded_commands():
    player=Player(NS())
    for value in range(101):player.change_playback('volume',value)
    player.change_playback('base_speed',1.1);player.change_playback('base_speed',1.4)
    assert player.commands.empty() and player.pending_playback=={'volume':100,'base_speed':1.4}


def test_autoplay_configuration_is_process_local_and_preserves_explicit_arguments(monkeypatch):
    import os
    key='WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS';monkeypatch.setenv(key,'--example-test-flag')
    configure_audio_playback();assert '--example-test-flag' in os.environ[key] and '--autoplay-policy=no-user-gesture-required' in os.environ[key]
    monkeypatch.setenv(key,'--autoplay-policy=document-user-activation-required')
    configure_audio_playback();assert os.environ[key]=='--autoplay-policy=document-user-activation-required'


def test_actual_narration_events_duck_only_the_soundtrack_frame_and_restore_after_pause():
    player=Player(NS());scripts=[]
    picture='a'*36;sound='b'*36
    player.active_frame=picture;player.clock_frame=sound;player.following=True;player.client=NS()
    player.options={'narrate':True,'duck_source':True,'source_percent':30}
    player.frames={sound:(time.monotonic(),'sound-frame',{'paused':False})}
    player.execute=lambda frame,code,identity=None:scripts.append((frame,code,identity))
    def event(name,nonce=None):
        args=NS(Source='https://live.rbg.tum.de/w/test',WebMessageAsJson=json.dumps(
            {'elt':nonce or player.nonce,'frame':picture,'kind':'playback','event':name}))
        player.message('picture-frame',args)
    event('playing')
    assert player.audio_active and len(scripts)==1 and scripts[0][0]=='sound-frame'
    assert '"percent": 30' in scripts[0][1] and '"active": true' in scripts[0][1]
    player.options['source_percent']=50;player.sync_source_volume()
    assert '"percent": 50' in scripts[-1][1]
    event('paused');assert not player.audio_active and 'active:false' in scripts[-1][1]
    assert all(row[0]=='sound-frame' for row in scripts)
    count=len(scripts);event('playing','invalid');assert len(scripts)==count


def test_source_frame_switch_and_stale_clock_restore_previous_volume_lease():
    player=Player(NS());scripts=[];player.client=NS();player.following=True;player.audio_active=True
    player.options={'narrate':True,'duck_source':True,'source_percent':20};player.clock_frame='first'
    player.execute=lambda frame,code,identity=None:scripts.append((frame,code))
    player.frames={'first':(time.monotonic(),'one',{'paused':False}),'second':(time.monotonic(),'two',{'paused':False})}
    player.sync_source_volume();player.clock_frame='second';player.sync_source_volume()
    assert scripts[1]==('one','window.__eltPlayer?.setSourceVolume({active:false})')
    assert scripts[2][0]=='two' and '"active": true' in scripts[2][1]
    player.frames['second']=(time.monotonic()-3,'two',{'paused':False});player.sync_source_volume()
    assert scripts[-1]==('two','window.__eltPlayer?.setSourceVolume({active:false})')
    assert player.source_volume_frame is None


def test_disabling_narration_or_ducking_restores_source_without_stopping_video():
    for key in ('narrate','duck_source'):
        player=Player(NS());scripts=[];player.client=NS();player.following=True;player.audio_active=True;player.clock_frame='clock'
        player.options={'narrate':True,'duck_source':True,'source_percent':20}
        player.frames={'clock':(time.monotonic(),'frame',{'paused':False})}
        player.execute=lambda frame,code,identity=None:scripts.append(code)
        player.sync_source_volume();player.options[key]=False;player.sync_source_volume()
        assert scripts[-1]=='window.__eltPlayer?.setSourceVolume({active:false})'
        assert len(scripts)==2 and not any('.pause(' in s or 'currentTime=' in s for s in scripts)
