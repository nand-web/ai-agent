# AI Video Editor (talking-head / testimonial)

Raw video upload karo. Agent khud edit karke do versions deta hai:

- **YouTube** 16:9 (1080p, ya 4K source par 4K)
- **Reel** 9:16, testimonial ka sabse strong 30–60 second hissa

## Kya-kya karta hai

| Feature | On/off |
|---|---|
| "umm / aaa" aur lambe pause hatana | ✅ |
| Galat shuru hue aur repeat sentences hatana (AI) | ✅ |
| Cut ke baad halka zoom (jump-cut smooth) | ✅ |
| Captions: Bold pop (word-by-word) ya Minimal | ✅ |
| Hook text pehle 3 sec (CAPS wala word highlight) | ✅ |
| Naam + title lower-third | ✅ |
| End CTA | ✅ |
| Logo watermark | ✅ |
| Awaaz saaf karna + loudness normalize (-16 LUFS) | ✅ |
| Background music + auto-ducking + fade in/out | ✅ |
| Sound effects (whoosh, pop) | ✅ |
| Emoji pop-ups | ✅ |
| B-roll stock clips | ✅ |
| Reel mein chehra frame ke beech mein (face detection) | auto |

Aage aane wala (phase 2): split-screen layouts, process steps aur stat graphics (mockup wale).

## Setup

FFmpeg aur **Python 3.10–3.12** chahiye. Sabse naye Python par Whisper ka `onnxruntime` package abhi install nahi hota.

Mac:

```bash
xcode-select --install
brew install python@3.12 ffmpeg
python3.12 -m venv .venv
```

Doosre system:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional keys:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # AI edit plan (retakes, hook, reel, B-roll choice)
export PEXELS_API_KEY=...             # free stock B-roll from pexels.com/api
```

Bina keys ke bhi chalega: tab simple rules se plan banta hai.

## Chalana

Web UI:

```bash
streamlit run app.py
```

Command line:

```bash
python -m videoagent raw.mp4 --name "Rahul Mehta" --title "Founder, FitBox Gym" --logo logo.png
```

Saare options: `python -m videoagent --help`.

## Apne assets

- `assets/music/<mood>/` mein royalty-free tracks daalo (jaise `upbeat/`, `piano/`, `lofi/`). YouTube Audio Library ya Pixabay Music se free milte hain.
- `assets/broll/` mein apne clips daalo; file ka naam keyword hota hai (jaise `gym-workout.mp4`).
- `assets/sfx/whoosh.wav`, `assets/sfx/pop.wav` daalo to woh use honge; warna built-in sound bante hain.

## Kaise kaam karta hai

```
raw video → Whisper (word timing) → Claude edit plan → cuts
          → text overlays (Pillow PNG) → FFmpeg: framing + zoom + B-roll + emoji + logo + text
          → audio: denoise + loudnorm + music ducking + sfx → MP4 (H.264)
```

Kisi bhi normal FFmpeg build par chalta hai (libass ya libx264 zaroori nahi). iPhone HDR video
automatically normal rangon mein convert hoti hai. Kai takes ek saath upload kar sakte ho.

Code: `videoagent/` (`pipeline.py` se shuru karo). Tests: `pytest`.
