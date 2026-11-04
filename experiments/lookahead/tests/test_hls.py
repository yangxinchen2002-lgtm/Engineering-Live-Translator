import pytest
from experiments.lookahead.hls import check_manifest, media_url, rewrite_manifest, validate_vod
from experiments.lookahead.media import Source


def test_hls_source_and_signed_link_are_supported_without_exporting_credentials():
    source = Source.parse('https://media.example/course/index.m3u8?jwt=test-only')
    assert source.hls


@pytest.mark.parametrize('method', ['AES-128', 'SAMPLE-AES', 'SAMPLE-AES-CTR'])
def test_protected_media_rejected(method):
    with pytest.raises(ValueError, match='加密'):
        check_manifest('#EXTM3U\n#EXT-X-KEY:METHOD='+method+',URI="key"\n')


def test_playlist_resources_rewritten_not_disclosed_to_browser():
    urls = []
    def register(url):
        urls.append(url)
        return '/hls/'+str(len(urls))
    result = rewrite_manifest('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\nsegment.ts?jwt=test-only\n#EXT-X-ENDLIST\n',
                              'https://media.example/path/vod.m3u8?jwt=test-only', register)
    assert 'jwt=' not in result and 'https://' not in result
    assert 'URI="/hls/1"' in result and '\n/hls/2\n' in result
    assert urls[1] == 'https://media.example/path/segment.ts?jwt=test-only'


@pytest.mark.parametrize('url', ['file:///secret', 'crypto:https://example/key', 'data:xx', 'https://u:p@x/a'])
def test_invalid_resource_protocols_rejected(url):
    with pytest.raises(ValueError):
        media_url('https://media.example/master.m3u8', url)


def test_vod_master_and_audio_validation(monkeypatch):
    fixtures = {'https://x/master.m3u8':'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nvideo.m3u8\n',
                'https://x/audio.m3u8':'#EXTM3U\n#EXTINF:6,\na.aac\n#EXT-X-ENDLIST\n',
                'https://x/video.m3u8':'#EXTM3U\n#EXTINF:6,\nv.ts\n#EXT-X-ENDLIST\n'}
    monkeypatch.setattr('experiments.lookahead.hls.fetch_manifest', lambda url: fixtures[url])
    validate_vod('https://x/master.m3u8')
    fixtures['https://x/audio.m3u8'] = '#EXTM3U\n#EXTINF:6,\na.aac\n'
    with pytest.raises(ValueError, match='直播'):
        validate_vod('https://x/master.m3u8')
