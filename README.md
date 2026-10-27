# listen-and-look

An agent skill that turns a long AI reply into a deck you can **listen to**: the reply is cut into short pieces, each with its own Play
button, and tables, charts and code show on a stage beside them. `Play all` reads everything aloud with your browser's built-in voices.
Nothing speaks until you press Play.

Built for [T3 Code](https://github.com/pingdotgg/t3code) (the deck shows inline through its `html_render` tool), and works in any agent
that reads skills (Claude Code, Codex, Gemini); outside T3 Code you open the generated `deck.html` in Edge or Chrome.

## Install

Needs Python 3.11+ or [uv](https://docs.astral.sh/uv/). No other packages are required.

**Claude (Claude Code, or Claude chats inside T3 Code):** clone into your personal skills folder.

```sh
# Windows (PowerShell)
git clone https://github.com/Unity7/listen-and-look "$env:USERPROFILE\.claude\skills\listen-and-look"

# macOS / Linux
git clone https://github.com/Unity7/listen-and-look ~/.claude/skills/listen-and-look
```

**Codex or Gemini:** clone the same way into that agent's skills folder, or into `.agents/skills/listen-and-look` inside a project.

To update later: `git pull` inside that folder.

## Use

1. Talk to your agent as normal. To speak instead of type on Windows, click the message box and press **Win+H** (built-in dictation);
   on macOS press the dictation key (or Fn twice).
2. Ask it to **"read it to me"**, "make this a listen-and-look deck", or "chunk this".
3. Press **Play all** (or Play on one piece). Speed and voice are in the top bar; Edge offers the most natural voices.

## Tests

```sh
uv run --no-project --with playwright playwright install chromium   # once
uv run --no-project --with pytest --with playwright pytest -q tests
```

## License

MIT
