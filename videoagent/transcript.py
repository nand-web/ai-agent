"""Word-level transcript: data model, Whisper transcription and JSON cache."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


@dataclass
class Word:
    text: str
    start: float
    end: float


def save_words(words: list[Word], path: Path) -> None:
    path.write_text(json.dumps([asdict(w) for w in words], ensure_ascii=False, indent=1), encoding="utf-8")


def load_words(path: Path) -> list[Word]:
    return [Word(**w) for w in json.loads(Path(path).read_text(encoding="utf-8"))]


def load_audio(path: Path, sr: int = 16000) -> np.ndarray:
    """Decode audio with FFmpeg (16 kHz mono float32), the format Whisper expects.

    Done here instead of inside faster-whisper so we do not depend on a PyAV version.
    """
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(Path(path).resolve()), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def transcribe(video: Path, model_size: str = "small", language: str = "") -> list[Word]:
    """Transcribe with faster-whisper and return words with timings.

    Runs on CPU by default (int8); uses CUDA automatically when available.
    """
    from faster_whisper import WhisperModel

    device, compute = "cpu", "int8"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            device, compute = "cuda", "float16"
    except Exception:
        pass

    model = WhisperModel(model_size, device=device, compute_type=compute)
    segments, _info = model.transcribe(
        load_audio(video),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        # Keeps "umm/aaa" in the text so the cleanup step can remove them.
        initial_prompt="Umm, aaa, toh basically, haan. Hinglish testimonial.",
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text, float(w.start), float(w.end)))
    return words
