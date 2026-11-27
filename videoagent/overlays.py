"""Text overlays: captions, hook, name lower-third and CTA.

Text is drawn with Pillow into transparent PNG frames and listed in an FFmpeg concat
file. FFmpeg only has to overlay those images, so no subtitle library (libass) or
font library is needed in the user's FFmpeg build.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

from .config import ASSETS
from .transcript import Word

FONT_XBOLD = ASSETS / "fonts" / "Poppins-ExtraBold.ttf"
FONT_BOLD = ASSETS / "fonts" / "Poppins-Bold.ttf"

WHITE = (255, 255, 255, 255)
INK = (11, 15, 23, 255)
YELLOW = (255, 210, 63, 255)
BOX_DARK = (11, 15, 23, 200)

POP_STEPS = 4  # frames of the pop-in animation


@dataclass
class TextEvent:
    start: float
    end: float
    kind: str                     # caption | caption_min | hook | name | cta
    words: list[str] = field(default_factory=list)
    highlight: int = -1           # caption: index of the word being spoken
    pop: bool = False             # scale/fade in over the first few frames
    later: list[str] = field(default_factory=list)  # name: second line (title)


# ---------------------------------------------------------------- events

def _clean(text: str) -> str:
    return re.sub(r"[,.;:]+$", "", text.strip())


def caption_events(words: list[Word], style: str = "bold", chunk: int = 3) -> list[TextEvent]:
    """Word-by-word captions. words must already be in edited time."""
    events: list[TextEvent] = []
    size = chunk if style == "bold" else 7
    groups: list[list[Word]] = []
    for w in words:
        if (
            not groups
            or len(groups[-1]) >= size
            or w.start - groups[-1][-1].end > 0.6
            or groups[-1][-1].text.endswith((".", "?", "!", "।"))
        ):
            groups.append([w])
        else:
            groups[-1].append(w)

    for gi, g in enumerate(groups):
        g_end = g[-1].end + 0.25
        if gi + 1 < len(groups):
            g_end = min(g_end, groups[gi + 1][0].start)
        if style == "bold":
            texts = [_clean(x.text).upper() for x in g]
            for wi, w in enumerate(g):
                s = g[0].start if wi == 0 else w.start
                e = g[wi + 1].start if wi + 1 < len(g) else g_end
                if e - s >= 0.02:
                    events.append(TextEvent(s, e, "caption", texts, highlight=wi, pop=wi == 0))
        else:
            events.append(TextEvent(g[0].start, g_end, "caption_min", [_clean(x.text) for x in g]))
    return events


def build_events(
    duration: float,
    *,
    words: list[Word] | None = None,
    caption_style: str = "bold",
    hook: str = "",
    name: str = "",
    title: str = "",
    cta: str = "",
) -> list[TextEvent]:
    ev: list[TextEvent] = []
    hook_end = 0.0
    if hook:
        hook_end = min(3.2, duration)
        ev.append(TextEvent(0.0, hook_end, "hook", hook.split(), pop=True))
    if name:
        s = hook_end + 0.3 if hook else 0.6
        e = min(s + 3.6, duration)
        if e > s:
            ev.append(TextEvent(s, e, "name", [name], pop=True, later=[title] if title else []))
    if cta and duration > 4:
        ev.append(TextEvent(max(0.0, duration - 3.8), duration, "cta", cta.split(), pop=True))
    if words:
        ev.extend(caption_events(words, caption_style))
    return ev


# ---------------------------------------------------------------- drawing

class TextRenderer:
    def __init__(self, width: int, height: int):
        self.W, self.H = width, height
        self.tall = height > width
        H = height
        engine = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
        self._engine = engine
        self.sizes = {
            "caption": round(H * (0.042 if self.tall else 0.062)),
            "caption_min": round(H * (0.026 if self.tall else 0.040)),
            "hook": round(H * (0.036 if self.tall else 0.070)),
            "name": round(H * (0.030 if self.tall else 0.048)),
            "role": round(H * (0.021 if self.tall else 0.032)),
            "cta": round(H * (0.028 if self.tall else 0.046)),
        }
        self.side = round(width * 0.06)
        self._fonts: dict[tuple, ImageFont.FreeTypeFont] = {}
        self._sprites: dict[tuple, tuple[Image.Image, int, int]] = {}

    def font(self, size: int, bold_only: bool = False) -> ImageFont.FreeTypeFont:
        key = (size, bold_only)
        if key not in self._fonts:
            path = FONT_BOLD if bold_only else FONT_XBOLD
            self._fonts[key] = ImageFont.truetype(str(path), size, layout_engine=self._engine)
        return self._fonts[key]

    # ---- helpers

    @staticmethod
    def _width(font, text: str) -> float:
        return font.getlength(text)

    def _wrap(self, words: list[str], font, max_w: float) -> list[list[str]]:
        lines: list[list[str]] = [[]]
        for w in words:
            trial = " ".join(lines[-1] + [w])
            if lines[-1] and self._width(font, trial) > max_w:
                lines.append([w])
            else:
                lines[-1].append(w)
        return lines

    def _box_text(self, lines: list[list[tuple[str, tuple]]], font, box_fill, pad_x, pad_y, radius) -> Image.Image:
        """Draw lines of coloured word runs on a rounded box; returns a tight sprite."""
        asc, desc = font.getmetrics()
        line_h = asc + desc
        space = self._width(font, " ")
        widths = [sum(self._width(font, t) for t, _ in ln) + space * (len(ln) - 1) for ln in lines]
        w = int(max(widths) + pad_x * 2)
        h = int(line_h * len(lines) + pad_y * 2 + (len(lines) - 1) * line_h * 0.08)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if box_fill:
            d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=box_fill)
        y = pad_y
        for ln, lw in zip(lines, widths):
            x = (w - lw) / 2
            for t, color in ln:
                d.text((x, y), t, font=font, fill=color)
                x += self._width(font, t) + space
            y += line_h * 1.08
        return img

    # ---- sprites per event kind: (image, x, y) top-left position on the frame

    def sprite(self, ev: TextEvent) -> tuple[Image.Image, int, int]:
        key = (ev.kind, tuple(ev.words), ev.highlight, tuple(ev.later))
        if key in self._sprites:
            return self._sprites[key]
        W, H = self.W, self.H
        if ev.kind == "caption":
            out = self._caption_bold(ev)
        elif ev.kind == "caption_min":
            font = self.font(self.sizes["caption_min"], bold_only=True)
            lines = self._wrap(ev.words, font, W * 0.86)
            img = self._box_text([[(t, WHITE) for t in ln] for ln in lines], font, BOX_DARK,
                                 font.size * 0.45, font.size * 0.22, font.size * 0.25)
            out = (img, (W - img.width) // 2, int(H - H * (0.20 if self.tall else 0.09) - img.height))
        elif ev.kind == "hook":
            font = self.font(self.sizes["hook"])
            # wide: stay clear of the logo in the top-right corner
            lines = self._wrap(ev.words, font, W * (0.80 if self.tall else 0.62))
            colored = [[(t, YELLOW if _is_caps(t) else WHITE) for t in ln] for ln in lines]
            img = self._box_text(colored, font, BOX_DARK, font.size * 0.45, font.size * 0.25, font.size * 0.25)
            out = (img, (W - img.width) // 2, int(H * (0.07 if self.tall else 0.06)))
        elif ev.kind == "name":
            out = self._lower_third(ev)
        elif ev.kind == "cta":
            font = self.font(self.sizes["cta"])
            lines = self._wrap(ev.words, font, W * 0.80)
            img = self._box_text([[(t, INK) for t in ln] for ln in lines], font, YELLOW,
                                 font.size * 0.8, font.size * 0.3, font.size)
            out = (img, (W - img.width) // 2, int(H * (0.09 if self.tall else 0.08)))
        else:
            raise ValueError(ev.kind)
        self._sprites[key] = out
        return out

    def _caption_bold(self, ev: TextEvent) -> tuple[Image.Image, int, int]:
        W, H = self.W, self.H
        size = self.sizes["caption"]
        font = self.font(size)
        # shrink if the chunk is too wide for the frame
        while size > 12 and self._width(font, " ".join(ev.words)) * 1.15 > W * 0.88:
            size = int(size * 0.9)
            font = self.font(size)
        big = self.font(int(size * 1.12))
        stroke = max(2, round(size * 0.09))
        space = self._width(font, " ")
        runs = [(t, big if i == ev.highlight else font, YELLOW if i == ev.highlight else WHITE) for i, t in enumerate(ev.words)]
        total = sum(self._width(f, t) for t, f, _ in runs) + space * (len(runs) - 1)
        asc, desc = big.getmetrics()
        w = int(total + stroke * 4 + size * 0.2)
        h = int(asc + desc + stroke * 4)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        base_y = stroke * 2 + asc  # shared baseline so the bigger word lines up
        for dx, dy, fill in [(0, stroke * 0.8, (0, 0, 0, 150)), (0, 0, None)]:
            x = stroke * 2
            for t, f, color in runs:
                if fill:
                    d.text((x + dx, base_y + dy), t, font=f, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=fill)
                else:
                    d.text((x, base_y), t, font=f, fill=color, anchor="ls", stroke_width=stroke, stroke_fill=INK)
                x += self._width(f, t) + space
        bottom = H - H * (0.20 if self.tall else 0.09)
        return img, (W - w) // 2, int(bottom - h)

    def _lower_third(self, ev: TextEvent) -> tuple[Image.Image, int, int]:
        H = self.H
        nf = self.font(self.sizes["name"])
        name = self._box_text([[(ev.words[0], INK)]], nf, WHITE, nf.size * 0.4, nf.size * 0.18, 4)
        parts = [name]
        if ev.later and ev.later[0]:
            rf = self.font(self.sizes["role"], bold_only=True)
            parts.append(self._box_text([[(ev.later[0], INK)]], rf, YELLOW, rf.size * 0.45, rf.size * 0.2, 4))
        gap = int(nf.size * 0.12)
        w = max(p.width for p in parts)
        h = sum(p.height for p in parts) + gap * (len(parts) - 1)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        y = 0
        for p in parts:
            img.alpha_composite(p, (0, y))
            y += p.height + gap
        bottom = H - H * (0.30 if self.tall else 0.23)   # above the captions
        return img, self.side, int(bottom - h)

    # ---- frames

    def frame(self, active: list[tuple[TextEvent, int]]) -> Image.Image:
        img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        for ev, step in active:
            spr, x, y = self.sprite(ev)
            if step < POP_STEPS:
                p = (step + 1) / (POP_STEPS + 1)
                scale = 0.75 + 0.25 * p
                sw, sh = max(1, int(spr.width * scale)), max(1, int(spr.height * scale))
                small = spr.resize((sw, sh), Image.LANCZOS)
                alpha = small.getchannel("A").point(lambda a: int(a * p))
                small.putalpha(alpha)
                x += (spr.width - sw) // 2
                y += (spr.height - sh) // 2
                spr = small
            img.alpha_composite(spr, (max(0, x), max(0, y)))
        return img


def _is_caps(word: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", word)
    return len(letters) > 1 and letters.isupper()


def render_text_track(events: list[TextEvent], width: int, height: int, duration: float, fps: float, folder: Path) -> Path | None:
    """Write PNG frames + an FFmpeg concat list for the text overlay. Returns the list path."""
    if not events or duration <= 0:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    r = TextRenderer(width, height)
    points = {0.0, duration}
    for ev in events:
        points.update({max(0.0, ev.start), min(duration, ev.end)})
        if ev.pop:
            points.update(min(duration, ev.start + k / fps) for k in range(1, POP_STEPS + 1))
    times = sorted(t for t in points if 0 <= t <= duration)

    files: dict[tuple, str] = {}
    entries: list[tuple[str, float]] = []
    for a, b in zip(times, times[1:]):
        if b - a < 1e-4:
            continue
        mid = (a + b) / 2
        active = []
        for i, ev in enumerate(events):
            if ev.start <= mid < ev.end:
                step = min(POP_STEPS, int((mid - ev.start) * fps)) if ev.pop else POP_STEPS
                active.append((i, step))
        key = tuple(active)
        if key not in files:
            name = f"t{len(files):05d}.png"
            r.frame([(events[i], s) for i, s in active]).save(folder / name, compress_level=1)
            files[key] = name
        if entries and entries[-1][0] == files[key]:
            entries[-1] = (files[key], entries[-1][1] + (b - a))
        else:
            entries.append((files[key], b - a))

    lines = []
    for name, dur in entries:
        lines += [f"file '{name}'", f"duration {dur:.4f}"]
    lines.append(f"file '{entries[-1][0]}'")  # concat demuxer needs the last file repeated
    lst = folder / "text.txt"
    lst.write_text("\n".join(lines) + "\n")
    return lst
