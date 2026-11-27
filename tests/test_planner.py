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
