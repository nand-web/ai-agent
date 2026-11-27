from videoagent.planner import _parse, transcript_for_prompt
from videoagent.transcript import Word


def test_parse_drops_out_of_range_indices():
    data = {
        "remove": [1, 99, -1],
        "hook_options": ["Sales DOUBLE", "", "b", "c"],
        "title": "T",
        "cta": "C",
        "reel_ranges": [{"start": 0, "end": 2}, {"start": 3, "end": 1}, {"start": 0, "end": 50}],
        "emphasis": [{"word": 2, "emoji": "🚀", "sfx": "pop"}, {"word": 40, "emoji": "x", "sfx": ""}],
        "broll": [{"start": 0, "end": 2, "query": "gym"}],
        "notes": "n",
    }
    plan = _parse(data, n=5)
    assert plan.removed == {1}
    assert plan.hook_options == ["Sales DOUBLE", "b", "c"]
    assert plan.reel_ranges == [(0, 2)]
    assert [e.word for e in plan.emphasis] == [2]
    assert plan.broll[0].query == "gym"
    assert plan.source == "claude"


def test_transcript_for_prompt_has_indices():
    words = [Word("Hello", 0, 0.4), Word("dosto.", 0.5, 0.9), Word("Aaj", 2.5, 2.8)]
    text = transcript_for_prompt(words)
    assert "0:Hello 1:dosto." in text
    assert "2:Aaj" in text.splitlines()[1]


def _words(text, t0=0.0):
    out, t = [], t0
    for tok in text.split():
        out.append(Word(tok, t, t + 0.3))
        t += 0.35
    return out


def test_retake_keeps_last_version():
    from videoagent.planner import retake_indices
    words = _words("Humne ek simple process follow kiya.") + _words("Humne ek bahut simple process follow kiya.", 10)
    removed = retake_indices(words)
    assert removed == set(range(0, 6))


def test_false_start_removed():
    from videoagent.planner import retake_indices
    words = _words("Pehle ads se.") + _words("Pehle ads se leads aayi.", 5)
    assert retake_indices(words) == {0, 1, 2}


def test_different_lines_kept():
    from videoagent.planner import retake_indices
    words = _words("Main Rahul hoon.") + _words("Humne process follow kiya.", 5)
    assert retake_indices(words) == set()


def test_prompt_marks_takes():
    words = _words("Pehli line.") + _words("Doosri line.", 20)
    text = transcript_for_prompt(words, take_starts=[0.0, 19.0])
    assert text.splitlines()[0] == "=== Take 1 ===" and "=== Take 2 ===" in text
