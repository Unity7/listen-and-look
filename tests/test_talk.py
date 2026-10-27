"""Talk mode round trip without a speaker or microphone: a voice writes a sentence to a .wav, Whisper reads it back; and a deck page built
with made audio. Runs only where `uv` and the models (`uv run scripts/talk.py setup`) are present; Sonia also needs internet."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
TALK = SCRIPTS / "talk.py"
HOME = Path(os.environ.get("LISTEN_AND_LOOK_HOME") or Path.home() / ".cache" / "listen-and-look")
pytestmark = pytest.mark.skipif(not (shutil.which("uv") and (HOME / "kokoro" / "voices-v1.0.bin").exists()),
                                reason="needs uv and `talk.py setup`")


def _talk(*args: str, stdin: str | None = None) -> str:
    done = subprocess.run(["uv", "run", "--quiet", str(TALK), *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", timeout=300, check=True)
    return done.stdout.strip()


@pytest.mark.parametrize("voice", ["en-GB-SoniaNeural", "bf_emma"])  # the default (Microsoft, online) and the offline fallback (Kokoro)
def test_say_then_listen_round_trip(tmp_path, voice):
    wav = tmp_path / "say.wav"
    _talk("say", "--voice", voice, "--out", str(wav), stdin="The **build** passed. See `C:/Users/me/app/main.py` for details.\n")
    assert wav.stat().st_size > 10_000
    heard = json.loads(_talk("listen", "--wav", str(wav)))
    text = heard["text"].lower()
    assert heard["heard"] and "build passed" in text and "main" in text
    assert "users" not in text and "c:" not in text  # the path was spoken as "file main.py", not read out


def _unpng(png: bytes) -> bytes:
    """Inverse of talk._png (one IDAT, filter 0 rows), as the page does with a canvas."""
    w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    i = png.index(b"IDAT")
    raw = zlib.decompress(png[i + 4:i + 4 + int.from_bytes(png[i - 4:i], "big")])
    rgb = b"".join(raw[y * (w * 3 + 1) + 1:(y + 1) * (w * 3 + 1)] for y in range(h))
    return rgb[3:3 + int.from_bytes(rgb[:3], "big")]


def test_deck_page_gets_sonia_audio(tmp_path):
    (tmp_path / "reply.md").write_text("## Status\nThe build passed.\n\n- Two pull requests merged.\n", encoding="utf-8")
    page = tmp_path / "deck.html"
    subprocess.run([sys.executable, str(SCRIPTS / "chunk_transform.py"), str(tmp_path / "reply.md"), "--html", str(page)], check=True,
                   timeout=300)
    deck = json.loads(page.read_text(encoding="utf-8").split('id="deck-data" type="application/json">')[1].split("</script>")[0])
    assert deck["voice"] == "Sonia" and len(deck["chunks"]) == 2
    for c in deck["chunks"]:
        mp3 = (tmp_path / c["audio"]["src"]).read_bytes()
        assert len(mp3) > 2_000 and _unpng(Path(c["audio"]["png"]).read_bytes()) == mp3
