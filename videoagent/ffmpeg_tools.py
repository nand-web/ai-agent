"""What the installed FFmpeg can do: encoders, filters, and a preflight check."""
from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess

# Every filter the pipeline uses. All are built into FFmpeg itself (no external
# library, no GPL-only filter), so any normal FFmpeg build has them.
REQUIRED_FILTERS = [
    "fps", "select", "setpts", "split", "crop", "scale", "pad", "setsar", "overlay", "format",
    "colorchannelmixer", "gblur", "fade", "trim", "concat",
    "aselect", "asetpts", "aresample", "aformat", "atrim", "apad", "anull", "anullsrc", "asplit",
    "highpass", "afftdn", "loudnorm", "volume", "afade", "adelay", "amix", "alimiter", "sidechaincompress",
]


def _run(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        return ""


def _names(listing: str) -> frozenset[str]:
    """Names from `ffmpeg -encoders` / `-filters` output.

    Rows look like "<flags> <name> <description>". The flags column changed width
    between FFmpeg versions (3 letters before 8.0, 2 after), and older versions have
    no "------" separator, so a row is recognised by its flags field instead.
    """
    names = set()
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] != "=" and re.fullmatch(r"[A-Z.|]{2,6}", parts[0]):
            names.add(parts[1])
    return frozenset(names)


@functools.lru_cache(maxsize=None)
def encoders() -> frozenset[str]:
    return _names(_run(["ffmpeg", "-hide_banner", "-encoders"]))


@functools.lru_cache(maxsize=None)
def filters() -> frozenset[str]:
    return _names(_run(["ffmpeg", "-hide_banner", "-filters"]))


def video_encoder() -> str:
    forced = os.environ.get("VIDEOAGENT_ENCODER")
    if forced:
        return forced
    for name in ("libx264", "h264_videotoolbox", "libopenh264", "mpeg4"):
        if name in encoders():
            return name
    return "mpeg4"


def video_args(width: int, height: int, crf: int = 18, preset: str = "medium", intermediate: bool = False) -> list[str]:
    """Encoder arguments for the best H.264 encoder available, at high quality."""
    enc = video_encoder()
    pixels = width * height
    # bitrates for encoders without a constant-quality mode
    mbps = 40 if pixels > 2_500_000 else 14
    if intermediate:
        mbps *= 2
    if enc == "libx264":
        return ["-c:v", "libx264", "-crf", str(12 if intermediate else crf),
                "-preset", "veryfast" if intermediate else preset, "-pix_fmt", "yuv420p"]
    if enc == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", f"{mbps}M", "-maxrate", f"{mbps * 2}M",
                "-bufsize", f"{mbps * 2}M", "-pix_fmt", "yuv420p"]
    if enc == "libopenh264":
        return ["-c:v", "libopenh264", "-b:v", f"{mbps}M", "-pix_fmt", "yuv420p"]
    return ["-c:v", "mpeg4", "-q:v", "1" if intermediate else "2", "-pix_fmt", "yuv420p"]


def preflight() -> None:
    """Fail early, with a clear fix, if FFmpeg is missing or too limited."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg nahi mila. Mac: `brew install ffmpeg`, Windows: `winget install ffmpeg`.")
    missing = [f for f in REQUIRED_FILTERS if f not in filters()]
    if missing:
        raise RuntimeError(
            "Aapke FFmpeg mein yeh filters nahi hain: " + ", ".join(missing)
            + ". FFmpeg update karo (Mac: `brew upgrade ffmpeg`)."
        )
    if "aac" not in encoders():
        raise RuntimeError("Aapke FFmpeg mein AAC audio encoder nahi hai. FFmpeg update karo.")


def sdr_filter(hdr: bool) -> str:
    """Filter chain (ending in ',') that turns HDR video into normal SDR BT.709, or ''."""
    if not hdr:
        return ""
    have = filters()
    if {"zscale", "tonemap"} <= have:
        return ("zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,"
                "tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
    # no zimg in this FFmpeg: convert the colour space only (HLG still looks close on SDR)
    return "format=yuv420p10le,colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:format=yuv420p,"
