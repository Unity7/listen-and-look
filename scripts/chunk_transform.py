"""listen-and-look: turn a markdown reply into a deck of playable chunks with clean spoken text.

Pure and deterministic: no model call, no network, standard library only (markdown-it-py renders `show_html` when it is
importable, else a small escape-first renderer does). The one exception is the deck's voice: with `--html`, each piece's spoken text is
rendered to audio by talk.py (through uv) unless `--voice browser` is given; without uv or a voice the page falls back to the browser's.

Chunk dict: {id, n, kind, badge, title, show_html, say, visual, options}; a deck adds {deck_id, title, subtitle, project,
updated_pt, kpis, chunks}. See ../SKILL.md.

CLI (writes a self-contained page for T3 `html_render` from ../resources/deck_template.html):
  python chunk_transform.py reply.md --title "Kit status" --project my-app --html deck.html
  python chunk_transform.py deck_in.json --html deck.html   # a partial deck: chunks given as {"md": ..., "visual": {...}}
  python chunk_transform.py reply.md --json deck.json        # the deck data only
  python chunk_transform.py reply.md --html deck.html --voice browser   # no audio files: the browser's own voices
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

TZ = "America/Los_Angeles"
PARA_MAX = 320  # a paragraph longer than this splits on sentence ends
WIDE_COLS = 4  # a table this wide goes to the visual stage / side sheet and is summarized aloud
LONG_ROWS = 5  # a table this long is summarized aloud
CODE_INLINE_MAX = 8  # a fence longer than this shows as a summary + visual
TEMPLATE = Path(__file__).resolve().parent.parent / "resources" / "deck_template.html"
PLACEHOLDER = "__DECK_JSON__"
TALK = Path(__file__).resolve().parent / "talk.py"
VOICE = "en-GB-SoniaNeural"  # talk.py's default; "browser" skips the audio

try:  # optional: a full CommonMark renderer
    from markdown_it import MarkdownIt

    _MD = MarkdownIt("commonmark", {"html": False}).enable("table")
except Exception:  # noqa: BLE001 - absent: the built-in renderer below
    _MD = None

# ---------------------------------------------------------------- spoken text

_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_TS = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]00:?00)(?![\w])")
_URL = re.compile(r"\b(?:https?|ftp|file|t3code)://[^\s<>()\[\]\"'`]+")
_PATH_CH = r"[^\s\\/:*?\"<>|,;()\[\]`']"
_WIN_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/](?:" + _PATH_CH + r"+[\\/])*" + _PATH_CH + r"*(?::\d+)?")
_REL_PATH = re.compile(r"(?<![\w/.:\\])(?:\.{0,2}[\\/])?(?:[\w.-]+[\\/])+[\w-][\w.-]*\.[A-Za-z0-9]{1,8}(?::\d+)?(?![\w/\\])")
_SHA = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
_EMPH = re.compile(r"(?<![\w*_])([*_])(?!\s)([^*_\n]+?)(?<!\s)\1(?![\w*_])")


def _us_pacific(dt: datetime) -> datetime:
    """`dt` (aware, UTC) in US Pacific time; zoneinfo when the tz database is there, else the US DST rule (Windows has no system tz data)."""
    try:
        from zoneinfo import ZoneInfo

        return dt.astimezone(ZoneInfo(TZ))
    except Exception:  # noqa: BLE001 - no tzdata on this machine
        y = dt.year
        mar = datetime(y, 3, 8, 10, tzinfo=UTC)  # 2 AM PST on the 2nd Sunday of March = 10:00 UTC
        start = mar + timedelta(days=(6 - mar.weekday()) % 7)
        nov = datetime(y, 11, 1, 9, tzinfo=UTC)  # 2 AM PDT on the 1st Sunday of November = 09:00 UTC
        end = nov + timedelta(days=(6 - nov.weekday()) % 7)
        return dt + timedelta(hours=-7 if start <= dt < end else -8)  # wall-clock fields only (pt_clock reads hour/minute)


def pt_clock(dt: datetime) -> str:
    """`dt` (aware) as the reader sees it: `11:30 AM PT`."""
    local = _us_pacific(dt.astimezone(UTC))
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} PT"


def _ts_say(m: re.Match) -> str:
    y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
    return pt_clock(datetime(y, mo, d, h, mi, tzinfo=UTC))


def _path_say(m: re.Match) -> str:
    raw = m.group(0)
    tail = ""
    while raw and raw[-1] in ".,;:!?":  # a sentence end is not part of the path
        tail, raw = raw[-1] + tail, raw[:-1]
    line = ""
    lm = re.search(r":(\d+)$", raw)
    if lm and not re.fullmatch(r"[A-Za-z]:\d+", raw):
        line, raw = f" line {lm.group(1)}", raw[: lm.start()]
    base = re.split(r"[\\/]", raw.rstrip("\\/"))[-1]
    if not base or re.fullmatch(r"[A-Za-z]:", base):
        return "a folder" + tail
    word = "file" if re.search(r"\.[A-Za-z0-9]{1,8}$", base) else "folder"
    return f"{word} {base}{line}{tail}"


def spoken(text: str) -> str:
    """Inline markdown as plain spoken English: link text only, ISO UTC times as 12-hour PT, raw URLs as "a link", file paths as
    "file foo.py" (plus "line 42"), git SHAs dropped, markdown marks and pipes gone, whitespace collapsed."""
    s = text or ""
    s = re.sub(r"</?[A-Za-z][^>]*>", " ", s)  # raw HTML tags are never read out
    s = _LINK.sub(lambda m: m.group(1) or "a link", s)
    s = _TS.sub(_ts_say, s)
    s = _URL.sub("a link", s)
    s = _WIN_PATH.sub(_path_say, s)
    s = _REL_PATH.sub(_path_say, s)
    s = _SHA.sub("", s)
    s = re.sub(r"(?<![\w&])#(\d+)\b", r"number \1", s)
    s = re.sub(r"\*\*|__|~~|`", "", s)
    s = _EMPH.sub(r"\2", s)
    s = re.sub(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)", "", s, flags=re.MULTILINE)
    s = s.replace("|", ", ")
    s = re.sub(r"\s*(?:->|=>|→)\s*", " to ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", s)
    s = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", s))
    s = re.sub(r"\(\s*\)", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,;")


def _end(s: str) -> str:
    """`s` as a spoken sentence: a full stop added unless it already ends in one."""
    s = s.strip()
    return s if not s or s[-1] in ".!?" else s + "."


def _and(words: list[str]) -> str:
    words = [w for w in words if w]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""


def table_say(header: list[str], rows: list[list[str]]) -> str:
    """A table aloud: wide (>= 4 columns) or long (>= 5 rows) as "<rows>-row table comparing <headers>", else row by row."""
    heads = [spoken(h) for h in header]
    if len(header) >= WIDE_COLS or len(rows) >= LONG_ROWS:
        return f"{len(rows)}-row table comparing {_and(heads)}."
    lines = []
    for r in rows:
        cells = [spoken(c) for c in r]
        lines.append(", ".join(f"{h}: {c}" if h else c for h, c in zip(heads, cells, strict=False) if c))
    return "Table. " + "; ".join(lines) + "." if lines else f"Empty table of {_and(heads)}."


def code_say(lang: str, lines: list[str]) -> str:
    """A code block aloud: "Code block in <lang>, <k> lines: <first comment or signature>"."""
    body = [ln for ln in lines if ln.strip()]
    k = len(lines)
    first = ""
    for ln in body:
        t = re.sub(r"^\s*(?:#+|//+|--|/\*+|\*+|;+|rem\b)\s*", "", ln, flags=re.IGNORECASE).strip(" */")
        if t:
            first = spoken(t)[:80].rstrip()
            break
    head = f"Code block in {lang or 'plain text'}, {k} line{'' if k == 1 else 's'}"
    return _end(f"{head}: {first}") if first else head + "."


# ---------------------------------------------------------------- blocks

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)")
_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TROW = re.compile(r"^\s*\|.*\|\s*$")
_TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def blocks(md: str) -> list[dict]:
    """Top-level blocks of `md` in order: heading, para, item (a top-level list item with its nested lines), table, code."""
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[dict] = []
    cur: dict | None = None
    i = 0

    def close():
        nonlocal cur
        if cur:
            cur["text"] = "\n".join(cur.pop("lines")).strip()
            if cur["text"]:
                out.append(cur)
        cur = None

    while i < len(lines):
        line = lines[i]
        fm = _FENCE.match(line)
        if fm:
            close()
            mark, lang, body = fm.group(1), fm.group(2), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark[0] * len(mark)):
                body.append(lines[i])
                i += 1
            out.append({"kind": "code", "lang": lang.lower(), "lines": body, "text": "\n".join(body)})
            i += 1
            continue
        if _TROW.match(line) and i + 1 < len(lines) and _TSEP.match(lines[i + 1]):
            close()
            header = _cells(line)
            rows, i = [], i + 2
            while i < len(lines) and _TROW.match(lines[i]):
                rows.append(_cells(lines[i]))
                i += 1
            out.append({"kind": "table", "header": header, "rows": rows, "text": ""})
            continue
        hm = _HEAD.match(line)
        if hm:
            close()
            out.append({"kind": "heading", "level": len(hm.group(1)), "text": hm.group(2)})
        elif not line.strip():
            close()
        else:
            im = _ITEM.match(line)
            if im and len(im.group(1).expandtabs(4)) < 2:
                close()
                cur = {"kind": "item", "lines": [line]}
            elif cur and (cur["kind"] == "item" or not im):
                cur["lines"].append(line)
            else:
                close()
                cur = {"kind": "para", "lines": [line]}
        i += 1
    close()
    return out


def _sentences(text: str, limit: int = PARA_MAX) -> list[str]:
    """`text` cut at sentence ends into pieces of at most `limit` characters (a single longer sentence stays whole)."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(*`])", text.strip())
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}" if cur else p
    return out + ([cur] if cur else [])


# ---------------------------------------------------------------- safe html

def _inline(s: str) -> str:
    """Escape first, then the few inline marks: `code`, **strong**, *em*, [text](http link)."""
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", keep, s)
    links: list[str] = []

    def link(m):
        text, url = m.group(1), m.group(2)
        if re.match(r"https?://", url):
            links.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(text)}</a>')
        else:
            links.append(html.escape(text or url))
        return f"\x01{len(links) - 1}\x01"

    s = _LINK.sub(link, s)
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", s)
    s = _EMPH.sub(r"<em>\2</em>", s)
    s = re.sub(r"\x01(\d+)\x01", lambda m: links[int(m.group(1))], s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def table_html(header: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_inline(h)}</th>" for h in header)
    trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="ll-table"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def code_html(lang: str, lines: list[str]) -> str:
    cls = f' class="lang-{html.escape(lang, quote=True)}"' if lang else ""
    return f"<pre><code{cls}>{html.escape(chr(10).join(lines))}</code></pre>"


def block_html(b: dict) -> str:
    """One block as safe HTML (markdown-it-py with raw HTML off when present, else the escape-first renderer)."""
    if b["kind"] == "table":
        return table_html(b["header"], b["rows"])
    if b["kind"] == "code":
        return code_html(b.get("lang", ""), b["lines"])
    if _MD is not None:
        return _MD.render(b["text"]).strip()
    if b["kind"] == "heading":
        return f"<h3>{_inline(b['text'])}</h3>"
    if b["kind"] == "item":
        first, *rest = b["text"].split("\n")
        body = _inline(_ITEM.match(first).group(3)) if _ITEM.match(first) else _inline(first)
        sub = [_ITEM.match(ln).group(3) if _ITEM.match(ln) else ln.strip() for ln in rest if ln.strip()]
        nested = "<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in sub) + "</ul>" if sub else ""
        return f"<ul><li>{body}{nested}</li></ul>"
    return "<p>" + "<br>".join(_inline(ln) for ln in b["text"].split("\n")) + "</p>"


# ---------------------------------------------------------------- chunks

KIND_WORD = {"summary": "Summary", "point": "Point", "table": "Table", "code": "Code", "blocker": "Blocker", "decision": "Your call",
             "sofar": "So far", "chart": "Chart"}


def _chunk(source: str, n: int, kind: str, title: str, show_html: str, say: str, visual: dict | None = None,
           options: list[dict] | None = None, badge: str = "") -> dict:
    return {"id": f"{source}-{n}", "n": n, "kind": kind, "badge": badge or f"{n} · {KIND_WORD.get(kind, kind.title())}", "title": title,
            "show_html": show_html, "say": say, "visual": visual, "options": options or []}


def chunk_markdown(md: str, source: str = "msg-1", start: int = 1) -> list[dict]:
    """Free-form markdown as ordered chunks: one per top-level list item, table, code block or paragraph (<= 320 chars, longer ones cut at
    sentence ends). A heading is not a chunk of its own: it titles the chunks under it and is spoken before the first of them."""
    chunks: list[dict] = []
    title, lead = "", ""
    n = start - 1
    for b in blocks(md):
        if b["kind"] == "heading":
            if lead:  # two headings in a row: the first stands alone
                n += 1
                chunks.append(_chunk(source, n, "point", title, f"<h3>{_inline(title)}</h3>", spoken(title) + "."))
            title = lead = b["text"]
            continue
        pieces = [b]
        if b["kind"] == "para" and len(b["text"]) > PARA_MAX:
            pieces = [{"kind": "para", "text": t} for t in _sentences(b["text"])]
        for p in pieces:
            n += 1
            visual = None
            if p["kind"] == "table":
                cols = len(p["header"])
                say = table_say(p["header"], p["rows"])
                full = table_html(p["header"], p["rows"])
                if cols >= WIDE_COLS:
                    visual = {"kind": "table", "label": f"Table · {cols} cols", "title": title or "Table", "html": full}
                    show = f'<p class="ll-sum">{html.escape(say)}</p>'
                else:
                    show = full
                kind = "table"
            elif p["kind"] == "code":
                say = code_say(p.get("lang", ""), p["lines"])
                full = code_html(p.get("lang", ""), p["lines"])
                if len(p["lines"]) > CODE_INLINE_MAX:
                    visual = {"kind": "code", "label": f"Code · {len(p['lines'])} lines", "title": title or "Code", "html": full}
                    show = f'<p class="ll-sum">{html.escape(say)}</p>'
                else:
                    show = full
                kind = "code"
            else:
                say = spoken(p["text"])
                show = block_html(p)
                kind = "point" if p["kind"] == "item" else ("summary" if n == start else "point")
            if lead:
                say = f"{spoken(lead)}. {say}"
                lead = ""
            chunks.append(_chunk(source, n, kind, title, show, say, visual))
    if lead:
        n += 1
        chunks.append(_chunk(source, n, "point", title, f"<h3>{_inline(title)}</h3>", spoken(title) + "."))
    return chunks


LABELS = ["Blocker", "Why", "The choice", *[f"Option {n}" for n in range(1, 10)], "My lean", "Your call"]
_FIELD = re.compile(r"^\s*(?:\*\*|__)?(" + "|".join(LABELS) + r")(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.*?)\s*$", re.IGNORECASE)


def blocker_fields(text: str) -> tuple[str, dict[str, str]] | None:
    """(prose before the blocker, {label: value}) when `text` holds the blocker shape ("Blocker:" plus one more field), else None.
    A label line opens a field, other lines continue it, the last Blocker wins."""
    fields: dict[str, str] = {}
    last, start = None, None
    for idx, line in enumerate((text or "").replace("\r", "").split("\n")):
        m = _FIELD.match(line)
        if m:
            last = next(lab for lab in LABELS if lab.lower() == m.group(1).lower())
            if last == "Blocker":
                fields, start = {}, idx
            fields[last] = m.group(2).replace("**", "").replace("__", "")
        elif not line.strip():
            last = None
        elif last:
            fields[last] = (fields[last] + " " + line.strip()).strip()
    if "Blocker" not in fields or len(fields) < 2:
        return None
    lines = (text or "").replace("\r", "").split("\n")
    before = "\n".join(lines[:start]).strip() if start else ""
    return before, fields


def blocker_card_html(fields: dict[str, str], lean: int | None) -> str:
    """The 7-line blocker card with one-click option pills (the pills fill / copy the reply in the deck)."""
    opts = [(int(k.split()[1]), v) for k, v in fields.items() if k.startswith("Option ") and v.strip()]
    rows = [f'<div class="bk-row"><span class="bk-lab">Blocker</span><span>{_inline(fields["Blocker"])}</span></div>']
    for lab in ("Why", "The choice"):
        if fields.get(lab):
            rows.append(f'<div class="bk-row"><span class="bk-lab">{lab}</span><span>{_inline(fields[lab])}</span></div>')
    pills = "".join(
        f'<button type="button" class="bk-pill{" lean" if n == lean else ""}" data-testid="option-pill" data-option="{n}" '
        f'data-reply="{html.escape(str(n), quote=True)}"><span class="bk-n">{n}</span><span>{_inline(v)}</span>'
        f'{"<span class=bk-leantag>my lean</span>" if n == lean else ""}</button>' for n, v in sorted(opts))
    if fields.get("My lean"):
        rows.append(f'<div class="bk-row"><span class="bk-lab">My lean</span><span>{_inline(fields["My lean"])}</span></div>')
    return (f'<div class="bk-card" data-testid="blocker-card">{"".join(rows)}<div class="bk-pills">{pills}</div>'
            f'<div class="bk-call">Your call: {_inline(fields.get("Your call") or "pick one")}</div></div>')


def chunk_blocker(text: str, source: str = "wait", start: int = 1) -> list[dict] | None:
    """A blocker-shaped reply as chunks: any prose before it (markdown chunks), Blocker + Why, one chunk per option, My lean + Your call.
    Every blocker chunk carries the whole card as its visual so the stage keeps showing the decision. None when not in the shape."""
    got = blocker_fields(text)
    if not got:
        return None
    before, f = got
    chunks = chunk_markdown(before, source, start) if before else []
    n = (chunks[-1]["n"] if chunks else start - 1)
    lm = re.search(r"\b(?:option\s*)?(\d)\b", f.get("My lean", ""), re.IGNORECASE)
    lean = int(lm.group(1)) if lm else None
    opts = [{"n": int(k.split()[1]), "label": k, "text": " ".join(v.split()), "lean": int(k.split()[1]) == lean}
            for k, v in f.items() if k.startswith("Option ") and v.strip()]
    opts.sort(key=lambda o: o["n"])
    card = {"kind": "blocker", "label": f"Blocker · {len(opts)} option{'' if len(opts) == 1 else 's'}", "title": "Your decision",
            "html": blocker_card_html(f, lean)}
    head = [f'<p><strong>Blocker:</strong> {_inline(f["Blocker"])}</p>']
    say = [_end(f"Blocker: {spoken(f['Blocker'])}")]
    for lab in ("Why", "The choice"):
        if f.get(lab):
            head.append(f"<p><strong>{lab}:</strong> {_inline(f[lab])}</p>")
            say.append(_end(f"{lab}: {spoken(f[lab])}"))
    n += 1
    chunks.append(_chunk(source, n, "blocker", "Blocker", "".join(head), " ".join(say), card, opts, f"{n} · Blocker"))
    for o in opts:
        n += 1
        tag = " (my lean)" if o["lean"] else ""
        chunks.append(_chunk(source, n, "decision", o["label"], f"<p><strong>{o['n']}.</strong> {_inline(o['text'])}{html.escape(tag)}</p>",
                             _end(f"Option {o['n']}: {spoken(o['text'])}"), card, [o], f"{n} · Option {o['n']}"))
    if f.get("My lean") or f.get("Your call"):
        n += 1
        parts, sp = [], []
        if f.get("My lean"):
            parts.append(f"<p><strong>My lean:</strong> {_inline(f['My lean'])}</p>")
            sp.append(_end(f"My lean: {spoken(f['My lean'])}"))
        parts.append(f"<p><strong>Your call:</strong> {_inline(f.get('Your call') or 'pick one')}</p>")
        sp.append(_end(f"Your call: {spoken(f.get('Your call') or 'pick one')}"))
        chunks.append(_chunk(source, n, "decision", "Your call", "".join(parts), " ".join(sp), card, opts,
                             f"{n} · Your call"))
    return chunks


def chunk_text(text: str, source: str = "msg-1") -> list[dict]:
    """Any reply: the blocker shape when it has one, else free-form markdown."""
    return chunk_blocker(text, source) or chunk_markdown(text, source)


# ---------------------------------------------------------------- deck

def build_deck(chunks: list[dict], title: str, subtitle: str = "", project: str = "", kpis: list[dict] | None = None,
               deck_id: str = "", now: datetime | None = None) -> dict:
    when = now or datetime.now(UTC)
    return {"deck_id": deck_id or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "deck", "title": title, "subtitle": subtitle,
            "project": project, "updated_pt": pt_clock(when), "kpis": kpis or [], "chunks": chunks}


def deck_from_spec(spec: dict, now: datetime | None = None) -> dict:
    """A partial deck (chunks as {"md"} or {"text"} with optional title/kind/visual/say) filled in: show_html, say, ids, badges."""
    out: list[dict] = []
    for c in spec.get("chunks") or []:
        src = spec.get("source") or "c"  # one id prefix for the whole deck
        if "show_html" in c and "say" in c:  # already a full chunk
            out.append({**_chunk(src, len(out) + 1, c.get("kind", "point"), c.get("title", ""), c["show_html"], c["say"]), **c,
                        "n": len(out) + 1, "id": c.get("id") or f"{src}-{len(out) + 1}"})
            continue
        made = chunk_text(c.get("md") or c.get("text") or "", src)
        for m in made:
            m["n"] = len(out) + 1
            m["id"] = f"{src}-{m['n']}"
            m["badge"] = re.sub(r"^\d+", str(m["n"]), m["badge"])
            if c.get("title") and not m["title"]:
                m["title"] = c["title"]
            if out and m["kind"] == "summary":  # only the deck's first piece is the summary
                m["kind"], m["badge"] = "point", re.sub(r"Summary$", "Point", m["badge"])
            if c.get("kind"):
                m["kind"] = c["kind"]
            if c.get("say") and len(made) == 1:
                m["say"] = c["say"]
            if c.get("visual") and (m["visual"] is None or len(made) == 1):
                m["visual"] = c["visual"]
                m["visual"].setdefault("label", m["visual"].get("kind", "visual").title())
            out.append(m)
    return build_deck(out, spec.get("title", "Briefing"), spec.get("subtitle", ""), spec.get("project", ""), spec.get("kpis"),
                      spec.get("deck_id", ""), now)


def deck_json(deck: dict) -> str:
    """The deck as JSON that is safe inside `<script type="application/json">` (no `<` can close the tag)."""
    return json.dumps(deck, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_html(deck: dict, template: Path = TEMPLATE) -> str:
    page = template.read_text(encoding="utf-8")
    if PLACEHOLDER not in page:
        raise ValueError(f"{template} has no {PLACEHOLDER}")
    return page.replace(PLACEHOLDER, deck_json(deck), 1)


def voice_name(voice: str) -> str:
    """'en-GB-SoniaNeural' -> 'Sonia', 'bf_emma' -> 'Emma'."""
    m = re.match(r"^[a-z]{2}-[A-Z]{2}-(.+?)(?:Multilingual)?Neural$", voice) or re.match(r"^[a-z]{2}_(.+)$", voice)
    return (m.group(1) if m else voice).capitalize()


def add_audio(deck: dict, html_path: Path, voice: str = VOICE) -> bool:
    """Render every piece's `say` with talk.py into <page>_audio/ next to the page and point each chunk at it: `audio.png` (absolute, so
    T3's html_render inlines it) and `audio.src` (the .mp3, relative, for a browser opening the file). False, and the deck unchanged,
    when uv or the voice is unavailable."""
    if not shutil.which("uv"):
        print("no uv: the page uses the browser's voices", file=sys.stderr)
        return False
    out = html_path.resolve().parent / f"{html_path.stem}_audio"
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.mp3"), *out.glob("*.png")]:
        old.unlink()
    lines = "".join(json.dumps({"id": c["id"], "text": c.get("say", "")}) + "\n" for c in deck["chunks"])
    try:
        done = subprocess.run(["uv", "run", "--quiet", str(TALK), "audio", "--dir", str(out), "--voice", voice], input=lines,
                              capture_output=True, text=True, encoding="utf-8", timeout=600, check=True)
        got = json.loads(done.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, ValueError, IndexError) as e:
        err = getattr(e, "stderr", "") or ""
        print(f"no audio ({type(e).__name__}): the page uses the browser's voices. {err.strip()[-300:]}", file=sys.stderr)
        return False
    for c in deck["chunks"]:
        if c["id"] in got["ids"]:
            c["audio"] = {"png": (out / f"{c['id']}.png").as_posix(), "src": f"{out.name}/{c['id']}.mp3"}
    deck["voice"] = voice_name(got["voice"])
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", help="a .md reply or a partial deck .json ('-' reads markdown from stdin)")
    ap.add_argument("--title", default="Briefing")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--project", default="")
    ap.add_argument("--html", help="write the self-contained deck page here")
    ap.add_argument("--json", help="write the deck data here")
    ap.add_argument("--voice", default=VOICE, help="voice for the page's audio (talk.py names), or 'browser' for none")
    a = ap.parse_args(argv)
    raw = sys.stdin.read() if a.source == "-" else Path(a.source).read_text(encoding="utf-8")
    if a.source.endswith(".json"):
        spec = json.loads(raw)
        for k in ("title", "subtitle", "project"):
            if getattr(a, k) and (k != "title" or a.title != "Briefing"):
                spec[k] = getattr(a, k)
        deck = deck_from_spec(spec)
    else:
        deck = build_deck(chunk_text(raw, "msg"), a.title, a.subtitle, a.project)
    if a.json:
        Path(a.json).write_text(json.dumps(deck, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.html:
        if a.voice != "browser":
            add_audio(deck, Path(a.html), a.voice)
        Path(a.html).write_text(render_html(deck), encoding="utf-8")
    if not (a.json or a.html):
        sys.stdout.write(json.dumps(deck, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(deck['chunks'])} chunks", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
