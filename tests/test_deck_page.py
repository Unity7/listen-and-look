"""listen-and-look M1: the deck page in a real (headless) Chromium: nothing speaks on load, Play all skips a failing piece and finishes the
rest, Resume starts at the failed piece, the stage follows unless pinned. Speech goes through the page's `window.__cockpitSynthOverride` hook
so the test needs no sound device."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("chunk_transform", HERE.parent / "scripts" / "chunk_transform.py")
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)
sync_api = pytest.importorskip("playwright.sync_api")

# chunk 2 ("fail") errors; every other utterance ends after 20 ms
FAKE_SYNTH = """
window.__fails = new Set(["d-2"]);
window.__cockpitUtteranceCtor = function (text) { this.text = text; };
window.__cockpitSynthOverride = {
  speaking: false, pending: false, queue: [],
  getVoices: function () { return [{name: "Test Natural", lang: "en-US"}]; },
  cancel: function () { var q = this.queue.splice(0); q.forEach(function (u) { u.onerror && u.onerror({error: "interrupted"}); }); this.speaking = false; },
  speak: function (u) {
    var self = this, spoken = window.__cockpitSpoken, id = spoken[spoken.length - 1].id;
    self.queue.push(u); self.speaking = true;
    setTimeout(function () {
      var i = self.queue.indexOf(u); if (i < 0) return; self.queue.splice(i, 1); self.speaking = false;
      if (window.__fails.has(id)) u.onerror && u.onerror({error: "synthesis-failed"}); else u.onend && u.onend();
    }, 20);
  }
};
"""


@pytest.fixture(scope="module")
def page_file(tmp_path_factory):
    md = ("## Plan\nFirst piece of the plan.\n\n| a | b | c | d |\n|---|---|---|---|\n| 1 | 2 | 3 | 4 |\n\n- third piece\n- fourth piece")
    deck = ct.build_deck(ct.chunk_markdown(md, "d"), "Test deck", project="my-app", now=datetime(2026, 10, 25, 18, 30, tzinfo=UTC))
    p = tmp_path_factory.mktemp("deck") / "deck.html"
    p.write_text(ct.render_html(deck), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"no chromium for playwright: {e}")
        yield b
        b.close()


def _open(browser, page_file):
    pg = browser.new_page(viewport={"width": 1100, "height": 800})
    pg.add_init_script(FAKE_SYNTH)
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(page_file.as_uri())
    return pg, errors


def test_silent_on_load_then_play_all_skips_failure(browser, page_file):
    pg, errors = _open(browser, page_file)
    pg.wait_for_timeout(300)
    assert pg.evaluate("window.__cockpitSpoken.length") == 0
    assert pg.locator('[data-testid="talk-chunk"]').count() == 4
    assert pg.locator('[data-testid="chunk-visual"]').count() == 1
    pg.click('[data-testid="play-all"]')
    pg.wait_for_function("document.querySelector('[data-testid=play-status]').textContent.indexOf('could not play') >= 0", timeout=5000)
    assert pg.evaluate("window.__cockpitSpoken.map(s => s.id)") == ["d-1", "d-2", "d-3", "d-4"]
    assert pg.get_attribute('[data-chunk="d-2"]', "data-play-error") == "1"
    assert pg.get_attribute('[data-chunk="d-3"]', "data-play-error") is None
    assert pg.evaluate("window.cockpitPlayer.resumeId") == "d-2"
    assert pg.is_enabled('[data-testid="play-resume"]')
    assert pg.get_attribute("#sheet-slot", "data-id") == "d-4"  # the stage followed to the last piece
    assert pg.evaluate("window.__cockpitSpoken[0].text") == "Plan. First piece of the plan."
    pg.evaluate("window.__fails.clear()")
    pg.click('[data-testid="play-resume"]')
    pg.wait_for_function("document.querySelector('[data-testid=play-status]').textContent === 'Done.'", timeout=5000)
    assert pg.evaluate("window.__cockpitSpoken.slice(4).map(s => s.id)") == ["d-2", "d-3", "d-4"]
    assert pg.get_attribute('[data-chunk="d-2"]', "data-play-error") is None
    assert errors == []


def test_pin_holds_the_stage_and_click_opens(browser, page_file):
    pg, errors = _open(browser, page_file)
    pg.click('[data-chunk="d-2"] [data-testid="chunk-visual"]')
    assert pg.get_attribute("#sheet-slot", "data-id") == "d-2" and pg.get_attribute("#sheet-slot", "data-kind") == "table"
    assert pg.locator("#st-body table").count() == 1
    pg.click('[data-testid="sheet-pin"]')
    assert pg.get_attribute('[data-testid="sheet-pin"]', "aria-pressed") == "true"
    pg.evaluate("window.__fails.clear()")
    pg.click('[data-chunk="d-3"] [data-testid="chunk-play"]')
    pg.wait_for_function("document.querySelector('[data-testid=play-status]').textContent === 'Done.'", timeout=5000)
    assert pg.evaluate("window.__cockpitSpoken.map(s => s.id)") == ["d-3"]
    assert pg.get_attribute("#sheet-slot", "data-id") == "d-2"  # pinned: playback did not move it
    assert errors == []


def test_stop_remembers_spot(browser, page_file):
    pg, errors = _open(browser, page_file)
    pg.evaluate("() => { window.__fails.clear(); window.__cockpitSynthOverride.speak = function (u) { this.queue.push(u); this.speaking = true; }; }")  # never ends
    pg.click('[data-testid="play-all"]')
    pg.click('[data-testid="play-stop"]')
    assert pg.evaluate("window.cockpitPlayer.resumeId") == "d-1"
    assert pg.locator('[data-playing="1"]').count() == 0 and pg.locator('[data-play-error="1"]').count() == 0
    assert errors == []
