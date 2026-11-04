import threading
import httpx
import pytest
from experiments.lookahead.bridge import BrowserBridge,validate_media
from experiments.lookahead.server import Lab,Server


@pytest.mark.parametrize('url',['http://edge.live.rbg.tum.de/a.m3u8','https://evil.example/a.mp4',
                              'file:///secret','https://user:pw@video.opencast.tum.de/a.mp4','https://video.opencast.tum.de/watch.html'])
def test_only_normal_target_media_allowed(url):
    with pytest.raises(ValueError):validate_media(url)


def test_pair_and_origin_auth():
    b=BrowserBridge(None);r=b.pair('a'*32,{})
    assert b.authorized('a'*32,r['token'],'chrome-extension://'+'a'*32)
    assert not b.authorized('b'*32,r['token'],'chrome-extension://'+'b'*32)
    assert not b.authorized('a'*32,r['token'],'https://evil.example')
    with pytest.raises(ValueError):b.check({'owner':'expired'})


def test_preferences_are_opt_in_and_keep_only_supplied_options(tmp_path):
    import json
    saved=tmp_path/'settings.json'
    b=BrowserBridge(None,saved)
    b.pair('a'*32,{'translate':True,'narrate':True})
    assert json.loads(saved.read_text(encoding='utf-8'))=={'translate':True,'narrate':True}
    assert 'token' not in saved.read_text(encoding='utf-8')


def test_stop_invalidates_browser_session_without_waiting_for_another_clock():
    lab=Lab();bridge=BrowserBridge(lab)
    try:
        lab.session_id=bridge.session='old';bridge.owner='a'*20
        lab.stop()
        assert bridge.status()['active'] is False
        with pytest.raises(ValueError):bridge.check({'owner':'a'*20})
    finally:lab.close()


def test_preview_is_visible_before_translation_and_older_generation_is_excluded():
    lab=Lab()
    try:
        lab.preview_generation=lab.timeline.generation
        lab.preview={'a':dict(id='a',start=0,end=1,source='original',translation='',speech='')}
        assert lab.state()['cues'][0]['source']=='original'
        lab.timeline.seek(5)
        assert lab.state()['cues']==[]
    finally:lab.close()


def test_observer_timeout_does_not_depend_on_settings_page_heartbeat():
    import time
    lab=Lab();bridge=BrowserBridge(lab)
    try:
        lab.session_id='observer';bridge.session='observer';bridge.owner='a'*20
        bridge.last_clock=time.monotonic()-121;lab.last_seen=time.monotonic()
        bridge.expire()
        assert bridge.owner=='' and lab.source is None
    finally:lab.close()


def test_real_pairing_http_and_cross_site_rejection():
    lab=Lab();server=Server(lab);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with httpx.Client(base_url=server.origin,trust_env=False) as c:
            layout=c.get('/subtitle-layout.js')
            assert layout.status_code==200 and 'fitCaption' in layout.text
            ext='a'*32
            headers={'Origin':'chrome-extension://'+ext,'X-ELT-Extension-Id':ext,'X-ELT-Lab-Token':server.token}
            assert c.post('/bridge/pair',headers={**headers,'Origin':'https://evil.example'},json={'options':{}}).status_code==403
            r=c.post('/bridge/pair',headers=headers,json={'options':{}})
            assert r.status_code==200 and r.headers['access-control-allow-origin']=='chrome-extension://'+ext
            auth={'Origin':'chrome-extension://'+ext,'X-ELT-Extension-Id':ext,'X-ELT-Bridge-Token':r.json()['token']}
            assert c.get('/bridge/status',headers=auth).json()['paired'] is True
            assert c.get('/bridge/status',headers={**auth,'X-ELT-Bridge-Token':'wrong'}).status_code==403
            assert c.post('/bridge/clock',headers=auth,json={'owner':'stale'}).status_code==400
            assert c.get('/bridge/audio/0.wav?owner=stale',headers=auth).status_code==409
            assert c.post('/bridge/start',headers=auth,json={'owner':'a'*20,'source':'https://evil.example/a.mp4'}).status_code==400
            for _ in range(20):
                assert c.post('/bridge/pair',headers={'X-ELT-Lab-Token':'wrong'},json={}).status_code==403
    finally:server.shutdown();server.server_close();lab.close();thread.join(timeout=3)
