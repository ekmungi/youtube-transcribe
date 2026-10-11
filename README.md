# YouTube Transcribe

One repository, two installable pieces that share a single transcription engine:

- **Obsidian plugin** (repo root) - transcribe a YouTube URL into a vault note from
  inside Obsidian. Installed with [BRAT](https://github.com/TfTHacker/obsidian42-brat).
- **Python engine** (`server/`) - the actual transcription engine, exposed as a
  `yt-transcribe` CLI and an optional `yt-transcribe-server` MCP server.

The plugin is a thin UI: it calls the `yt-transcribe` CLI, which writes a markdown
note into your vault. Claude Code does the same through a small skill
(`skills/yt-transcribe`) that tells it which command to run, so there is no
background process. The optional MCP server wraps the same engine for clients that
cannot run shell commands. The pieces install in different places and never
interfere - BRAT only reads the plugin's `manifest.json` + `main.js`; Claude Code
only runs the CLI.

## Repository layout

```
.                       # Obsidian plugin (TypeScript)  -> installed by BRAT
  main.ts, cli.ts, ...
  manifest.json, main.js, styles.css
server/                 # Python engine                 -> installed by uv
  src/yt_transcribe/     #   shared engine: captions, storage, search
  src/yt_transcribe/cli.py          #   -> yt-transcribe        (CLI)
  src/yt_transcribe/mcp_server.py   #   -> yt-transcribe-server (MCP, optional)
  pyproject.toml, tests/
skills/yt-transcribe/   # Claude Code skill             -> linked into ~/.claude/skills
```

## Install the plugin (Obsidian, via BRAT)

1. Install the "BRAT" plugin from the community store and enable it.
2. Run "BRAT: Add a beta plugin for testing".
3. Enter this repository: `ekmungi/youtube-transcribe`.
4. BRAT downloads the latest release and installs the plugin.
5. Enable "YouTube Transcribe" under Settings -> Community plugins.

The plugin needs the `yt-transcribe` CLI on your PATH (install it below).

## Install the engine (via uv)

```bash
uv tool install "git+https://github.com/ekmungi/youtube-transcribe.git#subdirectory=server"
```

This installs `yt-transcribe` (the CLI, used by the plugin and by Claude Code) and
`yt-transcribe-server` (the optional MCP server). The launcher goes to
`~/.local/bin` (make sure it is on PATH), the engine and its libraries to uv's tool
folder, and its settings to `~/.yt-transcribe/config.yaml`. Update with
`uv tool upgrade yt-transcribe`; the next call runs the new code.

### Use it from Claude Code (skill)

Link the skill folder into your user skills, so it applies in every project:

```bash
ln -s /path/to/youtube-transcribe/skills/yt-transcribe ~/.claude/skills/yt-transcribe
```

(Copying the folder works too, but then it does not follow updates.) When you paste a
YouTube link, Claude loads the skill and runs `yt-transcribe video "<url>" --json`
through its shell tool; the command saves the note, prints one line of JSON and exits.

### Optional: the MCP server

For clients that cannot run shell commands (such as Claude Desktop chat), register
the server instead. It is a long-running process, about 60 MB while a client is open.

```bash
claude mcp add yt-transcribe -- yt-transcribe-server
```

The server exposes these tools:

| Tool | Description |
|------|-------------|
| `get_transcripts` | Transcribe one URL or a list; auto-detects video vs playlist and routes each. Accepts `output_dir`. |
| `get_transcript` | Transcribe a single video. Accepts `output_dir`. |
| `get_playlist_transcripts` | Transcribe every video in a playlist. Accepts `output_dir`. |
| `list_transcripts` | List saved transcripts in the vault. |
| `search_transcripts` | Full-text search across saved transcripts. |
| `server_status` | Server health: uptime, version, config, activity. |

`output_dir` lets the caller choose where transcripts are written, overriding the
configured vault location for that call.

## Plugin usage

The plugin adds two commands (Ctrl/Cmd-P):

- **Transcribe YouTube video** - prompts for a URL (pre-filled from the clipboard if
  it holds a YouTube link).
- **Transcribe YouTube video from clipboard** - reads the clipboard and transcribes
  directly.

Both commands accept a single video **or a playlist** URL. The plugin auto-detects
which it is: a playlist transcribes every video and saves a separate note per video
(a `watch?v=...&list=...` URL is treated as the single video it points at). If some
videos fail (for example, no captions), the rest are still saved and the notice names
the failed ones; run the same playlist again to retry only those.

The first time you transcribe in a session, the plugin checks the engine version
(`yt-transcribe --version`) and shows a notice if the engine is older than the plugin
needs. Update it with `uv tool upgrade yt-transcribe`.

A ribbon icon in the left sidebar triggers the prompt. Settings cover the CLI
executable path, the transcript folder, and whether to open the note after
transcribing.

## How transcription works

The text always comes from a video's existing YouTube caption track (manual or
auto-generated) - instant, free, nothing leaves YouTube. There is no other source:
a video without captions cannot be transcribed, and the plugin or command says so.

Every saved transcript is Markdown with YAML frontmatter recording its provenance
(`source`, `caption_language`).

## Development

- **Plugin**: `npm install && npm run build` (produces `main.js`).
- **Engine**: `cd server && uv sync`, then `uv run python -m pytest`,
  `uv run ruff check`, `uv run python -m mypy src`.

When the CLI's `--json` output contract changes, update both the engine and the
plugin together - they share that contract.

## Notes

- The plugin is desktop only: it uses Node's `child_process` to launch the CLI.
