"""Command line: python -m videoagent raw.mp4 --name "Rahul Mehta" --title "Founder, FitBox Gym" """
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import EditOptions
from .pipeline import edit


def main() -> None:
    p = argparse.ArgumentParser(prog="videoagent", description="AI editor for talking-head testimonials and vlogs")
    p.add_argument("video", type=Path, nargs="+", help="one video, or several takes in order")
    p.add_argument("--out", type=Path, default=Path("output"))
    p.add_argument("--formats", default="youtube,reel", help="youtube,reel")
    p.add_argument("--transcript", type=Path, help="use an existing transcript JSON instead of Whisper")
    p.add_argument("--whisper-model", default="small", help="tiny | base | small | medium | large-v3")
    p.add_argument("--language", default="", help="hi | en | empty for auto")
    p.add_argument("--no-ai", action="store_true", help="skip Claude, use rule-based plan")

    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--caption-style", choices=["bold", "minimal"], default="bold")
    p.add_argument("--no-hook", action="store_true")
    p.add_argument("--hook", default="", help="hook text; CAPS word gets highlighted")
    p.add_argument("--name", default="")
    p.add_argument("--title", default="")
    p.add_argument("--no-cta", action="store_true")
    p.add_argument("--cta", default="")

    p.add_argument("--logo", default="")
    p.add_argument("--no-music", action="store_true")
    p.add_argument("--music", default="", help="music file")
    p.add_argument("--mood", default="upbeat", help="folder name under assets/music/")
    p.add_argument("--music-volume", type=float, default=0.18)
    p.add_argument("--no-ducking", action="store_true")
    p.add_argument("--no-sfx", action="store_true")
    p.add_argument("--no-emoji", action="store_true")
    p.add_argument("--no-broll", action="store_true")
    p.add_argument("--broll-dir", default="")

    p.add_argument("--keep-silence", action="store_true", help="do not shorten pauses")
    p.add_argument("--keep-fillers", action="store_true")
    p.add_argument("--no-zoom", action="store_true")
    p.add_argument("--reel-seconds", type=float, default=60)
    p.add_argument("--resolution", choices=["1080p", "4k"], default="1080p", help="4k only for 4K sources; much slower")
    p.add_argument("--crf", type=int, default=18, help="lower = better quality, bigger file")
    p.add_argument("--preset", default="medium")
    a = p.parse_args()

    opts = EditOptions(
        formats=[f.strip() for f in a.formats.split(",") if f.strip()],
        reel_max_seconds=a.reel_seconds,
        remove_fillers=not a.keep_fillers, remove_silence=not a.keep_silence, jump_zoom=not a.no_zoom,
        captions=not a.no_captions, caption_style=a.caption_style,
        hook=not a.no_hook, hook_text=a.hook,
        lower_third=bool(a.name), person_name=a.name, person_title=a.title,
        cta=not a.no_cta, cta_text=a.cta,
        logo_path=a.logo,
        music=not a.no_music, music_path=a.music, music_mood=a.mood, music_volume=a.music_volume, ducking=not a.no_ducking,
        sound_effects=not a.no_sfx, emoji=not a.no_emoji, broll=not a.no_broll, broll_dir=a.broll_dir,
        resolution=a.resolution, crf=a.crf, preset=a.preset,
        use_ai=not a.no_ai, language=a.language, whisper_model=a.whisper_model,
    )
    result = edit(a.video if len(a.video) > 1 else a.video[0], opts, a.out, transcript_path=a.transcript)
    print(json.dumps(result["outputs"], indent=2))


if __name__ == "__main__":
    main()
