"""Talk mode round trip without a speaker or microphone: Kokoro writes a sentence to a .wav, Whisper reads it back. Runs only where
`uv` and the models (`uv run scripts/talk.py setup`) are present."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TALK = Path(__file__).resolve().parent.parent / "scripts" / "talk.py"
HOME = Path(os.environ.get("LISTEN_AND_LOOK_HOME") or Path.home() / ".cache" / "listen-and-look")
pytestmark = pytest.mark.skipif(not (shutil.which("uv") and (HOME / "kokoro" / "voices-v1.0.bin").exists()),
                                reason="needs uv and `talk.py setup`")


def _talk(*args: str, stdin: str | None = None) -> str:
    done = subprocess.run(["uv", "run", "--quiet", str(TALK), *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", timeout=300, check=True)
    return done.stdout.strip()


def test_say_then_listen_round_trip(tmp_path):
    wav = tmp_path / "say.wav"
    _talk("say", "--out", str(wav), stdin="The **build** passed. See `C:/Users/me/app/main.py` for details.\n")
    assert wav.stat().st_size > 10_000
    heard = json.loads(_talk("listen", "--wav", str(wav)))
    text = heard["text"].lower()
    assert heard["heard"] and "build passed" in text and "main" in text
    assert "users" not in text and "c:" not in text  # the path was spoken as "file main.py", not read out
