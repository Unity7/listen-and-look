"""listen-and-look M1: the spoken-text normalizer, the deterministic chunker and the deck page (no browser here; see test_deck_page.py)."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("chunk_transform", HERE.parent / "scripts" / "chunk_transform.py")
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


@pytest.fixture(autouse=True)
def builtin_renderer(monkeypatch):
    monkeypatch.setattr(ct, "_MD", None)  # the stdlib path every agent has; markdown-it-py is checked separately below


REPLY = """## Where the app stands
| Step | Files | Owner | State | Proof |
|---|---|---|---|---|
| S1 | chunks.py | builder | open | none |
| S2 | listen.js | builder | open | none |

- First see `C:/Users/me/projects/my-app/pages/talk.py` at 2026-10-25T18:30:00Z.
- Then app/static/listen.js:42 (commit 5564a94d) per https://github.com/example/my-app/pull/829
"""


def test_spec_example_say():
    assert ct.spoken("See C:/Users/me/projects/my-app/pages/talk.py at 2026-10-25T18:30:00Z") == "See file talk.py at 11:30 AM PT"


@pytest.mark.parametrize(("raw", "want"), [
    ("Open a/b/foo.py:42.", "Open file foo.py line 42."),
    (r"Saved to C:\Users\me\out\deck.html, done", "Saved to file deck.html, done"),
    ("Look in C:/Users/me/projects/my-app/ now", "Look in folder my-app now"),
    ("Merged 5564a94d into main (#829)", "Merged into main (number 829)"),
    ("See [the PR](https://x.y/z) and https://example.com/a?b=1 too", "See the PR and a link too"),
    ("**Bold** and *em* and `code` and ~~gone~~", "Bold and em and code and gone"),
    ("S1 -> S2 | S3", "S1 to S2, S3"),
    ("Winter: 2026-12-01T20:05:00Z", "Winter: 12:05 PM PT"),
    ("Midnight 2026-07-01T07:00:00+00:00", "Midnight 12:00 AM PT"),
    ("dates like 10/25 and and/or stay", "dates like 10/25 and and/or stay"),
    ("C37 and SC-72 stay", "C37 and SC-72 stay"),
])
def test_spoken(raw, want):
    assert ct.spoken(raw) == want


def test_pt_without_tzdata(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_zoneinfo(name, *a, **k):
        if name == "zoneinfo":
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_zoneinfo)
    assert ct.pt_clock(datetime(2026, 10, 25, 18, 30, tzinfo=UTC)) == "11:30 AM PT"  # PDT
    assert ct.pt_clock(datetime(2026, 11, 2, 18, 30, tzinfo=UTC)) == "10:30 AM PT"  # PST after Nov 1
    assert ct.pt_clock(datetime(2026, 3, 8, 9, 59, tzinfo=UTC)) == "1:59 AM PT"  # just before the March switch
    assert ct.pt_clock(datetime(2026, 3, 8, 10, 0, tzinfo=UTC)) == "3:00 AM PT"


def test_table_say():
    assert ct.table_say(["A", "B", "C", "D"], [["1", "2", "3", "4"]] * 2) == "2-row table comparing A, B, C and D."
    assert ct.table_say(["Name", "State"], [["x"]] * 5) == "5-row table comparing Name and State."
    assert ct.table_say(["Name", "State"], [["S1", "`open`"], ["S2", "done"]]) == "Table. Name: S1, State: open; Name: S2, State: done."


def test_code_say():
    assert ct.code_say("python", ["# build the deck", "x = 1", ""]) == "Code block in python, 3 lines: build the deck."
    assert ct.code_say("", ["def run(a, b):"]) == "Code block in plain text, 1 line: def run(a, b):."


def test_chunk_reply_heading_titles_and_wide_table_chip():
    chunks = ct.chunk_markdown(REPLY, "42")
    assert [c["id"] for c in chunks] == ["42-1", "42-2", "42-3"]
    table, first, second = chunks
    assert table["kind"] == "table" and table["title"] == "Where the app stands"
    assert table["visual"]["label"] == "Table · 5 cols" and "<table" in table["visual"]["html"]
    assert "<table" not in table["show_html"]  # wide: a one-line summary in the 400 px column
    assert table["say"] == "Where the app stands. 2-row table comparing Step, Files, Owner, State and Proof."
    assert first["say"] == "First see file talk.py at 11:30 AM PT."
    assert second["say"] == "Then file listen.js line 42 (commit) per a link"
    for c in chunks:
        assert "C:/" not in c["say"] and "|" not in c["say"] and "http" not in c["say"]


def test_narrow_table_inline_and_code_rules():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\n" + "\n".join(f"x{i} = {i}" for i in range(10)) + "\n```\n\n```sh\nls\n```"
    t, long_code, short_code = ct.chunk_markdown(md, "m")
    assert "<table" in t["show_html"] and t["visual"] is None
    assert long_code["visual"]["kind"] == "code" and long_code["visual"]["label"] == "Code · 10 lines"
    assert "<pre>" in short_code["show_html"] and short_code["visual"] is None


def test_long_paragraph_splits_at_sentences():
    para = " ".join(f"Sentence number {i} says a little more about the plan." for i in range(12))
    chunks = ct.chunk_markdown(para, "p")
    assert len(chunks) >= 2 and all(len(c["say"]) <= ct.PARA_MAX for c in chunks)
    assert chunks[0]["kind"] == "summary" and chunks[1]["kind"] == "point"


def test_list_item_keeps_nested_lines():
    chunks = ct.chunk_markdown("- top one\n  - nested a\n  - nested b\n- top two", "l")
    assert len(chunks) == 2 and "nested b" in chunks[0]["show_html"]


def test_xss_is_escaped():
    chunks = ct.chunk_markdown("<script>alert(1)</script> and [x](javascript:alert(1))\n\n| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | 2 |", "x")
    blob = json.dumps(chunks)
    assert "<script>" not in blob and "<img" not in blob and "javascript:" not in "".join(c["show_html"] for c in chunks)
    assert "&lt;script&gt;" in chunks[0]["show_html"]


def test_markdown_it_path_is_safe_too(monkeypatch):
    mdit = pytest.importorskip("markdown_it")
    monkeypatch.setattr(ct, "_MD", mdit.MarkdownIt("commonmark", {"html": False}).enable("table"))
    c = ct.chunk_markdown("<script>alert(1)</script> **bold**", "x")[0]
    assert "<script>" not in c["show_html"] and "<strong>bold</strong>" in c["show_html"]


BLOCKER = """I checked the sheet route first.

**Blocker:** The app needs a new dependency (markdown-it-py).
**Why:** the standard library has no markdown parser.
**Option 1:** add markdown-it-py to app/pyproject.toml
**Option 2:** keep the escape-first renderer
**My lean:** Option 1, it is the safe parser.
**Your call:** 1 or 2?
"""


def test_blocker_chunks_and_card():
    chunks = ct.chunk_text(BLOCKER, "wait")
    kinds = [c["kind"] for c in chunks]
    assert kinds == ["summary", "blocker", "decision", "decision", "decision"]
    blocker = chunks[1]
    assert blocker["say"] == "Blocker: The app needs a new dependency (markdown-it-py). Why: the standard library has no markdown parser."
    assert [o["n"] for o in blocker["options"]] == [1, 2] and blocker["options"][0]["lean"] is True
    assert chunks[2]["say"] == "Option 1: add markdown-it-py to file pyproject.toml."
    assert chunks[4]["say"] == "My lean: Option 1, it is the safe parser. Your call: 1 or 2?"
    card = blocker["visual"]["html"]
    assert blocker["visual"]["label"] == "Blocker · 2 options"
    assert card.count('data-testid="option-pill"') == 2 and 'data-option="1"' in card and "my lean" in card
    assert all(c["visual"] is blocker["visual"] for c in chunks[1:])


def test_not_a_blocker_without_second_field():
    assert ct.chunk_blocker("Blocker: only this line") is None


def test_deck_from_spec_and_page(tmp_path):
    spec_in = {"title": "Kit status", "project": "my-app", "kpis": [{"label": "Merged", "value": "3", "tone": "g"}],
               "source": "s", "chunks": [{"md": "All three PRs merged."},
                          {"md": "Cost went down.", "visual": {"kind": "chart", "label": "Chart · cost", "title": "Cost", "html": "<svg></svg>"}},
                          {"md": "</script><script>alert(1)</script>"}]}
    deck = ct.deck_from_spec(spec_in, now=datetime(2026, 10, 25, 22, 45, tzinfo=UTC))
    assert deck["updated_pt"] == "3:45 PM PT" and deck["deck_id"] == "kit-status"
    assert [c["n"] for c in deck["chunks"]] == [1, 2, 3] and deck["chunks"][1]["visual"]["kind"] == "chart"
    page = ct.render_html(deck)
    assert ct.PLACEHOLDER not in page
    data = re.search(r'<script id="deck-data" type="application/json">(.*?)</script>', page, re.DOTALL).group(1)
    assert json.loads(data) == json.loads(json.dumps(deck))  # the planted </script> did not close the tag
    out = tmp_path / "deck.html"
    assert ct.main([str(_write(tmp_path / "in.json", json.dumps(spec_in))), "--html", str(out)]) == 0
    assert out.read_text(encoding="utf-8").count('id="deck-data"') == 1


def test_template_contract():
    page = ct.TEMPLATE.read_text(encoding="utf-8")
    for tid in ("play-all", "play-stop", "play-resume", "play-speed", "play-voice", "sheet-pin", "talk-chunk", "chunk-play", "chunk-visual"):
        assert f'"{tid}"' in page, tid
    for rate in ("0.9", "1.15", "1.3", "1.5"):
        assert f'value="{rate}"' in page
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", page)  # self-contained: no CDN
    assert "__cockpitSynthOverride" in page and "__cockpitSpoken" in page and "window.cockpitPlayer" in page
    assert "flex:0 0 400px" in page and "#0d1117" in page


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p
