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

## Talk mode (spoken conversation)

Say **"talk mode"** or **"let's talk"** and the agent answers out loud in a natural voice, then listens for your reply through the
microphone, turn by turn. In T3 Code it can also ask your other chats for you ("what's the Scout chat doing?") and read you the answer.
Say **"stop"** or **"goodbye"** to end it; it also ends after 60 seconds of silence.

Everything runs on your computer, free, no account: [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) for the voice and
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) for listening. It needs [uv](https://docs.astral.sh/uv/) and a one-time
download of about 650 MB:

```sh
uv run ~/.claude/skills/listen-and-look/scripts/talk.py setup
```

Each turn takes a few seconds on top of the agent's own thinking. The microphone is only open while the agent is waiting for your answer
in talk mode; there is no wake word and nothing listens otherwise. You can't interrupt it mid-sentence; it stops when it finishes.

## Tests

```sh
uv run --no-project --with playwright playwright install chromium   # once
uv run --no-project --with pytest --with playwright pytest -q tests
```

## Credits

Talk mode's speech settings and the spoken-style rules follow Row-Bot's voice mode and Humanizer skill
(Apache-2.0); no Row-Bot code is copied.

## License

MIT
