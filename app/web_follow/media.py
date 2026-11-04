"""Actual seek/decode/resampling; direct media only, never rendered loopback."""
from __future__ import annotations
from app.i18n import tr as _tr

from contextlib import contextmanager
from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import av
import httpx
import numpy as np

RATE = 16000
HLS_TIMESTAMP_HOLE_LIMIT = round(RATE * .0005)  # 0.5 ms, never a packet-sized gap.
EXTENSIONS = {'.mp4', '.m4v', '.webm', '.mov', '.mp3', '.wav', '.m4a', '.ogg'}


def file_identity(stat):
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns


def repair_rounding(audio: np.ndarray, covered: np.ndarray, *, max_hole_samples: int = 2) -> dict:
    if type(max_hole_samples) is not int or not 2<=max_hole_samples<=HLS_TIMESTAMP_HOLE_LIMIT:
        raise ValueError('invalid timestamp repair limit')
    missing = np.flatnonzero(~covered)
    largest = max((len(run) for run in np.split(missing, np.flatnonzero(np.diff(missing) > 1) + 1)), default=0)
    if missing.size:
        # Local files retain the strict 2-sample rounding bound. HLS may have <=0.5 ms
        # interior timestamp jitter; require known samples on both sides and
        # retain the same cumulative budget of at most 2 samples per second.
        unbounded_edge=max_hole_samples>2 and (missing[0]==0 or missing[-1]==audio.size-1)
        if largest > max_hole_samples or missing.size > max(2, int(np.ceil(audio.size / RATE * 2))) or unbounded_edge:
            raise ValueError(f'audio timeline has {missing.size} missing samples (largest gap {largest}, first at {missing[0]/RATE:.3f}s); preparation stopped')
        known = np.flatnonzero(covered)
        if not known.size:
            raise ValueError('audio timeline has no valid samples')
        audio[missing] = np.interp(missing, known, audio[known])
    return dict(missing_samples=int(missing.size), rounding_repaired_samples=int(missing.size), largest_gap_samples=largest,
                timestamp_hole_limit_samples=max_hole_samples)


@dataclass(frozen=True)
class Source:
    value: str
    remote: bool
    mime: str
    local_identity: tuple[int,int,int,int] | None = None

    def check_local(self,stat):
        if self.local_identity is not None and file_identity(stat)!=self.local_identity:
            raise ValueError(_tr('本地媒体文件已更改，请重新打开文件'))

    @property
    def hls(self):
        return self.remote and urlsplit(self.value).path.lower().endswith('.m3u8')

    @classmethod
    def parse(cls, value: str):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 4096:
            raise ValueError(_tr('请输入本机媒体文件路径或直达媒体链接'))
        value = value.strip().strip('"')
        url = urlsplit(value)
        if url.scheme.lower() in ('http', 'https'):
            if not url.hostname or url.username or url.password or url.fragment:
                raise ValueError(_tr('媒体链接不能包含账户密码或片段'))
            return cls(value, True, mimetypes.guess_type(url.path)[0] or 'video/mp4')
        if '://' in value or value.lower().startswith(('blob:', 'data:')):
            raise ValueError(_tr('仅支持 HTTP(S) 直达媒体和本机文件；不支持 blob、网页地址或播放列表'))
        path = Path(value).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError(_tr('不支持的本机媒体格式'))
        return cls(str(path), False, mimetypes.guess_type(path.name)[0] or 'application/octet-stream',file_identity(path.stat()))

    def preflight(self):
        if not self.remote:
            return
        if self.hls:
            from .hls import validate_vod
            validate_vod(self.value)
            return
        # Closing a streaming response avoids downloading the entire course.
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', self.value, headers={'Range': 'bytes=0-0', 'Accept-Encoding': 'identity'}) as r:
                if (r.status_code != 206 or not re.fullmatch(r'bytes 0-0/[1-9][0-9]*', r.headers.get('content-range', ''))
                        or 'text/html' in r.headers.get('content-type', '')
                        or 'mpegurl' in r.headers.get('content-type', '')):
                    raise ValueError(_tr('链接必须直接返回支持 Range 的媒体；不支持网页、跳转、登录或 HLS/DASH 播放列表'))


@contextmanager
def open_media(source: Source):
    options = {'protocol_whitelist': 'http,https,tcp,tls' if source.remote else 'file',
               'rw_timeout': '10000000'}
    with av.logging.Capture(local=False) as logs:
        try:
            if source.remote:
                with av.open(source.value, options=options, timeout=(10., 10.)) as container:
                    yield container
            else:
                with Path(source.value).open('rb') as handle:
                    source.check_local(os.fstat(handle.fileno()))
                    with av.open(handle, options=options, timeout=(10., 10.)) as container:
                        yield container
                    source.check_local(os.fstat(handle.fileno()))
        except InterruptedError:
            raise
        except av.FFmpegError as error:
            detail = ' '.join(item[2] for item in logs[-2:])
            detail = detail.replace(source.value, _tr('[播放链接]'))
            detail = re.sub(r'(?:https?|file|crypto):\S+', _tr('[资源链接]'), detail)
            detail = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', _tr('[访问令牌]'), detail)
            raise ValueError(f"{_tr('音轨读取失败（')}{error.errno}，{error.strerror}）：{detail[:400]}") from None
        except OSError:
            raise ValueError(_tr('媒体无法读取，请检查文件是否已移动、删除或被占用')) from None


def probe(source: Source) -> dict:
    source.preflight()
    with open_media(source) as c:
        if not c.streams.audio:
            raise ValueError(_tr('媒体没有可读取的音轨'))
        if not source.remote and len(c.streams.audio)>1:
            raise ValueError(_tr('本地视频包含多条音轨；当前请使用单音轨文件，或使用 VLC 应用音频模式选择音轨'))
        if c.duration is None or not 0 < c.duration / av.time_base <= 86400:
            raise ValueError(_tr('需要时长明确、可定位的点播媒体；不支持直播'))
        stream = c.streams.audio[0]
        return dict(duration=c.duration / av.time_base, input_rate=stream.codec_context.sample_rate,
                    input_channels=stream.codec_context.channels, has_video=bool(c.streams.video),
                    container_start_seconds=(c.start_time or 0) / av.time_base,
                    audio_start_seconds=float(stream.start_time * stream.time_base) if stream.start_time is not None else None)


def decode_window(source: Source, begin: float, end: float, cancelled=lambda: False) -> tuple[np.ndarray, dict]:
    if not 0 <= begin < end <= begin + 31:
        raise ValueError('invalid audio decode window')
    count = round((end - begin) * RATE)
    audio = np.zeros(count, dtype=np.float32)
    covered = np.zeros(count, dtype=bool)
    with open_media(source) as c:
        stream = c.streams.audio[0]
        origin = (c.start_time or 0) / av.time_base
        preroll = 6. if source.hls else 1.
        if begin > preroll:
            try:
                # Seek in the selected audio stream, not the default video keyframes.
                # HLS needs a complete prior segment to avoid landing after the requested start.
                c.seek(round((origin + begin - preroll) / float(stream.time_base)),
                       stream=stream, backward=True, any_frame=True)
            except av.FFmpegError as error:
                raise ValueError(f"{_tr('音轨定位失败（')}{error.errno}，{error.strerror}）") from None
        resampler = av.AudioResampler(format='fltp', layout='mono', rate=RATE)
        planar = av.AudioResampler(format='fltp', layout=stream.codec_context.layout,
                                  rate=stream.codec_context.sample_rate)
        channel_energy = np.zeros(stream.codec_context.channels, dtype=np.float64)
        channel_samples = 0
        discarded_priming_frames = 0
        seen_timestamp = False
        def consume(frame):
            if frame.pts is None:
                raise ValueError('audio frame has no timestamp')
            at = round((float(frame.pts * frame.time_base) - origin - begin) * RATE)
            samples = frame.to_ndarray().reshape(-1)
            left, right = max(0, at), min(count, at + samples.size)
            if right > left:
                audio[left:right] = samples[left - at:right - at]
                covered[left:right] = True
        def downmix(frame):
            nonlocal channel_samples
            # FFmpeg's default stereo->mono matrix adds +3 dB for identical channels.
            # Use an explicit arithmetic mean so ASR normalization preserves amplitude.
            channels = frame.to_ndarray()
            channel_energy[:] += np.sum(channels.astype(np.float64) ** 2, axis=1)
            channel_samples += channels.shape[1]
            values = channels.mean(axis=0, dtype=np.float32)[None, :]
            mono = av.AudioFrame.from_ndarray(values, format='fltp', layout='mono')
            mono.sample_rate, mono.pts, mono.time_base = frame.sample_rate, frame.pts, frame.time_base
            for f in resampler.resample(mono):
                consume(f)
        for frame in c.decode(stream):
            if cancelled():
                raise InterruptedError('generation changed')
            if frame.pts is None:
                if seen_timestamp or discarded_priming_frames >= 64:
                    raise ValueError('audio timestamp unavailable')
                # AAC can emit unpositioned decoder priming after a seek. Discard
                # only these initial frames; sample coverage must still prove the
                # complete requested window was subsequently decoded.
                discarded_priming_frames += 1
                continue
            seen_timestamp = True
            if float(frame.pts * frame.time_base) - origin > end + .15:
                break
            for f in planar.resample(frame):
                downmix(f)
            if covered.size and covered[-1]:
                break
        for f in planar.resample(None):
            downmix(f)
        for f in resampler.resample(None):
            consume(f)
    gaps = repair_rounding(audio, covered,max_hole_samples=HLS_TIMESTAMP_HOLE_LIMIT if source.hls else 2)
    if not np.isfinite(audio).all():
        raise ValueError('non-finite audio samples')
    return audio, dict(samples=count, rate=RATE, **gaps,
                       discarded_priming_frames=discarded_priming_frames,
                       channel_rms=np.sqrt(channel_energy / max(1, channel_samples)).tolist(),
                       rms=float(np.sqrt(np.mean(audio ** 2))), peak=float(np.max(np.abs(audio))))


def byte_range(value: str | None, size: int) -> tuple[int, int]:
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not any(match.groups()):
        raise ValueError('invalid range')
    first, last = match.groups()
    if first:
        start, end = int(first), int(last) if last else size - 1
    else:
        length = int(last)
        if length < 1:
            raise ValueError('invalid suffix range')
        start, end = max(0, size - length), size - 1
    if not 0 <= start <= end or start >= size:
        raise ValueError('unsatisfiable range')
    return start, min(end, size - 1)
