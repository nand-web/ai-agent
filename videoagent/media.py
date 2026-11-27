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

    @property
    def aspect(self) -> float:
        return self.width / self.height


def probe(path: Path) -> VideoInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
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
    return VideoInfo(w, h, fps, duration, has_audio)


def face_center(path: Path, samples: int = 24) -> tuple[float, float]:
    """Median face centre as fractions of width/height; (0.5, 0.42) when no face is found."""
    try:
        import cv2
    except ImportError:
        return 0.5, 0.42
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs, ys = [], []
    for k in range(samples):
        if total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        scale = 640 / max(w, h)
        small = cv2.resize(frame, (int(w * scale), int(h * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + fw / 2) / small.shape[1])
            ys.append((y + fh / 2) / small.shape[0])
    cap.release()
    if not xs:
        return 0.5, 0.42
    xs.sort(), ys.sort()
    return xs[len(xs) // 2], ys[len(ys) // 2]
