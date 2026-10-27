# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["faster-whisper>=1.1", "kokoro-onnx>=0.4", "sounddevice>=0.5", "numpy"]
# ///
"""listen-and-look talk mode: speak a reply in a natural local voice and hear the user's answer, so an agent can hold a spoken
conversation one turn at a time.

Everything runs on this computer: Kokoro (kokoro-onnx) speaks, faster-whisper transcribes, a simple loudness check finds where speech
starts and stops (the same approach and values as Row-Bot's voice mode). The microphone is open only while `listen` or `turn` runs.

  uv run talk.py setup                       # download the voice and speech models once (~650 MB)
  uv run talk.py say "Hi there"              # speak (text from the argument, or stdin when none is given)
  uv run talk.py listen [--wait 60]          # wait for speech, print {"heard": bool, "text": "..."}
  uv run talk.py turn < reply.txt            # say, then listen: one conversational turn in one call
  uv run talk.py say "Hi" --out hi.wav       # write the voice to a file instead of playing it
  uv run talk.py listen --wav hi.wav         # transcribe a file instead of the microphone
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import wave
from collections import deque
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # model downloads: no Windows symlink or token nags
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
sys.path.insert(0,str(Path(__file__).resolve().parent))
from chunk_transform import spoken  # noqa: E402 - same cleanup as the deck: paths, URLs, SHAs and markdown never get read aloud

HOME = Path(os.environ.get("LISTEN_AND_LOOK_HOME") or Path.home() / ".cache" / "listen-and-look")
KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_FILES = ("kokoro-v1.0.fp16.onnx", "voices-v1.0.bin")
VOICE = "af_heart"
WHISPER = "small"

RATE = 16_000  # Whisper wants 16 kHz mono
CHUNK = 1280  # 80 ms
PRE_CHUNKS = 8  # ~640 ms kept from before speech starts
LOUD = 300  # mean absolute level (16-bit) that counts as speech
SILENCE_S = 1.5  # this much quiet after speech ends the utterance
MAX_S = 30  # one utterance at most
MIN_LOUD = 5  # ~400 ms of loud audio, else it was a click or a cough
GRACE_S = 0.6  # ignore the first moment so the end of our own voice is not heard


def _out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- models

def setup() -> None:
    (HOME / "kokoro").mkdir(parents=True, exist_ok=True)
    for name in KOKORO_FILES:
        dest = HOME / "kokoro" / name
        if not dest.exists():
            print(f"downloading {name} ...", file=sys.stderr, flush=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            urllib.request.urlretrieve(f"{KOKORO_BASE}/{name}", tmp)
            tmp.replace(dest)
    _whisper(WHISPER)  # faster-whisper downloads its model on first load
    _out({"ready": True, "models": str(HOME)})


def _kokoro():
    from kokoro_onnx import Kokoro

    model, voices = (HOME / "kokoro" / n for n in KOKORO_FILES)
    if not (model.exists() and voices.exists()):
        sys.exit("voice model missing: run `uv run talk.py setup` once")
    return Kokoro(str(model), str(voices))


def _whisper(size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(size, device="cpu", compute_type="int8", download_root=str(HOME / "whisper"))


# ---------------------------------------------------------------- speak

def say(text: str, voice: str, speed: float, out: str | None, raw: bool) -> None:
    line = text if raw else " ".join(spoken(p) for p in text.splitlines() if p.strip())
    if not line.strip():
        return
    lang = "en-gb" if voice.startswith("b") else "en-us"
    samples, rate = _kokoro().create(line, voice=voice, speed=speed, lang=lang)
    if out:
        _write_wav(out, samples, rate)
        return
    import sounddevice as sd

    sd.play(samples, rate)
    sd.wait()


def _write_wav(path: str, samples, rate: int) -> None:
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- listen

def _record(wait_s: float):
    """Microphone audio of one utterance (16 kHz int16), or None when nobody spoke within `wait_s` seconds."""
    import queue

    import numpy as np
    import sounddevice as sd

    q: queue.Queue = queue.Queue()
    pre: deque = deque(maxlen=PRE_CHUNKS)
    frames: list = []
    started, loud_n, last, t_start = False, 0, 0.0, 0.0
    t0 = time.monotonic()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=lambda d, *_: q.put(d[:, 0].copy())):
        while True:
            chunk = q.get(timeout=10)
            now = time.monotonic()
            if now - t0 < GRACE_S:
                continue
            loud = float(np.abs(chunk.astype(np.float32)).mean()) >= LOUD
            if not started:
                pre.append(chunk)
                if loud:
                    started, frames, loud_n, last, t_start = True, list(pre), 1, now, now
                elif now - t0 > wait_s:
                    return None
                continue
            frames.append(chunk)
            if loud:
                loud_n, last = loud_n + 1, now
            if now - last >= SILENCE_S or now - t_start >= MAX_S:
                if loud_n >= MIN_LOUD:
                    return np.concatenate(frames)
                started = False  # a click, not speech: keep waiting
                pre.clear()
                if now - t0 > wait_s:
                    return None


def _read_wav(path: str):
    import numpy as np

    with wave.open(path, "rb") as w:
        rate, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(n), dtype=np.int16).reshape(-1, ch)[:, 0]
    if rate != RATE:  # e.g. Kokoro's 24 kHz output in tests
        pcm = np.interp(np.arange(0, len(pcm), rate / RATE), np.arange(len(pcm)), pcm).astype(np.int16)
    return pcm


def listen(wait_s: float, wav: str | None, model: str) -> None:
    audio = _read_wav(wav) if wav else _record(wait_s)
    if audio is None:
        _out({"heard": False, "text": ""})
        return
    f32 = audio.astype("float32") / 32768.0
    segs, _ = _whisper(model).transcribe(f32, beam_size=5, language="en", vad_filter=True)
    text = " ".join(s.text.strip() for s in segs).strip()
    _out({"heard": bool(text), "text": text})


# ---------------------------------------------------------------- CLI

def main() -> None:
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to a code page
    ap =argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    for name in ("say", "turn"):
        p = sub.add_parser(name)
        p.add_argument("text", nargs="?", help="what to say (default: read stdin)")
        p.add_argument("--voice", default=VOICE, help="Kokoro voice, e.g. af_heart, af_bella, am_michael, bf_emma")
        p.add_argument("--speed", type=float, default=1.0)
        p.add_argument("--raw", action="store_true", help="speak the text as given, without the deck's cleanup")
        if name == "say":
            p.add_argument("--out", help="write a .wav here instead of playing")
    for name in ("listen", "turn"):
        p = sub.choices.get(name) or sub.add_parser(name)
        p.add_argument("--wait", type=float, default=60, help="give up after this many seconds without speech")
        p.add_argument("--model", default=WHISPER, help="Whisper size: tiny, base, small, medium")
        if name == "listen":
            p.add_argument("--wav", help="transcribe this file instead of the microphone")
    a = ap.parse_args()
    if a.cmd == "setup":
        setup()
        return
    if a.cmd in ("say", "turn"):
        text = a.text if a.text is not None else sys.stdin.read()
        say(text, a.voice, a.speed, getattr(a, "out", None), a.raw)
    if a.cmd in ("listen", "turn"):
        listen(a.wait, getattr(a, "wav", None), a.model)


if __name__ == "__main__":
    main()
