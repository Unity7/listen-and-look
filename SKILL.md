---
name: listen-and-look
description: "Turn a long reply, status report, plan or decision into a listen-and-look deck: the reply cut into short playable pieces (Play one, Play all, Stop, Resume, speed and voice), each paired with its picture (wide table, chart, diagram, code, or a blocker card with one-click option pills) on a follow-along stage, rendered with html_render in T3 Code (or opened as a local HTML page elsewhere). Nothing ever speaks until the user presses Play. Use when the user asks to hear or listen to a reply, wants a briefing they can play, says 'read it to me', 'chunk this', 'segment this', 'listen and look', or when a reply has a wide table, several sections, or a decision they must make. Works the same in Claude, Codex and Gemini chats."
---

# listen-and-look: playable pieces with their pictures

One page, two panes: on the left a 400 px column of pieces, each with its own Play button; on the right the stage showing the active
piece's picture. `Play all` speaks the pieces in order and the stage follows; a piece that fails to speak is marked and skipped, and
`Resume` starts again there. **Audio plays only when the user presses a Play button**: never on load, never by itself.

Files next to this one: `scripts/chunk_transform.py` (pure Python, standard library only; markdown -> deck), `resources/deck_template.html`
(the page and the player `window.cockpitPlayer`), `tests/` (pytest; the page test drives headless Chromium).

## Steps

1. Write the reply as you normally would, in markdown (headings, short paragraphs, bullets, tables, fenced code). For a decision, end with
   the blocker shape on its own lines: `Blocker:` / `Why:` / `Option 1:` .. `Option N:` / `My lean:` / `Your call:`.
2. Save it to a scratch file and build the page (any shell; `uv run --no-project python` if `python` is not on PATH):
   `python <skill>/scripts/chunk_transform.py reply.md --title "<short title>" --project <name> --html deck.html`
   For charts, diagrams or KPI tiles, write a partial deck JSON instead and pass it as the source (see "Partial deck" below).
3. In T3 Code: read `deck.html` and pass its whole text to `html_render` (title = the deck title); check with `html_preview` first when you
   changed the template or added hand-made visuals. Elsewhere: tell the user the path of `deck.html` to open in Edge or Chrome.
4. Keep your chat reply short: one line on what the deck holds and what you need from the user. Do not repeat the deck in text.

## What the transform does (deterministic, no model call)

- Cuts on blocks: each top-level list item, table, fenced code block and paragraph is a piece; a paragraph over 320 characters is cut at
  sentence ends. A heading is not a piece: it titles the pieces under it and is spoken before the first of them.
- `show_html` is safe: markdown-it-py with raw HTML off when importable, else an escape-first renderer (only `code`, bold, italics and
  http(s) links survive; `<script>` shows as text).
- `say` is clean spoken English: file paths become "file talk.py" (plus "line 42"), ISO UTC times become "11:30 AM PT" (US Pacific;
  change `TZ` and `pt_clock` in the script for another zone), raw URLs become "a link", git SHAs are dropped, `#829` is "number 829",
  markdown marks, HTML tags and pipes go.
- Tables of 4+ columns show a one-line summary and a `Table · N cols` chip in the column; the full table opens on the stage. Tables of 4+
  columns or 5+ rows are spoken as "<rows>-row table comparing <headers>"; smaller ones row by row. Code over 8 lines goes to the stage
  and is spoken as "Code block in <lang>, <k> lines: <first comment or signature>".
- A blocker becomes: Blocker + Why, one piece per option, My lean + Your call; every one of them shows the blocker card (numbered option
  pills; a click copies the reply text and fills the reply box, since the page cannot send into the chat).

## Partial deck (charts, diagrams, KPIs)

```json
{"title": "Status", "subtitle": "Oct 25 evening", "project": "my-app",
 "kpis": [{"label": "Merged today", "value": "3", "tone": "g"}, {"label": "Waiting on you", "value": "1", "tone": "a"}],
 "chunks": [
   {"md": "All three PRs merged; main is green."},
   {"md": "Cost per run fell by a third this week.",
    "visual": {"kind": "chart", "label": "Chart · cost", "title": "Cost per run", "html": "<svg viewBox='0 0 300 120'>...</svg>"}},
   {"md": "Blocker: ...\nWhy: ...\nOption 1: ...\nOption 2: ...\nMy lean: Option 1\nYour call: 1 or 2?"}
 ]}
```

`tone` is one of `g a r acc n`. A `visual.html` is your own self-contained HTML/SVG (dark theme: `#0d1117` page, `#161b22` panels,
`#21262d` lines, `#58a6ff` accent); no external URLs, scripts or fonts. A chunk may also give its own `say` (one-piece chunks only).
A full example: `resources/example_deck.json`.

## The chunk data

Deck: `{deck_id, title, subtitle, project, updated_pt, kpis: [{label, value, tone}], chunks}`. Chunk: `{id, n, kind (summary | point | table |
chart | code | blocker | decision | sofar), badge, title, show_html, say, visual: {kind, label, title, html, sheet_url?} | null, options:
[{n, label, text, lean}]}`.

## The page and the player

- Test ids: `play-all`, `play-stop`, `play-resume`, `play-speed` (0.9x-1.5x), `play-voice` (`speechSynthesis.getVoices()`, an en-US
  "Natural" voice preferred), `talk-chunk[data-chunk][data-say]`, `chunk-play`, `chunk-visual`, `sheet` (`#sheet-slot[data-id][data-kind]`),
  `sheet-pin` (`aria-pressed`), `option-pill`, `reply-box`.
- One `SpeechSynthesisUtterance` per piece; `onend` moves on; `onerror` or a stall (watchdog: 2x the expected length + 4 s, at least 8 s)
  marks the piece `data-play-error="1"` and moves on; when the queue ends, `Resume` starts at the first failed piece. `Stop` cancels at
  once and `Resume` starts at the stopped piece. The playing piece has `data-playing="1"`.
- The stage follows the playing piece unless `Pin visual` is pressed; a click on a piece or its chip always opens it (a click is an ask).
- Test hooks: `window.__cockpitSynthOverride` (an object with `speak(u)`, `cancel()`, `getVoices()`), `window.__cockpitUtteranceCtor`,
  and `window.__cockpitSpoken` (every utterance started: `{id, text}`; empty after load). See `tests/test_deck_page.py`.
- Speed and voice are remembered in `localStorage` when the frame allows it. If the view has no speech engine, a note says so and the text
  and pictures still work.

## Run the tests

From this folder: `uv run --no-project --with pytest --with playwright pytest -q tests` (run `uv run --no-project --with playwright
playwright install chromium` once first; add `--with markdown-it-py` to cover the markdown-it path too).
