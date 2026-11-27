"""Text overlays as an ASS subtitle file: captions, hook, name lower-third, CTA.

FFmpeg burns this file in with libass, so animations (pop, slide, fade)
stay crisp at any resolution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .transcript import Word

# ASS colours are &HAABBGGRR
WHITE = "&H00FFFFFF"
INK = "&H00170F0B"
YELLOW = "&H003FD2FF"
BOX_DARK = "&H40170F0B"


@dataclass
class Overlay:
    width: int
    height: int
    tall: bool


def ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _header(o: Overlay) -> str:
    H, W = o.height, o.width
    cap = round(H * (0.042 if o.tall else 0.062))
    cap_min = round(H * (0.026 if o.tall else 0.040))
    hook = round(H * (0.048 if o.tall else 0.082))
    name = round(H * (0.030 if o.tall else 0.048))
    role = round(H * (0.021 if o.tall else 0.032))
    cta = round(H * (0.028 if o.tall else 0.046))
    mv_cap = round(H * (0.20 if o.tall else 0.09))
    side = round(W * 0.06)
    outline = max(2, round(H * 0.004))
    styles = [
        # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, Underline, StrikeOut,
        # ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
        f"Style: Caption,Poppins ExtraBold,{cap},{WHITE},{WHITE},{INK},&H80000000,0,0,0,0,100,100,0,0,1,{outline * 2},{outline},2,{side},{side},{mv_cap},1",
        f"Style: CaptionMin,Inter SemiBold,{cap_min},{WHITE},{WHITE},{BOX_DARK},{BOX_DARK},0,0,0,0,100,100,0,0,3,{outline * 2},0,2,{side},{side},{mv_cap},1",
        f"Style: Hook,Poppins ExtraBold,{hook},{WHITE},{WHITE},{BOX_DARK},{BOX_DARK},0,0,0,0,100,100,0,0,3,{round(hook * 0.3)},0,8,{side},{side},{round(H * (0.09 if o.tall else 0.07))},1",
        f"Style: Name,Poppins ExtraBold,{name},{INK},{INK},{WHITE},{WHITE},0,0,0,0,100,100,0,0,3,{round(name * 0.28)},0,1,{side},{side},{round(H * (0.30 if o.tall else 0.25))},1",
        f"Style: Role,Poppins Bold,{role},{INK},{INK},{YELLOW},{YELLOW},0,0,0,0,100,100,0,0,3,{round(role * 0.32)},0,1,{side},{side},{round(H * (0.30 if o.tall else 0.25)) - round(role * 1.9)},1",
        f"Style: CTA,Poppins ExtraBold,{cta},{INK},{INK},{YELLOW},{YELLOW},0,0,0,0,100,100,0,0,3,{round(cta * 0.4)},0,8,{side},{side},{round(H * (0.09 if o.tall else 0.08))},1",
    ]
    return (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {W}\nPlayResY: {H}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + "\n".join(styles)
        + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _ev(start: float, end: float, style: str, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{ts(start)},{ts(end)},{style},,0,0,0,,{text}"


def _clean_word(text: str, upper: bool) -> str:
    t = esc(text).strip()
    t = re.sub(r"[,.;:]+$", "", t)
    return t.upper() if upper else t


def caption_events(words: list[Word], style: str = "bold", chunk: int = 3) -> list[str]:
    """Word-by-word captions. words must already be in edited time."""
    events: list[str] = []
    if not words:
        return events
    size = chunk if style == "bold" else 7
    groups: list[list[Word]] = []
    for w in words:
        # new group on size limit, sentence end, or a pause
        if not groups or len(groups[-1]) >= size or w.start - groups[-1][-1].end > 0.6 or groups[-1][-1].text.endswith((".", "?", "!", "।")):
            groups.append([w])
        else:
            groups[-1].append(w)

    for gi, g in enumerate(groups):
        g_end = g[-1].end + 0.25
        if gi + 1 < len(groups):
            g_end = min(g_end, groups[gi + 1][0].start)
        if style == "bold":
            for wi, w in enumerate(g):
                s = w.start if wi else g[0].start
                e = g[wi + 1].start if wi + 1 < len(g) else g_end
                if e - s < 0.02:
                    continue
                parts = []
                for k, x in enumerate(g):
                    word = _clean_word(x.text, upper=True)
                    if k == wi:
                        parts.append(f"{{\\c{YELLOW}\\fscx112\\fscy112}}{word}{{\\c{WHITE}\\fscx100\\fscy100}}")
                    else:
                        parts.append(word)
                pop = "{\\fscx70\\fscy70\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
                events.append(_ev(s, e, "Caption", pop + " ".join(parts)))
        else:
            text = " ".join(_clean_word(x.text, upper=False) for x in g)
            events.append(_ev(g[0].start, g_end, "CaptionMin", "{\\fad(80,80)}" + text))
    return events


def hook_text_ass(text: str) -> str:
    out = []
    for w in esc(text).split():
        letters = re.sub(r"[^A-Za-z]", "", w)
        if len(letters) > 1 and letters.isupper():
            out.append(f"{{\\c{YELLOW}}}{w}{{\\c{WHITE}}}")
        else:
            out.append(w)
    return " ".join(out)


def build_ass(
    o: Overlay,
    duration: float,
    *,
    words: list[Word] | None = None,
    caption_style: str = "bold",
    hook: str = "",
    name: str = "",
    title: str = "",
    cta: str = "",
) -> str:
    ev: list[str] = []
    hook_end = 0.0
    if hook:
        hook_end = min(3.2, duration)
        ev.append(_ev(0.05, hook_end, "Hook", "{\\fad(120,200)\\fscx85\\fscy85\\t(0,140,\\fscx100\\fscy100)}" + hook_text_ass(hook), layer=2))
    if name:
        s = hook_end + 0.3 if hook else 0.6
        e = min(s + 3.6, duration)
        if e > s:
            slide = f"{{\\fad(150,200)}}"
            ev.append(_ev(s, e, "Name", slide + esc(name), layer=2))
            if title:
                ev.append(_ev(s + 0.15, e, "Role", slide + esc(title), layer=2))
    if cta and duration > 4:
        ev.append(_ev(max(0, duration - 3.8), duration, "CTA", "{\\fad(150,0)\\fscx80\\fscy80\\t(0,160,\\fscx100\\fscy100)}" + esc(cta), layer=2))
    if words:
        ev.extend(caption_events(words, caption_style))
    return _header(o) + "\n".join(ev) + "\n"
