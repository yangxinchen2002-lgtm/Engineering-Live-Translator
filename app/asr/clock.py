"""One monotonic QPC clock for M1 audio, IPC jobs, inference and display.

On Windows Python 3.12, monotonic_ns is GetTickCount64 and must NOT be mixed
with WASAPI QPC. perf_counter_ns is QueryPerformanceCounter on Windows.
"""
import time


def now_ns() -> int:
    return time.perf_counter_ns()


def metadata() -> dict:
    info = time.get_clock_info('perf_counter')
    return {'implementation':info.implementation,'monotonic':info.monotonic,'resolution_seconds':info.resolution,
            'wasapi_timestamp_unit':'100 ns QPC','python_api':'perf_counter_ns'}


def validate_capture_timestamp(timestamp_100ns: int, received_ns: int) -> None:
    age = (received_ns-timestamp_100ns*100)/1e9
    if timestamp_100ns <= 0 or not -.1 <= age <= 5:
        raise ValueError(f'capture QPC epoch mismatch/stale timestamp: age={age:.6f}s')


def latency_seconds(audio_end_ns: int, displayed_ns: int) -> float:
    latency = (displayed_ns-audio_end_ns)/1e9
    if latency < -.1:
        raise ValueError(f'audio/display clock mismatch: negative latency {latency:.6f}s')
    return latency


def sample_time(spans, sample: int, rate: int = 16000) -> int:
    for start, end, timestamp in spans:
        if start <= sample <= end:
            return timestamp - (end-sample)*1_000_000_000//rate
    raise ValueError('sample clock is outside retained history')
