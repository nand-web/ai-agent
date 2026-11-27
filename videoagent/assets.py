"""Sound effects, emoji images, music tracks and B-roll clips."""
from __future__ import annotations

import json
import math
import os
import random
import re
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from .config import ASSETS

CACHE = ASSETS / ".cache"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


# ---------------------------------------------------------------- sound effects

def _write_wav(path: Path, samples: list[float], sr: int = 48000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = max(1e-9, max(abs(s) for s in samples))
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(b"".join(int(s / peak * 0.9 * 32767).to_bytes(2, "little", signed=True) for s in samples))


def _synth_whoosh(sr: int = 48000, dur: float = 0.55) -> list[float]:
    rnd = random.Random(7)
    n = int(sr * dur)
    out, y = [], 0.0
    for i in range(n):
        p = i / n
        cutoff = 300 + 5000 * math.sin(math.pi * p) ** 2          # sweep up then down
        a = 1 - math.exp(-2 * math.pi * cutoff / sr)
        y += a * (rnd.uniform(-1, 1) - y)                       # one-pole low-pass on noise
        out.append(y * math.sin(math.pi * p) ** 1.5)
    return out


def _synth_pop(sr: int = 48000, dur: float = 0.14) -> list[float]:
    n, phase, out = int(sr * dur), 0.0, []
    for i in range(n):
        t = i / sr
        freq = 300 + 900 * math.exp(-t * 40)
        phase += 2 * math.pi * freq / sr
        out.append(math.sin(phase) * math.exp(-t * 30))
    return out


def sfx_file(kind: str) -> Path | None:
    """User files in assets/sfx/<kind>.(wav|mp3) win; otherwise a synthesized one is made."""
    for ext in (".wav", ".mp3"):
        p = ASSETS / "sfx" / f"{kind}{ext}"
        if p.exists():
            return p
    synth = {"whoosh": _synth_whoosh, "pop": _synth_pop}.get(kind)
    if not synth:
        return None
    p = CACHE / "sfx" / f"{kind}.wav"
    if not p.exists():
        _write_wav(p, synth())
    return p


# ---------------------------------------------------------------- emoji

def _codepoints(emoji: str, sep: str = "-", drop_fe0f: bool = False) -> str:
    cps = [f"{ord(c):x}" for c in emoji if not (drop_fe0f and ord(c) == 0xFE0F)]
    return sep.join(cps)


def _download(url: str, dest: Path, headers: dict | None = None, timeout: int = 30) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "videoagent/0.1", **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def _render_with_font(emoji: str, dest: Path) -> bool:
    """Draw the emoji with a colour-emoji font installed on this computer."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "C:/Windows/Fonts/seguiemj.ttf",
    ]
    for font_path in candidates:
        if not os.path.exists(font_path):
            continue
        for size in (109, 160, 96, 64):
            try:
                font = ImageFont.truetype(font_path, size)
                img = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
                ImageDraw.Draw(img).text((size // 2, size // 4), emoji, font=font, embedded_color=True)
                bbox = img.getbbox()
                if not bbox:
                    continue
                img = img.crop(bbox).resize((256, round(256 * (bbox[3] - bbox[1]) / (bbox[2] - bbox[0]))))
                dest.parent.mkdir(parents=True, exist_ok=True)
                img.save(dest)
                return True
            except Exception:
                continue
    return False


def emoji_png(emoji: str) -> Path | None:
    if not emoji:
        return None
    local = ASSETS / "emoji" / f"{_codepoints(emoji)}.png"
    if local.exists():
        return local
    dest = CACHE / "emoji" / f"{_codepoints(emoji)}.png"
    if dest.exists():
        return dest
    noto = f"https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/512/emoji_u{_codepoints(emoji, '_', drop_fe0f=True)}.png"
    twemoji = f"https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/{_codepoints(emoji, drop_fe0f=True)}.png"
    if _download(noto, dest) or _render_with_font(emoji, dest) or _download(twemoji, dest):
        return dest
    return None


# ---------------------------------------------------------------- music

def pick_music(music_path: str, mood: str) -> Path | None:
    if music_path:
        p = Path(music_path)
        return p if p.exists() else None
    folder = ASSETS / "music" / mood
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in AUDIO_EXT) if folder.exists() else []
    if not files:
        files = sorted(p for p in (ASSETS / "music").rglob("*") if p.suffix.lower() in AUDIO_EXT)
    return files[0] if files else None


# ---------------------------------------------------------------- B-roll

def _words(s: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", s.lower()) if len(w) > 2}


def local_broll(query: str, folder: Path) -> Path | None:
    if not folder.exists():
        return None
    want = _words(query)
    best, best_score = None, 0
    for p in folder.rglob("*"):
        if p.suffix.lower() in VIDEO_EXT:
            score = len(want & _words(p.stem))
            if score > best_score:
                best, best_score = p, score
    return best


def pexels_broll(query: str, portrait: bool) -> Path | None:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    orient = "portrait" if portrait else "landscape"
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    dest = CACHE / "broll" / f"{slug}-{orient}.mp4"
    if dest.exists():
        return dest
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": orient, "per_page": 5, "size": "medium"}
    )
    try:
        req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "videoagent/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            videos = json.load(r).get("videos", [])
    except Exception:
        return None
    for v in videos:
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        if not files:
            continue
        # smallest file that is still at least HD on its short side
        hd = [f for f in files if min(f["width"], f["height"]) >= 1080] or files
        f = min(hd, key=lambda f: f["width"] * f["height"])
        if _download(f["link"], dest, timeout=120):
            return dest
    return None


def find_broll(query: str, portrait: bool, folder: str = "") -> Path | None:
    return local_broll(query, Path(folder) if folder else ASSETS / "broll") or pexels_broll(query, portrait)
