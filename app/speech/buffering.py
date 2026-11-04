"""Audio-only reserve for streaming synthesis under variable inference load."""


def required_audio_reserve(produced_seconds,elapsed_seconds,text_length,speed,*,recent_rtf=0,jitter_seconds=.5):
    """Raw audio needed before starting at the requested playback tempo.

    When synthesis is slower than playback, reserve its projected shortfall
    over this utterance plus a small margin. This does not change text or tempo.
    A completed utterance bypasses this estimate in the controller.
    """
    minimum=max(1.2,jitter_seconds)*speed
    if produced_seconds<=0 or elapsed_seconds<=0:return minimum
    duration=max(produced_seconds,text_length/3.5)
    rate=max(recent_rtf,elapsed_seconds/produced_seconds)
    shortfall=duration*max(0,1-1/(rate*speed))
    return max(minimum,shortfall+jitter_seconds*speed)
