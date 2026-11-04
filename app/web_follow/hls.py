"""Bounded, unencrypted HLS VOD manifests; authorized playback URLs stay in RAM."""
from __future__ import annotations
from app.i18n import tr as _tr
import re
from urllib.parse import urljoin, urlsplit
import httpx

MAX_MANIFEST = 2 * 1024 * 1024
HLS_MIME = 'application/vnd.apple.mpegurl'


def media_url(base: str, value: str) -> str:
    target = urljoin(base, value.strip())
    parsed = urlsplit(target)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError(_tr('HLS 资源必须使用普通 HTTP(S) 播放链接'))
    return target


def fetch_manifest(url: str) -> str:
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        with client.stream('GET', url, headers={'Accept-Encoding':'identity'}) as response:
            if response.status_code != 200:
                raise ValueError(f"{_tr('HLS 播放链接不可读取（HTTP ')}{response.status_code}{_tr('），请重新复制网站提供的播放链接')}")
            data = bytearray()
            for part in response.iter_bytes(65536):
                data.extend(part)
                if len(data) > MAX_MANIFEST:
                    raise ValueError(_tr('HLS 播放列表超过处理容量'))
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError(_tr('HLS 播放列表不是 UTF-8 文本')) from None
    check_manifest(text)
    return text


def check_manifest(text: str):
    if not text.lstrip().startswith('#EXTM3U') or len(text.encode()) > MAX_MANIFEST:
        raise ValueError(_tr('不是有效的 HLS 播放列表'))
    for line in text.splitlines():
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')) and not re.search(r'(?:^|[:,])METHOD=NONE(?:,|$)', line):
            raise ValueError(_tr('不支持加密或受保护的 HLS 内容'))


def validate_vod(url: str, *, depth=0, visited=None):
    if depth > 3:
        raise ValueError(_tr('HLS 播放列表嵌套过深'))
    visited = set() if visited is None else visited
    if url in visited:
        return
    visited.add(url)
    if len(visited) > 16:
        raise ValueError(_tr('HLS 音轨/清晰度数量超过处理容量'))
    text = fetch_manifest(url)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.startswith('#EXTINF:') for line in lines):
        if '#EXT-X-ENDLIST' not in lines:
            raise ValueError(_tr('目前只支持 HLS 点播，不支持直播'))
    else:
        children = [media_url(url, line) for line in lines if not line.startswith('#')]
        for line in lines:
            if line.startswith('#EXT-X-MEDIA:') and 'TYPE=AUDIO' in line:
                match = re.search(r'URI="([^"]+)"', line)
                if match:
                    children.append(media_url(url, match[1]))
        if not children:
            raise ValueError(_tr('HLS 播放列表中没有可用音视频'))
        for child in children:
            validate_vod(child, depth=depth+1, visited=visited)


def rewrite_manifest(text: str, base: str, register) -> str:
    """Route media through the authorized local player; never expose source URLs to logs."""
    check_manifest(text)
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            result.append(line)
        elif not line.startswith('#'):
            result.append(register(media_url(base, line)))
        else:
            result.append(re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + register(media_url(base, m[1])) + '"', line))
    return '\n'.join(result) + '\n'
