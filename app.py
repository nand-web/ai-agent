"""Web UI: streamlit run app.py"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from videoagent.config import ASSETS, EditOptions
from videoagent.pipeline import edit
from videoagent.planner import have_api_key

st.set_page_config(page_title="AI Video Editor", page_icon="🎬", layout="wide")
st.title("AI Video Editor")
st.caption("Raw talking-head ya testimonial video upload karo. Agent cut, captions, music aur graphics laga ke YouTube aur Reel version banayega.")

WORK = Path(tempfile.gettempdir()) / "videoagent"
WORK.mkdir(exist_ok=True)


def save_upload(f, sub: str) -> str:
    if not f:
        return ""
    d = WORK / sub
    d.mkdir(exist_ok=True)
    p = d / f.name
    p.write_bytes(f.getbuffer())
    return str(p)


moods = sorted(p.name for p in (ASSETS / "music").iterdir() if p.is_dir()) or ["upbeat"]

with st.sidebar:
    st.header("Edit options")
    formats = st.multiselect("Format", ["youtube", "reel"], default=["youtube", "reel"],
                             format_func=lambda f: {"youtube": "YouTube 16:9", "reel": "Reel 9:16"}[f])
    reel_s = st.slider("Reel max length (sec)", 15, 90, 60)

    st.subheader("Cleanup")
    fillers = st.toggle("Umm / aaa hatao", True)
    silence = st.toggle("Lambe pause chhote karo", True)
    retakes = st.toggle("Galat / repeat lines hatao (AI)", True)
    zoom = st.toggle("Cut ke baad halka zoom", True)

    st.subheader("Captions")
    captions = st.toggle("Captions", True)
    cap_style = st.radio("Style", ["bold", "minimal"], horizontal=True, disabled=not captions,
                         format_func=lambda s: {"bold": "Bold pop", "minimal": "Minimal"}[s])

    st.subheader("Text")
    hook = st.toggle("Hook (pehle 3 sec)", True)
    hook_text = st.text_input("Hook text (khali = AI likhega)", "", disabled=not hook, help="CAPS wala word yellow highlight hoga")
    lt = st.toggle("Naam aur title", True)
    name = st.text_input("Naam", "", disabled=not lt)
    title = st.text_input("Title / company", "", disabled=not lt)
    cta = st.toggle("End CTA", True)
    cta_text = st.text_input("CTA text (khali = AI likhega)", "", disabled=not cta)

    st.subheader("Branding")
    logo = st.file_uploader("Logo watermark (PNG)", type=["png", "jpg", "jpeg"])

    st.subheader("Audio")
    clean = st.toggle("Awaaz saaf + loudness theek karo", True)
    music = st.toggle("Background music", True)
    music_file = st.file_uploader("Apna music (optional)", type=["mp3", "wav", "m4a"], disabled=not music)
    mood = st.selectbox("Mood (assets/music/ folder)", moods, disabled=not music)
    vol = st.slider("Music volume", 0.05, 0.5, 0.18, 0.01, disabled=not music)
    duck = st.toggle("Auto-ducking (bolte waqt music dheema)", True, disabled=not music)
    sfx = st.toggle("Sound effects (whoosh / pop)", True)

    st.subheader("Visuals")
    emoji = st.toggle("Emoji pop-ups", True)
    broll = st.toggle("B-roll stock clips", True, help="assets/broll/ ke clips, ya PEXELS_API_KEY set ho to Pexels se")

    st.subheader("Quality")
    resolution = st.radio("Resolution", ["1080p", "4k"], horizontal=True,
                          help="4K sirf 4K video par, aur 4-5 guna zyada time leta hai")
    crf = st.slider("Quality (kam = behtar)", 14, 26, 18)
    whisper = st.selectbox("Transcription model", ["small", "medium", "large-v3", "base"], help="bada model = zyada accurate, zyada time")

videos = st.file_uploader(
    "Raw video (ek ya zyada takes)", type=["mp4", "mov", "m4v", "mkv", "webm"], accept_multiple_files=True,
    help="Alag-alag takes ek saath daal sakte ho. Agent unhe jodega aur repeat lines ka sirf behtar take rakhega.",
)
order: list = []
if videos and len(videos) > 1:
    names = [v.name for v in videos]
    picked = st.multiselect("Takes ka order (upar se neeche)", names, default=sorted(names))
    order = [next(v for v in videos if v.name == n) for n in picked]
elif videos:
    order = list(videos)
if not have_api_key():
    st.info("ANTHROPIC_API_KEY set nahi hai: AI ki jagah simple rules chalenge. Umm, pause aur repeat lines phir bhi hatengi, "
            "lekin B-roll khud nahi chunega aur hook transcript se banega.")

if order and st.button("Edit video", type="primary", disabled=not formats):
    srcs = [Path(save_upload(v, "in")) for v in order]
    src = str(srcs[0])
    opts = EditOptions(
        formats=formats, reel_max_seconds=reel_s,
        remove_fillers=fillers, remove_silence=silence, remove_retakes=retakes, jump_zoom=zoom,
        captions=captions, caption_style=cap_style,
        hook=hook, hook_text=hook_text, lower_third=lt and bool(name), person_name=name, person_title=title,
        cta=cta, cta_text=cta_text,
        logo_path=save_upload(logo, "logo"),
        clean_audio=clean, music=music, music_path=save_upload(music_file, "music"), music_mood=mood,
        music_volume=vol, ducking=duck, sound_effects=sfx,
        emoji=emoji, broll=broll, resolution=resolution, crf=crf, whisper_model=whisper,
    )
    out_dir = WORK / "out" / Path(src).stem
    lines: list[str] = []
    box = st.empty()

    def log(msg: str) -> None:
        lines.append(msg)
        box.code("\n".join(lines[-14:]))

    with st.spinner("Editing... (lambi video mein kuch minute lagenge)"):
        try:
            result = edit(srcs if len(srcs) > 1 else srcs[0], opts, out_dir, log=log)
        except Exception as e:
            st.error(f"Edit fail hua: {e}")
            st.stop()
    st.session_state["result"] = result

result = st.session_state.get("result")
if result:
    st.success("Video ready!")
    cols = st.columns(len(result["outputs"]))
    for col, (fmt, path) in zip(cols, result["outputs"].items()):
        with col:
            st.subheader({"youtube": "YouTube 16:9", "reel": "Reel 9:16"}.get(fmt, fmt))
            st.video(path)
            st.download_button("Download", Path(path).read_bytes(), file_name=Path(path).name, mime="video/mp4", key=f"dl-{fmt}")
    plan = result["plan"]
    with st.expander("AI edit plan"):
        st.write(f"Source: **{plan['source']}**")
        if plan.get("hook_options"):
            st.write("Hook suggestions:", plan["hook_options"])
        if plan.get("title"):
            st.write("YouTube title:", plan["title"])
        if plan.get("notes"):
            st.write(plan["notes"])
        st.code(json.dumps(plan, ensure_ascii=False, indent=1), language="json")
