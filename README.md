# YouTube Transcribe

One repository, two installable pieces that share a single transcription engine:

- **Obsidian plugin** (repo root) - transcribe a YouTube URL into a vault note from
  inside Obsidian. Installed with [BRAT](https://github.com/TfTHacker/obsidian42-brat).
- **Python engine** (`server/`) - the actual transcription engine, exposed as a
  `yt-transcribe` CLI and a `yt-transcribe-server` MCP server for Claude Code.

The plugin is a thin UI: it calls the `yt-transcribe` CLI, which writes a markdown
note into your vault. The MCP server wraps the same engine so Claude Code can drive
it directly. The two install in different places and never interfere - BRAT only
reads the plugin's `manifest.json` + `main.js`; Claude Code only runs the Python
entry point.

## Repository layout

```
.                       # Obsidian plugin (TypeScript)  -> installed by BRAT
  main.ts, cli.ts, ...
  manifest.json, main.js, styles.css
server/                 # Python engine                 -> installed by uv
  src/yt_transcribe/     #   shared engine: captions, storage, search
  src/yt_transcribe/cli.py          #   -> yt-transcribe        (CLI)
  src/yt_transcribe/mcp_server.py   #   -> yt-transcribe-server (MCP)
  pyproject.toml, tests/
```

## Install the plugin (Obsidian, via BRAT)

1. Install the "BRAT" plugin from the community store and enable it.
2. Run "BRAT: Add a beta plugin for testing".
3. Enter this repository: `ekmungi/youtube-transcribe`.
4. BRAT downloads the latest release and installs the plugin.
5. Enable "YouTube Transcribe" under Settings -> Community plugins.

The plugin needs the `yt-transcribe` CLI on your PATH (install it below).

## Install the engine (CLI + MCP server, via uv)

```bash
uv tool install "git+https://github.com/ekmungi/youtube-transcribe.git#subdirectory=server"
```

This installs `yt-transcribe` (CLI, used by the plugin) and `yt-transcribe-server`
(MCP server, used by Claude Code).

### Register the MCP server with Claude Code

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
(a `watch?v=...&list=...` URL is treated as the single video it points at).

A ribbon icon in the left sidebar triggers the prompt. Settings cover the CLI
executable path, default strategy, the transcript folder, and whether to open the
note after transcribing.

## How transcription works

The default `captions` strategy fetches a video's existing YouTube caption track
(manual or auto-generated) - instant, free, nothing leaves YouTube. An opt-in
`cloud` strategy sends audio to AssemblyAI for speech-to-text when a video has no
captions; it requires an AssemblyAI API key and ffmpeg.

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
