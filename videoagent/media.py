"""Video facts (size, fps, duration) and where the speaker's face sits in the frame."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path



@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool
    hdr: bool = False       # iPhone HLG / HDR10: needs tone-mapping to look right in SDR

    @property
    def aspect(self) -> float:
        return self.width / self.height


def probe(path: Path) -> VideoInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(Path(path).resolve())],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    w, h = int(v["width"]), int(v["height"])
    # phones store portrait video as landscape + rotation metadata
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if "rotate" in v.get("tags", {}):
        rot = int(v["tags"]["rotate"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1"
    try:
        fps = float(Fraction(rate)) if rate != "0/0" else 30.0
    except (ZeroDivisionError, ValueError):
        fps = 30.0
    fps = min(max(round(fps, 3), 15.0), 60.0)
    duration = float(data["format"].get("duration") or v.get("duration") or 0)
    hdr = v.get("color_transfer") in ("arib-std-b67", "smpte2084") or v.get("color_primaries") == "bt2020"
    return VideoInfo(w, h, fps, duration, has_audio, hdr)


def face_center(path: Path, samples: int = 24) -> tuple[float, float]:
    """Median face centre as fractions of width/height; (0.5, 0.42) when no face is found.

    FFmpeg decodes only keyframes at small size, which is fast even for 4K HEVC.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.5, 0.42
    info = probe(path)
    sw = 480
    sh = max(2, round(sw * info.height / info.width / 2) * 2)
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-skip_frame", "nokey", "-i", str(Path(path).resolve()),
         "-vf", f"scale={sw}:{sh}", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    ).stdout
    n = len(raw) // (sw * sh)
    if n == 0:
        return 0.5, 0.42
    frames = np.frombuffer(raw[: n * sw * sh], dtype=np.uint8).reshape(n, sh, sw)
    picks = sorted({int(i) for i in np.linspace(0, n - 1, min(samples, n))})
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs, ys = [], []
    for i in picks:
        faces = cascade.detectMultiScale(frames[i], 1.1, 5, minSize=(30, 30))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + fw / 2) / sw)
            ys.append((y + fh / 2) / sh)
    if not xs:
        return 0.5, 0.42
    xs.sort(), ys.sort()
    return xs[len(xs) // 2], ys[len(ys) // 2]


@dataclass
class Source:
    """One take, placed on the joined timeline at `offset` seconds."""
    path: Path
    info: VideoInfo
    offset: float
    duration: float          # length used on the timeline (whole frames)


def open_sources(paths: list[Path]) -> tuple[list[Source], VideoInfo]:
    """Probe the takes and lay them end to end on one timeline.

    No joined file is written: the renderer cuts every take directly, so nothing is
    re-encoded twice and 4K takes keep full resolution for the reel crop.
    """
    infos = [probe(p) for p in paths]
    first = infos[0]
    fps = first.fps
    sources, acc = [], 0.0
    for p, info in zip(paths, infos):
        dur = int(info.duration * fps) / fps
        sources.append(Source(Path(p).resolve(), info, acc, dur))
        acc += dur
    combined = VideoInfo(first.width, first.height, fps, acc, any(i.has_audio for i in infos), first.hdr)
    return sources, combined


def joined_audio(sources: list[Source], sr: int = 16000):
    """16 kHz mono audio of all takes back to back, aligned with the timeline."""
    import numpy as np

    from .transcript import load_audio

    parts = []
    for src in sources:
        n = int(round(src.duration * sr))
        a = load_audio(src.path, sr) if src.info.has_audio else np.zeros(0, dtype=np.float32)
        parts.append(a[:n] if len(a) >= n else np.pad(a, (0, n - len(a))))
    return np.concatenate(parts)
