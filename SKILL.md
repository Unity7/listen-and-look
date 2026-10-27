---
name: listen-and-look
description: "Turn a long reply, status report, plan or decision into a listen-and-look deck: the reply cut into short playable pieces (Play one, Play all, Stop, Resume, speed and voice), each paired with its picture (wide table, chart, diagram, code, or a blocker card with one-click option pills) on a follow-along stage, rendered with html_render in T3 Code (or opened as a local HTML page elsewhere). Nothing ever speaks until the user presses Play. Use when the user asks to hear or listen to a reply, wants a briefing they can play, says 'read it to me', 'chunk this', 'segment this', 'listen and look', or when a reply has a wide table, several sections, or a decision they must make. Also a spoken conversation (talk mode): the agent answers out loud in a natural voice and hears the reply through the microphone, turn by turn, until the user says stop; use when the user says 'talk mode', 'let's talk', 'talk to me' or 'voice chat'. Works the same in Claude, Codex and Gemini chats."
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
   With `--html`, every piece is also recorded in Sonia's voice (Microsoft's British neural voice; a second or two, needs internet,
   needs `uv`) into a `deck_audio` folder next to the page; keep that folder. Offline it uses Kokoro's British Emma if `talk.py setup`
   has run, else the page falls back to the browser's voices. `--voice <name>` picks another voice (see Talk mode), `--voice browser`
   skips the recording.
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

## Talk mode (a spoken conversation)

The user talks, you answer out loud, they answer back. `scripts/talk.py` does the voice, with no account or key: Sonia speaks
(Microsoft's British neural voice; needs internet, and the spoken text goes to Microsoft), falling back to Kokoro's British Emma on this
computer when offline; Whisper listens on this computer. The microphone is open only while `listen` or `turn` runs, and only in talk mode.

1. Start only when the user asks for it ("talk mode", "let's talk"). First time on a computer: `uv run <skill>/scripts/talk.py setup`
   (about 650 MB of models, a few minutes; say so before it runs).
2. Each turn: write your answer in the chat as normal, then speak a short version of it and listen for the reply in one call:
   pipe the spoken text to `uv run <skill>/scripts/talk.py turn` (allow 3 minutes for the call). It prints
   `{"heard": true, "text": "<what the user said>"}`; treat that text as the user's next message and answer it the same way.
3. What you speak follows "Spoken style" below: one to three sentences, the answer first. Tables, code, lists of files and anything
   long stay in the chat (or a deck); say "the details are in the chat".
4. The user asks about another chat or project: in T3 Code use its thread tools (list, read, send, wait) to ask that chat or read its
   last reply, then speak the answer. Say what you are doing first ("Checking the Scout chat, one moment").
5. End talk mode when the user says stop, goodbye, "that's all" or "end talk mode", or when `heard` is false (nobody spoke for 60 s):
   say one short goodbye with `say`, never `turn`, and stop calling the script.

Options: `--voice` (`en-GB-SoniaNeural` default; other Microsoft voices such as `en-US-AvaMultilingualNeural`; or Kokoro, offline:
`af_heart`, `af_bella`, `am_michael`, `bf_emma`, `bf_isabella`, `bm_george`, `bm_lewis`), `--speed`
(0.8-1.3), `--wait` (seconds to wait for speech), `--model` (Whisper size: `base` is faster, `small` the default, `medium` more
accurate). `say "text"` and `listen` also work alone.

## Spoken style (talk mode, and any `say` you write yourself)

Talk like a person across the table, not a press release:
- The answer first, then the reason. Skip the preamble ("Great question", "I'd be happy to") and the recap of what you just did.
- Contractions and plain words: "it's", "don't", "use", "start", "help". Short sentences, with the odd longer one so it doesn't sound
  robotic. One qualifier at most; pick a position.
- Cut filler: "basically", "essentially", "it's worth noting", "in order to". Be specific: "three tests failed", not "some issues".
- Numbers and names as people say them: "about two hundred", "the login page", never a file path, link, commit id or table read out.
- Friendly and warm is fine; performed enthusiasm is not. A formal request from the user still gets a formal answer.

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

- Recorded pieces: a chunk's `audio` is `{png, src}`: the .mp3 packed into a PNG (`png`, an absolute path, because T3's `html_render`
  inlines local images and nothing else; the page unpacks it through a canvas) and the plain .mp3 (`src`, relative) for a browser
  opening the file. `deck.voice` names the voice; it is the Voice menu's first entry, and the browser's voices follow it.
- Test ids: `play-all`, `play-stop`, `play-resume`, `play-speed` (0.9x-1.5x), `play-voice` (the recorded voice, then
  `speechSynthesis.getVoices()`; with no recording an en-US "Natural" voice is preferred), `talk-chunk[data-chunk][data-say]`, `chunk-play`, `chunk-visual`, `sheet` (`#sheet-slot[data-id][data-kind]`),
  `sheet-pin` (`aria-pressed`), `option-pill`, `reply-box`.
- One `SpeechSynthesisUtterance` per piece; `onend` moves on; `onerror` or a stall (watchdog: 2x the expected length + 4 s, at least 8 s)
  marks the piece `data-play-error="1"` and moves on; when the queue ends, `Resume` starts at the first failed piece. `Stop` cancels at
  once and `Resume` starts at the stopped piece. The playing piece has `data-playing="1"`.
- The stage follows the playing piece unless `Pin visual` is pressed; a click on a piece or its chip always opens it (a click is an ask).
- Test hooks: `window.__cockpitSynthOverride` (an object with `speak(u)`, `cancel()`, `getVoices()`), `window.__cockpitUtteranceCtor`,
  `window.__cockpitAudioCtor` (stands in for `Audio`),
  and `window.__cockpitSpoken` (every utterance started: `{id, text}`; empty after load). See `tests/test_deck_page.py`.
- Speed and voice are remembered in `localStorage` when the frame allows it. If the view has no speech engine, a note says so and the text
  and pictures still work.

## Run the tests

From this folder: `uv run --no-project --with pytest --with playwright pytest -q tests` (run `uv run --no-project --with playwright
playwright install chromium` once first; add `--with markdown-it-py` to cover the markdown-it path too). The voice tests (`tests/test_talk.py`: Sonia and Kokoro round trips, a page
built with recorded audio) run once `talk.py setup` has downloaded the models, and Sonia's need internet; they play no sound and open no
microphone.
