import math
import pytest
from experiments.lookahead.timeline import Cue, Timeline, active_cue, finite


@pytest.mark.parametrize('value', [True, None, '1', math.nan, math.inf, -1, 86401])
def test_clock_rejects_invalid_numbers(value):
    with pytest.raises(ValueError):
        finite(value, 0, 86400)


def test_seek_discards_old_results_and_prepares_new_position():
    timeline = Timeline()
    old = timeline.generation
    assert timeline.plan() == (0, 15)
    timeline.seek(50)
    assert not timeline.commit(old, 0, 15, [Cue('old', 1, 2, 'old')])
    assert timeline.cues == []
    assert timeline.plan() == (50, 65)
    assert timeline.commit(timeline.generation, 50, 65, [Cue('new', 51, 53, 'new')])


def test_audio_silence_is_prepared_without_fabricated_subtitles():
    timeline = Timeline()
    timeline.commit(1, 0, 15, [])
    assert timeline.prepared_until == 15
    assert timeline.cues == []
    assert timeline.plan() is None
    timeline.position = 5
    assert timeline.plan() == (15, 20)


def test_end_of_media_is_bounded():
    timeline = Timeline()
    timeline.duration = 4
    assert timeline.plan() == (0, 4)
    timeline.commit(1, 0, 4, [])
    assert timeline.plan() is None


def test_heartbeat_does_not_schedule_tiny_asr_windows():
    timeline = Timeline()
    timeline.commit(1, 0, 15, [])
    for position in [.4, .8, 1.2, 2.4, 4.8]:
        timeline.position = position
        assert timeline.plan() is None
    timeline.position = 5.2
    assert timeline.plan() == (15, 20.2)


def test_clock_selects_cue_not_arrival_or_length():
    cues = [Cue('long', 1, 8, 'long'), Cue('short', 8, 9, 'short')]
    assert active_cue(cues, 7.9).id == 'long'
    assert active_cue(cues, 8).id == 'short'
    assert active_cue(cues, 9) is None


def test_discontinuous_preparation_is_error():
    with pytest.raises(ValueError, match='non-contiguous'):
        Timeline().commit(1, 4, 8, [])


def test_cue_capacity_never_silently_drops_future_sentences():
    timeline = Timeline()
    cues = [Cue(str(i), i / 10, i / 10 + .05, 'x') for i in range(97)]
    with pytest.raises(ValueError, match='capacity'):
        timeline.commit(1, 0, 15, cues)
    assert timeline.prepared_until == 0


