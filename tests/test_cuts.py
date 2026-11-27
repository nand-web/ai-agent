from videoagent.cuts import Segment, Timeline, filler_indices, is_filler, keep_segments, restrict
from videoagent.transcript import Word


def W(text, s, e):
    return Word(text, s, e)


def test_is_filler():
    for f in ["umm", "Umm,", "uh", "aaa", "hmm", "erm"]:
        assert is_filler(f), f
    for w in ["matlab", "aap", "a", "hum", "main"]:
        assert not is_filler(w), w


def test_filler_is_cut_out():
    words = [W("Hello", 0.0, 0.5), W("umm", 0.6, 1.0), W("dosto", 1.1, 1.6)]
    segs = keep_segments(words, filler_indices(words), duration=2.0)
    assert len(segs) == 2
    assert segs[0].end <= 0.6   # never reaches into the filler
    assert segs[1].start >= 1.0


def test_long_pause_is_shortened():
    words = [W("Ek", 0.0, 0.4), W("do", 3.0, 3.4)]
    segs = keep_segments(words, set(), duration=4.0, max_pause=0.45, pad=0.18)
    assert len(segs) == 2
    total = sum(s.dur for s in segs)
    assert total < 1.6


def test_short_pause_kept_together():
    words = [W("Ek", 0.0, 0.4), W("do", 0.6, 1.0)]
    segs = keep_segments(words, set(), duration=2.0)
    assert len(segs) == 1


def test_no_pause_cutting_keeps_silence():
    words = [W("Ek", 1.0, 1.4), W("do", 3.0, 3.4)]
    segs = keep_segments(words, set(), duration=4.0, cut_pauses=False)
    assert len(segs) == 1
    assert segs[0].dur > 2.0


def test_timeline_maps_times():
    tl = Timeline([Segment(0, 1), Segment(3, 4)])
    assert tl.duration == 2
    assert tl.to_edited(0.5) == 0.5
    assert tl.to_edited(2.0) is None
    assert tl.to_edited(3.5) == 1.5


def test_timeline_words_drop_cut_words():
    words = [W("a1", 0.1, 0.4), W("cut", 1.5, 1.8), W("b1", 3.2, 3.6)]
    tl = Timeline([Segment(0, 1), Segment(3, 4)])
    out = tl.words(words)
    assert [i for i, _ in out] == [0, 2]
    assert abs(out[1][1].start - 1.2) < 1e-9


def test_restrict():
    segs = [Segment(0, 5), Segment(6, 10)]
    r = restrict(segs, [(4, 7)])
    assert [(s.start, s.end) for s in r] == [(4, 5), (6, 7)]
