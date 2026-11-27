"""Decide which parts of the raw video to keep, and map raw times to edited times."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .transcript import Word

_FILLER_RE = re.compile(r"^(u+m+|u+h+|a+h+|a{2,}|h+m+|e+r+m*|e+h+|mm+|umm+)$")


def _norm(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower())


def is_filler(text: str) -> bool:
    return bool(_FILLER_RE.match(_norm(text)))


def filler_indices(words: list[Word]) -> set[int]:
    return {i for i, w in enumerate(words) if is_filler(w.text)}


@dataclass
class Segment:
    start: float  # raw-video seconds
    end: float

    @property
    def dur(self) -> float:
        return self.end - self.start


def keep_segments(
    words: list[Word],
    removed: set[int],
    duration: float,
    *,
    cut_pauses: bool = True,
    max_pause: float = 0.45,
    pad: float = 0.18,
    min_len: float = 0.12,
) -> list[Segment]:
    """Build the list of raw-time ranges to keep.

    A new segment starts whenever a removed word sits between two kept words,
    or (when cut_pauses) the silence between them is longer than max_pause.
    Each segment keeps `pad` seconds of air around speech but never reaches
    into a removed word.
    """
    kept = [i for i in range(len(words)) if i not in removed]
    if not kept:
        return []

    groups: list[list[int]] = [[kept[0]]]
    for prev, cur in zip(kept, kept[1:]):
        gap = words[cur].start - words[prev].end
        removed_between = cur - prev > 1
        if removed_between or (cut_pauses and gap > max_pause):
            groups.append([cur])
        else:
            groups[-1].append(cur)

    segs: list[Segment] = []
    for g in groups:
        first, last = g[0], g[-1]
        lo = 0.0 if first == 0 else words[first - 1].end
        hi = duration if last == len(words) - 1 else words[last + 1].start
        # Without pause cutting, keep the natural silence up to a removed word / video edge.
        start = max(lo, words[first].start - pad)
        end = min(hi, words[last].end + pad)
        if first - 1 >= 0 and (first - 1) not in removed and not cut_pauses:
            start = lo
        start, end = max(0.0, start), min(duration, end)
        if end - start >= min_len:
            segs.append(Segment(start, end))

    merged: list[Segment] = []
    for s in segs:
        if merged and s.start <= merged[-1].end + 1e-3:
            merged[-1].end = max(merged[-1].end, s.end)
        else:
            merged.append(Segment(s.start, s.end))
    return merged


def restrict(segs: list[Segment], ranges: list[tuple[float, float]]) -> list[Segment]:
    """Intersect keep segments with raw-time ranges (used to build the reel)."""
    out: list[Segment] = []
    for a, b in ranges:
        for s in segs:
            lo, hi = max(a, s.start), min(b, s.end)
            if hi - lo > 0.05:
                out.append(Segment(lo, hi))
    out.sort(key=lambda s: s.start)
    return out


class Timeline:
    """Maps raw-video times onto the edited (cut) video."""

    def __init__(self, segs: list[Segment]):
        self.segs = segs
        self.offsets: list[float] = []
        acc = 0.0
        for s in segs:
            self.offsets.append(acc)
            acc += s.dur
        self.duration = acc

    def to_edited(self, t: float) -> float | None:
        for s, off in zip(self.segs, self.offsets):
            if s.start - 1e-6 <= t <= s.end + 1e-6:
                return off + (min(max(t, s.start), s.end) - s.start)
        return None

    def words(self, words: list[Word]) -> list[tuple[int, Word]]:
        """Return (original index, word in edited time) for every word that survives the cut."""
        out = []
        for i, w in enumerate(words):
            mid = (w.start + w.end) / 2
            if self.to_edited(mid) is None:
                continue
            s = self.to_edited(w.start)
            e = self.to_edited(w.end)
            if s is None:
                s = self.to_edited(mid)
            if e is None:
                e = self.to_edited(mid)
            out.append((i, Word(w.text, s, max(e, s + 0.05))))
        return out
