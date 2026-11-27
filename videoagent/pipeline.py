"""Raw video in, finished YouTube and Reel videos out."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from . import assets
from .config import EditOptions
from .cuts import Segment, Timeline, filler_indices, keep_segments, restrict
from .media import face_center, joined_audio, open_sources
from .ffmpeg_tools import preflight
from .overlays import build_events, render_text_track
from .planner import EditPlan, make_plan
from .render import Overlay, RenderJob, run, snap
from .transcript import Word, load_words, save_words, transcribe

HOOK_END = 3.2


def _size(fmt: str, src_w: int, src_h: int, resolution: str = "1080p") -> tuple[int, int]:
    big = resolution == "4k" and max(src_w, src_h) >= 3200
    if fmt == "reel":
        return (2160, 3840) if big else (1080, 1920)
    return (3840, 2160) if big else (1920, 1080)


def _plan_to_json(plan: EditPlan) -> dict:
    d = asdict(plan)
    d["removed"] = sorted(plan.removed)
    return d


def edit(
    video: Path | list[Path],
    opts: EditOptions,
    out_dir: Path,
    *,
    transcript_path: Path | None = None,
    log=print,
) -> dict:
    """Edit one video, or several takes of the same recording (joined in the given order)."""
    preflight()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    takes = [Path(v) for v in video] if isinstance(video, (list, tuple)) else [Path(video)]
    sources, info = open_sources(takes)
    take_starts = [s.offset for s in sources] if len(sources) > 1 else None
    stem = takes[0].stem + ("_takes" if len(takes) > 1 else "")
    if len(takes) > 1:
        log(f"{len(takes)} takes: " + ", ".join(t.name for t in takes))
    log(f"Video: {info.width}x{info.height}, {info.fps:g} fps, {info.duration:.1f}s" + (" (HDR)" if any(s.info.hdr for s in sources) else ""))

    # 1. transcript
    key = hashlib.sha1("|".join(f"{t.name}:{t.stat().st_size}" for t in takes).encode()).hexdigest()[:8]
    cached = out_dir / f"{stem}.{key}.transcript.json"
    if transcript_path:
        words = load_words(transcript_path)
    elif cached.exists():
        words = load_words(cached)
        log("Using saved transcript")
    else:
        log(f"Transcribing with Whisper ({opts.whisper_model})... this can take a few minutes")
        words = transcribe(joined_audio(sources), opts.whisper_model, opts.language, log=log)
    save_words(words, cached)
    log(f"Transcript: {len(words)} words")

    # 2. plan
    plan = make_plan(words, use_ai=opts.use_ai, reel_max=opts.reel_max_seconds, take_starts=take_starts, log=log)
    (out_dir / f"{stem}.plan.json").write_text(json.dumps(_plan_to_json(plan), ensure_ascii=False, indent=1), encoding="utf-8")

    removed: set[int] = set()
    if opts.remove_fillers:
        removed |= filler_indices(words)
    if opts.remove_retakes:
        removed |= plan.removed

    if words:
        base = keep_segments(
            words, removed, info.duration,
            cut_pauses=opts.remove_silence, max_pause=opts.max_pause, pad=opts.keep_pause,
        )
    else:
        base = [Segment(0, info.duration)]
    face = face_center(takes[0])
    log(f"Kept {sum(s.dur for s in base):.1f}s of {info.duration:.1f}s; face at x={face[0]:.2f}")

    results = {"plan": _plan_to_json(plan), "outputs": {}}
    for fmt in opts.formats:
        out = _render_format(fmt, stem, sources, info, words, removed, base, plan, face, opts, out_dir, log)
        results["outputs"][fmt] = str(out)
    return results


def _render_format(fmt, stem: str, sources, info, words: list[Word], removed, base, plan: EditPlan, face, opts: EditOptions, out_dir: Path, log):
    W, H = _size(fmt, info.width, info.height, opts.resolution)
    tall = H > W
    segs = base
    if fmt == "reel" and plan.reel_ranges and words:
        ranges = [(words[a].start - 0.25, words[b].end + 0.35) for a, b in plan.reel_ranges]
        segs = restrict(base, ranges) or base
    segs = snap(segs, info.fps, info.duration)
    if fmt == "reel":
        # hard cap for platforms
        capped, acc = [], 0.0
        for s in segs:
            if acc >= opts.reel_max_seconds:
                break
            take = min(s.dur, opts.reel_max_seconds - acc)
            capped.append(Segment(s.start, s.start + take))
            acc += take
        segs = snap(capped, info.fps, info.duration)
    tl = Timeline(segs)
    total = tl.duration

    def at(i: int, end: bool = False) -> float | None:
        w = words[i]
        return tl.to_edited(w.end if end else w.start)

    edited_words = [w for i, w in tl.words(words) if i not in removed]

    hook = (opts.hook_text or (plan.hook_options[0] if plan.hook_options else "")) if opts.hook else ""
    cta = (opts.cta_text or plan.cta) if opts.cta else ""
    name = opts.person_name if opts.lower_third else ""
    title = opts.person_title if opts.lower_third else ""

    events = build_events(
        total,
        words=edited_words if opts.captions else None,
        caption_style=opts.caption_style, hook=hook, name=name, title=title, cta=cta,
    )
    text_dir = out_dir / f".text_{fmt}"
    shutil.rmtree(text_dir, ignore_errors=True)
    text_track = render_text_track(events, W, H, total, info.fps, text_dir)

    busy_start = HOOK_END if hook else 0.3
    busy_end = total - (4.0 if cta else 0.5)
    sfx: list[tuple[float, Path]] = []
    whoosh, pop = (assets.sfx_file("whoosh"), assets.sfx_file("pop")) if opts.sound_effects else (None, None)
    if hook and whoosh:
        sfx.append((0.0, whoosh))

    broll: list[Overlay] = []
    if opts.broll:
        for b in plan.broll:
            s, e = at(b.start), at(b.end, end=True)
            if s is None or e is None:
                continue
            e = min(max(e, s + 2.0), s + 5.0, busy_end)
            if s < busy_start or e - s < 1.5 or any(not (e <= o.start or s >= o.end) for o in broll):
                continue
            clip = assets.find_broll(b.query, portrait=tall, folder=opts.broll_dir)
            if not clip:
                log(f"  no B-roll found for '{b.query}' (add clips to assets/broll or set PEXELS_API_KEY)")
                continue
            broll.append(Overlay(s, e, clip))
            if whoosh:
                sfx.append((max(0.0, s - 0.15), whoosh))

    emoji: list[Overlay] = []
    if opts.emoji or opts.sound_effects:
        for em in plan.emphasis:
            t = at(em.word)
            if t is None or t < busy_start or t > busy_end:
                continue
            if opts.emoji and em.emoji:
                png = assets.emoji_png(em.emoji)
                if png:
                    emoji.append(Overlay(t, min(t + 1.6, total), png))
                    if pop:
                        sfx.append((t, pop))
                    continue
            if em.sfx == "whoosh" and whoosh:
                sfx.append((t, whoosh))

    music = assets.pick_music(opts.music_path, opts.music_mood) if opts.music else None
    if opts.music and not music:
        log("  no music file found (add tracks to assets/music/<mood>/ or pick a file)")

    logo = Path(opts.logo_path) if opts.logo_path and Path(opts.logo_path).exists() else None
    job = RenderJob(
        sources=sources, info=info, segs=segs, out=out_dir / f"{stem}_{fmt}.mp4",
        width=W, height=H, face=face, text_track=text_track,
        zoom_segments=list(range(1, len(segs), 2)) if opts.jump_zoom else [],
        broll=broll, emoji=emoji, logo=logo, logo_opacity=opts.logo_opacity,
        music=music, music_volume=opts.music_volume, ducking=opts.ducking,
        sfx=sfx, clean_audio=opts.clean_audio, crf=opts.crf, preset=opts.preset,
    )
    log(f"[{fmt}] {total:.1f}s, {len(segs)} cuts, {len(broll)} B-roll, {len(emoji)} emoji, music: {music.name if music else 'off'}")
    try:
        return run(job, log=log)
    finally:
        shutil.rmtree(text_dir, ignore_errors=True)
