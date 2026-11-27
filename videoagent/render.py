"""Build and run the FFmpeg command that produces one finished video."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import ASSETS
from .cuts import Segment
from .media import VideoInfo

FONTS = ASSETS / "fonts"


@dataclass
class Overlay:
    start: float           # edited-time seconds
    end: float
    path: Path


@dataclass
class RenderJob:
    src: Path
    info: VideoInfo
    segs: list[Segment]
    out: Path
    width: int
    height: int
    face: tuple[float, float] = (0.5, 0.42)
    ass: Path | None = None
    zoom_segments: list[int] = field(default_factory=list)  # indices into segs that get a punch-in
    zoom: float = 1.08
    broll: list[Overlay] = field(default_factory=list)
    emoji: list[Overlay] = field(default_factory=list)
    logo: Path | None = None
    logo_opacity: float = 0.85
    music: Path | None = None
    music_volume: float = 0.18
    ducking: bool = True
    sfx: list[tuple[float, Path]] = field(default_factory=list)
    clean_audio: bool = True
    crf: int = 18
    preset: str = "medium"


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


SUBS_NAME = "overlay.ass"
FONTS_DIR = "fonts"


def _prepare_workdir(job: "RenderJob") -> Path:
    """Put the subtitle file and fonts next to each other under plain names.

    FFmpeg then reads them by bare relative name, which avoids path quoting rules that
    differ between FFmpeg versions (spaces, colons, long temp paths on macOS).
    """
    work = Path(job.out).resolve().parent / f".render_{Path(job.out).stem}"
    (work / FONTS_DIR).mkdir(parents=True, exist_ok=True)
    for f in FONTS.glob("*.ttf"):
        dest = work / FONTS_DIR / f.name
        if not dest.exists():
            shutil.copyfile(f, dest)
    if job.ass:
        shutil.copyfile(job.ass, work / SUBS_NAME)
    return work


def snap(segs: list[Segment], fps: float, duration: float) -> list[Segment]:
    """Put cut points on the frame grid so audio and video stay in sync over many cuts."""
    out = []
    for s in segs:
        a = round(s.start * fps) / fps
        b = min(round(s.end * fps) / fps, duration)
        if b - a >= 1 / fps:
            out.append(Segment(a, b))
    return out


def _cover(src_w: int, src_h: int, W: int, H: int, fx: float, fy: float) -> str:
    """Crop the largest W:H window around the face, then scale to W x H."""
    A = W / H
    if src_w / src_h > A:
        ch, cw = src_h, src_h * A
    else:
        cw, ch = src_w, src_w / A
    cw, ch = _even(min(cw, src_w)), _even(min(ch, src_h))
    x = min(max(fx * src_w - cw / 2, 0), src_w - cw)
    y = min(max(fy * src_h - ch * 0.42, 0), src_h - ch)
    return f"crop={cw}:{ch}:{int(x)}:{int(y)},scale={W}:{H}:flags=lanczos,setsar=1"


def build_command(job: RenderJob) -> list[str]:
    info, W, H = job.info, job.width, job.height
    fps = info.fps
    segs = snap(job.segs, fps, info.duration)
    if not segs:
        raise ValueError("Nothing left to keep after cutting")
    total = sum(s.dur for s in segs)
    eps = 0.5 / fps

    inputs: list[str] = ["-i", str(Path(job.src).resolve())]
    n_in = 1

    def add_input(*args: str) -> int:
        nonlocal n_in
        inputs.extend(args)
        n_in += 1
        return n_in - 1

    g: list[str] = []
    keep_v = "+".join(f"gte(t,{s.start - eps:.4f})*lt(t,{s.end - eps:.4f})" for s in segs)
    keep_a = "+".join(f"gte(t,{s.start:.4f})*lt(t,{s.end:.4f})" for s in segs)

    # ---- video: CFR, cut, frame for the target shape
    g.append(f"[0:v]fps={fps},select='{keep_v}',setpts=N/({fps})/TB[cut]")
    tall_src_to_wide = info.aspect < (W / H) * 0.8
    if tall_src_to_wide:
        # vertical source into 16:9: blurred fill behind the sharp video
        g.append(
            f"[cut]split[bgi][fgi];"
            f"[bgi]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.08[bg];"
            f"[fgi]scale=-2:{H}:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1[framed]"
        )
    else:
        g.append(f"[cut]{_cover(info.width, info.height, W, H, *job.face)}[framed]")
    cur = "framed"

    # ---- jump-cut punch-in: a zoomed copy shown on alternating segments
    if job.zoom_segments:
        offsets, acc = [], 0.0
        for s in segs:
            offsets.append(acc)
            acc += s.dur
        spans = [(offsets[i], offsets[i] + segs[i].dur) for i in job.zoom_segments if i < len(segs)]
        if spans:
            en = "+".join(f"between(t,{a:.3f},{b - 0.001:.3f})" for a, b in spans)
            zw, zh = _even(W / job.zoom), _even(H / job.zoom)
            g.append(
                f"[{cur}]split[zb][zs];[zs]crop={zw}:{zh}:(iw-ow)/2:(ih-oh)*0.35,scale={W}:{H}:flags=lanczos[zz];"
                f"[zb][zz]overlay=0:0:enable='{en}'[zoomed]"
            )
            cur = "zoomed"

    # ---- B-roll clips
    for k, b in enumerate(job.broll):
        dur = b.end - b.start
        idx = add_input("-stream_loop", "-1", "-t", f"{dur + 0.5:.2f}", "-i", str(Path(b.path).resolve()))
        g.append(
            f"[{idx}:v]fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
            f"format=yuva420p,fade=in:st=0:d=0.2:alpha=1,fade=out:st={max(0.0, dur - 0.2):.2f}:d=0.2:alpha=1,"
            f"setpts=PTS-STARTPTS+{b.start:.3f}/TB[br{k}];"
            f"[{cur}][br{k}]overlay=0:0:eof_action=pass:enable='between(t,{b.start:.3f},{b.end:.3f})'[vb{k}]"
        )
        cur = f"vb{k}"

    # ---- emoji pop-ups
    tall = H > W
    # upper right, clear of the face, the logo and the captions
    ew = _even(W * (0.20 if tall else 0.11))
    ex = "W*0.78-w/2" if tall else "W*0.80-w/2"
    ey = "H*0.15" if tall else "H*0.16"
    for k, e in enumerate(job.emoji):
        dur = e.end - e.start
        idx = add_input("-loop", "1", "-framerate", str(fps), "-t", f"{e.end + 0.1:.2f}", "-i", str(Path(e.path).resolve()))
        g.append(
            f"[{idx}:v]scale={ew}:-2,format=rgba,"
            f"fade=in:st={e.start:.3f}:d=0.12:alpha=1,fade=out:st={max(e.start, e.end - 0.25):.3f}:d=0.25:alpha=1[em{k}];"
            f"[{cur}][em{k}]overlay={ex}:{ey}:eof_action=pass:enable='between(t,{e.start:.3f},{e.end:.3f})'[ve{k}]"
        )
        cur = f"ve{k}"

    # ---- logo watermark
    if job.logo:
        idx = add_input("-i", str(Path(job.logo).resolve()))
        lw = _even(W * (0.16 if tall else 0.10))
        m = _even(W * 0.03)
        g.append(
            f"[{idx}:v]scale={lw}:-2,format=rgba,colorchannelmixer=aa={job.logo_opacity:.2f}[logo];"
            f"[{cur}][logo]overlay=W-w-{m}:{m}[vl]"
        )
        cur = "vl"

    # ---- text: captions, hook, name, CTA
    if job.ass:
        g.append(f"[{cur}]ass=filename={SUBS_NAME}:fontsdir={FONTS_DIR}[vt]")
        cur = "vt"
    g.append(f"[{cur}]format=yuv420p[vout]")

    # ---- audio
    if info.has_audio:
        g.append(f"[0:a]aselect='{keep_a}',asetpts=N/SR/TB,aresample=48000,aformat=channel_layouts=stereo[araw]")
    else:
        g.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[araw]")
    if job.clean_audio and info.has_audio:
        g.append("[araw]highpass=f=80,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[voice]")
    else:
        g.append("[araw]anull[voice]")
    mix = ["voice"]

    if job.music:
        idx = add_input("-stream_loop", "-1", "-i", str(Path(job.music).resolve()))
        fade_out = max(0.0, total - 2.0)
        g.append(
            f"[{idx}:a]atrim=0:{total:.3f},asetpts=N/SR/TB,aresample=48000,aformat=channel_layouts=stereo,"
            f"loudnorm=I=-16:TP=-2,volume={job.music_volume:.3f},"
            f"afade=t=in:d=1.0,afade=t=out:st={fade_out:.3f}:d=2.0[mus]"
        )
        if job.ducking:
            g.append("[voice]asplit[voice2][sc];[mus][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1[musd]")
            mix = ["voice2", "musd"]
        else:
            mix.append("mus")

    sfx_inputs: dict[Path, int] = {}
    for k, (t, path) in enumerate(job.sfx):
        if t >= total:
            continue
        if path not in sfx_inputs:
            sfx_inputs[path] = add_input("-i", str(Path(path).resolve()))
        ms = int(t * 1000)
        g.append(f"[{sfx_inputs[path]}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.35,adelay={ms}|{ms}[sfx{k}]")
        mix.append(f"sfx{k}")

    if len(mix) == 1:
        g.append(f"[{mix[0]}]alimiter=limit=0.95,atrim=0:{total:.3f}[aout]")
    else:
        labels = "".join(f"[{m}]" for m in mix)
        g.append(f"{labels}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95,atrim=0:{total:.3f}[aout]")

    # sfx inputs that are reused need a split; build it after we know the counts
    graph = _split_reused(";".join(g), sfx_inputs)

    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
        *inputs,
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-crf", str(job.crf), "-preset", job.preset, "-profile:v", "high",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{total:.3f}",
        str(Path(job.out).resolve()),
    ]


def _split_reused(graph: str, sfx_inputs: dict[Path, int]) -> str:
    """An input pad can feed only one filter; add asplit for sound effects used more than once."""
    extra = []
    for idx in sfx_inputs.values():
        tag = f"[{idx}:a]"
        n = graph.count(tag)
        if n > 1:
            parts = graph.split(tag)
            rebuilt = parts[0]
            for i, p in enumerate(parts[1:]):
                rebuilt += f"[s{idx}_{i}]" + p
            graph = rebuilt
            extra.append(f"{tag}asplit={n}" + "".join(f"[s{idx}_{i}]" for i in range(n)))
    return ";".join(extra + [graph]) if extra else graph


def run(job: RenderJob, log=print) -> Path:
    cmd = build_command(job)
    job.out.parent.mkdir(parents=True, exist_ok=True)
    log(f"Rendering {job.out.name} ({job.width}x{job.height})")
    work = _prepare_workdir(job)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        raise RuntimeError(f"FFmpeg failed for {job.out.name}:\n{tail}")
    return job.out
