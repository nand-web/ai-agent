"""Edit options: every toggle the user can turn on or off."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"


@dataclass
class EditOptions:
    # outputs
    formats: list[str] = field(default_factory=lambda: ["youtube", "reel"])  # youtube = 16:9, reel = 9:16
    reel_max_seconds: float = 60.0

    # cleanup
    remove_fillers: bool = True
    remove_silence: bool = True
    max_pause: float = 0.45          # pauses longer than this get shortened
    keep_pause: float = 0.18         # padding left around speech
    remove_retakes: bool = True      # AI removes false starts / repeated lines
    jump_zoom: bool = True           # alternate slight zoom after cuts

    # captions
    captions: bool = True
    caption_style: str = "bold"      # "bold" (word-by-word pop) | "minimal"

    # text overlays
    hook: bool = True
    hook_text: str = ""              # empty = AI suggests one
    lower_third: bool = True
    person_name: str = ""
    person_title: str = ""
    cta: bool = True
    cta_text: str = ""

    # branding
    logo_path: str = ""
    logo_opacity: float = 0.85

    # audio
    clean_audio: bool = True         # denoise + loudness normalize
    music: bool = True
    music_path: str = ""             # file; empty = pick from assets/music/<mood>/
    music_mood: str = "upbeat"
    music_volume: float = 0.18       # 0..1, relative to voice
    ducking: bool = True
    sound_effects: bool = True

    # visuals
    emoji: bool = True
    broll: bool = True
    broll_dir: str = ""              # local clips; filename words are used as keywords

    # quality
    crf: int = 18
    preset: str = "medium"

    # AI
    use_ai: bool = True
    language: str = ""               # "" = auto detect (Hindi/English/Hinglish)
    whisper_model: str = "small"

    def to_dict(self) -> dict:
        return asdict(self)
