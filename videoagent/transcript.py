"""Word-level transcript: data model, Whisper transcription and JSON cache."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Word:
    text: str
    start: float
    end: float


def save_words(words: list[Word], path: Path) -> None:
    path.write_text(json.dumps([asdict(w) for w in words], ensure_ascii=False, indent=1), encoding="utf-8")


def load_words(path: Path) -> list[Word]:
    return [Word(**w) for w in json.loads(Path(path).read_text(encoding="utf-8"))]


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
        str(video),
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
