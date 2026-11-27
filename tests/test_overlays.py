from pathlib import Path

from PIL import Image

from videoagent.overlays import TextRenderer, build_events, caption_events, render_text_track
from videoagent.transcript import Word


def test_bold_captions_one_event_per_word_and_highlight():
    words = [Word("Teen", 0.0, 0.3), Word("mahine", 0.3, 0.7), Word("mein", 0.7, 1.0), Word("double.", 1.0, 1.5)]
    ev = caption_events(words, "bold")
    assert len(ev) == 4
    assert ev[0].words == ["TEEN", "MAHINE", "MEIN"] and ev[0].highlight == 0 and ev[0].pop
    assert ev[3].words == ["DOUBLE"]


def test_minimal_captions_group_sentence():
    words = [Word("Teen", 0.0, 0.3), Word("mahine", 0.3, 0.7), Word("mein.", 0.7, 1.0)]
    ev = caption_events(words, "minimal")
    assert len(ev) == 1 and ev[0].words == ["Teen", "mahine", "mein"]


def test_build_events_toggles():
    words = [Word("Hello", 0.5, 1.0)]
    full = build_events(20, words=words, hook="Hi THERE", name="Rahul", title="Founder", cta="Book now")
    assert {e.kind for e in full} == {"hook", "name", "cta", "caption"}
    assert build_events(20) == []


def test_sprites_fit_in_frame():
    for W, H in [(1920, 1080), (1080, 1920)]:
        r = TextRenderer(W, H)
        evs = build_events(20, words=[Word(w, i * 0.3, i * 0.3 + 0.25) for i, w in enumerate("bahut lamba shabd zabardast".split())],
                           hook="Sales 3 mahine mein DOUBLE kaise hui yeh dekho", name="Rahul Mehta", title="Founder, FitBox Gym",
                           cta="Free consultation book karein")
        for ev in evs:
            img, x, y = r.sprite(ev)
            assert img.getbbox() is not None
            assert 0 <= x and x + img.width <= W and 0 <= y and y + img.height <= H, ev.kind


def test_text_track_durations_cover_video(tmp_path: Path):
    words = [Word("Teen", 0.5, 0.8), Word("mahine", 0.8, 1.2)]
    evs = build_events(6.0, words=words, hook="Hi THERE", cta="Book")
    lst = render_text_track(evs, 640, 360, 6.0, 30, tmp_path)
    lines = lst.read_text().splitlines()
    total = sum(float(l.split()[1]) for l in lines if l.startswith("duration"))
    assert abs(total - 6.0) < 1e-3
    first = tmp_path / lines[0].split("'")[1]
    assert Image.open(first).mode == "RGBA"


def test_overlays_do_not_collide():
    """Hook stays clear of the logo corner; name card stays above the captions."""
    from videoagent.overlays import TextEvent
    for W, H in [(1920, 1080), (1080, 1920)]:
        r = TextRenderer(W, H)
        hook, hx, hy = r.sprite(TextEvent(0, 3, "hook", "Teen mahine mein hamari SALES double ho gayi".split()))
        if W > H:
            assert hx + hook.width < W * 0.86          # logo starts at about 0.87 W
        name, nx, ny = r.sprite(TextEvent(0, 3, "name", ["Rahul Mehta"], later=["Founder, FitBox Gym"]))
        cap, cx, cy = r.sprite(TextEvent(0, 1, "caption", ["PROCESS", "FOLLOW", "KIYA"], highlight=0))
        assert ny + name.height < cy, (W, H)
        assert hy + hook.height < H * 0.33, (W, H)
