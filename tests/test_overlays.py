from videoagent.overlays import Overlay, build_ass, caption_events, hook_text_ass, ts
from videoagent.transcript import Word


def test_ts_format():
    assert ts(0) == "0:00:00.00"
    assert ts(65.5) == "0:01:05.50"


def test_bold_captions_one_event_per_word_and_highlight():
    words = [Word("Teen", 0.0, 0.3), Word("mahine", 0.3, 0.7), Word("mein", 0.7, 1.0), Word("double.", 1.0, 1.5)]
    ev = caption_events(words, "bold")
    assert len(ev) == 4
    assert "TEEN" in ev[0] and "\\c&H003FD2FF" in ev[0]
    # 4th word starts a new group of 3
    assert "MAHINE" not in ev[3] and "DOUBLE" in ev[3]


def test_minimal_captions_group_sentence():
    words = [Word("Teen", 0.0, 0.3), Word("mahine", 0.3, 0.7), Word("mein.", 0.7, 1.0)]
    ev = caption_events(words, "minimal")
    assert len(ev) == 1 and "Teen mahine mein" in ev[0]


def test_hook_caps_highlight():
    assert "\\c&H003FD2FF}DOUBLE" in hook_text_ass("Sales DOUBLE kaise?")


def test_build_ass_toggles():
    o = Overlay(1920, 1080, tall=False)
    words = [Word("Hello", 0.5, 1.0)]
    full = build_ass(o, 20, words=words, hook="Hi THERE", name="Rahul", title="Founder", cta="Book now")
    for style in ["Hook,", "Name,", "Role,", "CTA,", "Caption,"]:
        assert f",{style}" in full.split("[Events]")[1], style
    bare = build_ass(o, 20)
    assert "Dialogue" not in bare


def test_rule_plan_hook_has_caps_word():
    from videoagent.planner import rule_plan
    words = [Word(t, i * 0.4, i * 0.4 + 0.3) for i, t in enumerate("Teen mahine mein sales double ho gayi.".split())]
    plan = rule_plan(words)
    assert "SALES" in plan.hook_options[0]
    assert plan.reel_ranges == [(0, 6)]
