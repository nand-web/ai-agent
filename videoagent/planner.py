"""The edit plan: what the AI decides (retakes to remove, hook, reel part, emoji, B-roll).

With an Anthropic API key, Claude reads the transcript and writes the plan.
Without one (or if the call fails) a rule-based plan is used, so the tool still works free.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field

from .transcript import Word

MODEL = "claude-opus-5-5"


@dataclass
class Emphasis:
    word: int                 # word index in the raw transcript
    emoji: str = ""
    sfx: str = ""             # "pop" | "whoosh" | ""


@dataclass
class BRoll:
    start: int                # word index range it covers
    end: int
    query: str                # stock-footage search term (English)


@dataclass
class EditPlan:
    removed: set[int] = field(default_factory=set)
    hook_options: list[str] = field(default_factory=list)
    title: str = ""
    cta: str = ""
    reel_ranges: list[tuple[int, int]] = field(default_factory=list)
    emphasis: list[Emphasis] = field(default_factory=list)
    broll: list[BRoll] = field(default_factory=list)
    source: str = "rules"     # "claude" | "rules"
    notes: str = ""


# ---------------------------------------------------------------- helpers

def sentences(words: list[Word], breaks: list[float] | None = None) -> list[tuple[int, int]]:
    """Split into (first, last) word-index ranges on punctuation, long pauses and take boundaries."""
    out, start = [], 0
    cuts = sorted(breaks or [])
    for i, w in enumerate(words):
        end_punct = w.text.endswith((".", "?", "!", "।"))
        long_gap = i + 1 < len(words) and words[i + 1].start - w.end > 0.9
        take_break = i + 1 < len(words) and any(w.start < b <= words[i + 1].start for b in cuts)
        if end_punct or long_gap or take_break or i == len(words) - 1:
            out.append((start, i))
            start = i + 1
    return out


def _text(words: list[Word], a: int, b: int) -> str:
    return " ".join(w.text for w in words[a : b + 1])


EMOJI_KEYWORDS = {
    "📈": ["sales", "growth", "grow", "badh", "increase", "badha"],
    "🚀": ["double", "2x", "guna", "fast", "launch", "boost"],
    "💰": ["paisa", "paise", "money", "profit", "revenue", "kamai", "rupees", "lakh", "crore"],
    "😊": ["happy", "khush", "satisfied", "mazaa", "maza"],
    "🔥": ["best", "amazing", "zabardast", "kamaal", "awesome"],
    "💡": ["idea", "tip", "process", "tarika", "solution"],
    "🤝": ["team", "support", "help", "madad", "saath"],
    "⏰": ["time", "waqt", "jaldi", "turant", "minute", "mahine", "months"],
    "❤️": ["love", "pyaar", "pasand", "recommend"],
    "😟": ["problem", "dikkat", "pareshani", "issue", "mushkil"],
    "✅": ["result", "done", "ho gaya", "success", "safal"],
}

HOOK_WORDS = ["double", "guna", "%", "result", "best", "lakh", "crore", "sales", "growth", "kaise", "how", "secret"]


def _score_sentence(text: str) -> int:
    t = text.lower()
    return sum(2 for k in HOOK_WORDS if k in t) + len(re.findall(r"\d", t))


# ---------------------------------------------------------------- retakes

def _tokens(words: list[Word], a: int, b: int) -> list[str]:
    return [re.sub(r"[^\w]", "", w.text.lower()) for w in words[a : b + 1] if re.sub(r"[^\w]", "", w.text)]


def retake_indices(words: list[Word], lookahead: int = 4, take_starts: list[float] | None = None) -> set[int]:
    """Find lines that are said again later (another take, or a false start).

    A sentence is dropped when most of its words come back, in order, in one of the
    next few sentences; the later take is kept because it is usually the cleaner one.
    """
    sents = sentences(words, take_starts)
    removed: set[int] = set()
    for i, (a, b) in enumerate(sents):
        if a in removed:
            continue
        mine = _tokens(words, a, b)
        if len(mine) < 2:
            continue
        for c, d in sents[i + 1 : i + 1 + lookahead]:
            if c in removed:
                continue
            other = _tokens(words, c, d)
            if not other:
                continue
            m = difflib.SequenceMatcher(None, mine, other, autojunk=False)
            matched = sum(bl.size for bl in m.get_matching_blocks())
            starts_same = other[:2] == mine[:2]
            if matched / len(mine) >= 0.75 and (starts_same or len(mine) >= 4):
                removed.update(range(a, b + 1))   # said again later: keep the later take
                break
            if len(other) >= 3 and len(other) < len(mine) and matched / len(other) >= 0.9:
                removed.update(range(c, d + 1))   # later line is only a piece of this one
    return removed


# ---------------------------------------------------------------- rule-based plan

def rule_plan(words: list[Word], reel_max: float = 60.0, take_starts: list[float] | None = None) -> EditPlan:
    plan = EditPlan(source="rules")
    plan.removed = retake_indices(words, take_starts=take_starts)
    sents = sentences(words, take_starts)
    if not sents:
        return plan

    sents = [s for s in sents if s[0] not in plan.removed] or sents
    best = max(sents, key=lambda s: _score_sentence(_text(words, *s)))
    hook_words = _text(words, *best).split()[:9]
    for k, w in enumerate(hook_words):  # put the key word in CAPS so it gets highlighted
        low = w.lower()
        if any(h in low for h in HOOK_WORDS if h != "kaise") or re.search(r"\d", low):
            hook_words[k] = w.upper()
            break
    plan.hook_options = [" ".join(hook_words).rstrip(".,")]

    # Reel: the densest window (by sentence score) up to reel_max seconds.
    best_window, best_score = (sents[0][0], sents[0][1]), -1
    for i in range(len(sents)):
        score, j = 0, i
        while j < len(sents) and words[sents[j][1]].end - words[sents[i][0]].start <= reel_max:
            score += _score_sentence(_text(words, *sents[j])) + 1
            j += 1
        if j > i and score > best_score:
            best_score, best_window = score, (sents[i][0], sents[j - 1][1])
    plan.reel_ranges = [best_window]

    used: set[str] = set()
    last_t = -10.0
    for i, w in enumerate(words):
        if i in plan.removed:
            continue
        low = w.text.lower()
        for emoji, keys in EMOJI_KEYWORDS.items():
            if emoji not in used and any(k in low for k in keys) and w.start - last_t > 4:
                plan.emphasis.append(Emphasis(i, emoji, "pop"))
                used.add(emoji)
                last_t = w.start
                break
    return plan


# ---------------------------------------------------------------- Claude plan

SYSTEM = """You are a senior video editor who cuts talking-head testimonials and vlogs
for YouTube and Instagram Reels. Speakers talk in Hindi, English or Hinglish.
You get a transcript where every word has an index. Decide the edit:

- remove: word indices of false starts, repeated takes, broken sentences and
  verbal fillers ("umm", "aaa", "matlab matlab", "toh basically" used as filler).
  When a line is said twice, keep the better (usually the last) take.
  Never remove words that carry meaning.
- hook_options: 3 short on-screen hook lines (max 8 words) for the first 3 seconds,
  in the speaker's language style. Put the single most important word in CAPS.
- title: a YouTube title.
- cta: a short call-to-action for the end card.
- reel_ranges: word-index ranges (inclusive) that together make the strongest
  self-contained 30-60 second reel. Start with the most striking line.
- emphasis: up to one moment every 5-8 seconds where an emoji pop-up helps
  (key result, emotion, number). sfx is "pop" for emoji, "whoosh" for a topic change.
- broll: moments where a stock clip would help the viewer see what is said
  (a gym, a phone chat, money, an office). query is a short English search term.
  At most one B-roll per 15 seconds, 2-5 seconds long each. Skip it for emotional lines
  where the face matters.
- notes: one or two sentences explaining the edit.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "remove": {"type": "array", "items": {"type": "integer"}},
        "hook_options": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
        "cta": {"type": "string"},
        "reel_ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
                "required": ["start", "end"],
                "additionalProperties": False,
            },
        },
        "emphasis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "integer"},
                    "emoji": {"type": "string"},
                    "sfx": {"type": "string", "enum": ["pop", "whoosh", ""]},
                },
                "required": ["word", "emoji", "sfx"],
                "additionalProperties": False,
            },
        },
        "broll": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "query": {"type": "string"},
                },
                "required": ["start", "end", "query"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["remove", "hook_options", "title", "cta", "reel_ranges", "emphasis", "broll", "notes"],
    "additionalProperties": False,
}


def transcript_for_prompt(words: list[Word], take_starts: list[float] | None = None) -> str:
    lines = []
    takes = list(take_starts or [])[1:]
    take_no = 1
    if take_starts and len(take_starts) > 1:
        lines.append("=== Take 1 ===")
    for a, b in sentences(words, take_starts):
        while takes and words[a].start >= takes[0]:
            takes.pop(0)
            take_no += 1
            lines.append(f"=== Take {take_no} ===")
        body = " ".join(f"{i}:{words[i].text}" for i in range(a, b + 1))
        lines.append(f"[{words[a].start:6.1f}s] {body}")
    return "\n".join(lines)


def _parse(data: dict, n: int) -> EditPlan:
    ok = lambda i: isinstance(i, int) and 0 <= i < n  # noqa: E731
    plan = EditPlan(source="claude")
    plan.removed = {i for i in data.get("remove", []) if ok(i)}
    plan.hook_options = [h for h in data.get("hook_options", []) if h.strip()][:3]
    plan.title = data.get("title", "")
    plan.cta = data.get("cta", "")
    plan.reel_ranges = [
        (r["start"], r["end"]) for r in data.get("reel_ranges", []) if ok(r["start"]) and ok(r["end"]) and r["end"] >= r["start"]
    ]
    plan.emphasis = [Emphasis(e["word"], e.get("emoji", ""), e.get("sfx", "")) for e in data.get("emphasis", []) if ok(e["word"])]
    plan.broll = [
        BRoll(b["start"], b["end"], b["query"]) for b in data.get("broll", []) if ok(b["start"]) and ok(b["end"]) and b["end"] >= b["start"]
    ]
    plan.notes = data.get("notes", "")
    return plan


def claude_plan(words: list[Word], reel_max: float = 60.0, take_starts: list[float] | None = None) -> EditPlan:
    import anthropic

    client = anthropic.Anthropic()
    takes_note = ""
    if take_starts and len(take_starts) > 1:
        takes_note = (
            f"The recording is {len(take_starts)} separate takes joined in order (marked below). "
            "Takes often repeat the same lines: keep the best version of each line once, "
            "and remove the other versions completely.\n"
        )
    user = (
        f"Reel should be at most {int(reel_max)} seconds.\n{takes_note}"
        f"Transcript ({len(words)} words, format index:word):\n\n{transcript_for_prompt(words, take_starts)}"
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to plan this video")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Plan was cut off (video too long for one request)")
    text = next(b.text for b in response.content if b.type == "text")
    return _parse(json.loads(text), len(words))


def have_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_plan(words: list[Word], *, use_ai: bool = True, reel_max: float = 60.0, take_starts: list[float] | None = None, log=print) -> EditPlan:
    if use_ai and have_api_key():
        try:
            plan = claude_plan(words, reel_max, take_starts)
            log(f"AI plan ready: {len(plan.removed)} words removed, {len(plan.broll)} B-roll, {len(plan.emphasis)} emoji")
            return plan
        except Exception as e:  # network, auth, refusal: fall back so the edit still happens
            log(f"AI plan failed ({e}); using rule-based plan")
    elif use_ai:
        log("No ANTHROPIC_API_KEY set; using rule-based plan")
    plan = rule_plan(words, reel_max, take_starts)
    if plan.removed:
        log(f"Removed {len(plan.removed)} words of repeated takes / false starts")
    return plan
