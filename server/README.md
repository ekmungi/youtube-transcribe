# YT Transcribe

Captions-first YouTube transcript extractor. Fetches YouTube's existing caption tracks (manual or auto-generated) in seconds and saves them as Markdown with YAML frontmatter to an Obsidian vault. Exposed through an MCP server (for Claude Code and other MCP clients) and a CLI.

## How it works

YouTube already has a transcript for nearly every video: a manual caption track uploaded by the creator, or an auto-generated one. The default `captions` strategy fetches that track directly -- no audio download, no speech-to-text, no cost, typically a few seconds per video.

For the rare video with no captions at all, the `cloud` strategy downloads the audio and sends it to AssemblyAI for paid speech-to-text. This is an explicit opt-in: it requires an AssemblyAI API key and it sends the video's audio to a third-party service. It is never used unless you ask for it.

Every saved transcript records its provenance in the frontmatter: `source` (`manual_captions`, `auto_captions`, or `assemblyai`) and `caption_language` (null for speech-to-text results).

### Foreign-language videos

For videos in other languages, you get the transcript in the video's original language. YouTube's auto-translated caption tracks are unreliable in practice, so auto-translation is deprioritized; translate the saved Markdown afterwards if you need it in another language.

## Features

- **Captions-first**: YouTube's own caption tracks by default -- free, fast, nothing leaves YouTube
- **Cloud fallback (opt-in)**: AssemblyAI speech-to-text for caption-less videos
- **Obsidian vault output**: Markdown with YAML frontmatter (title, channel, url, video_id, date, duration, source, caption_language, tags)
- **Playlist support**: Expand and transcribe entire YouTube playlists
- **Deduplication**: Skips videos already saved in the vault
- **Full-text search**: Search across all saved transcripts
- **Real-time progress**: MCP server streams stage-by-stage progress during transcription
- **Lean MCP server**: Subprocess worker model keeps the server small; heavy dependencies load only while a transcription runs and are freed when it finishes

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- AssemblyAI API key (only for the optional `cloud` strategy)
- ffmpeg (only for the optional `cloud` strategy; auto-detected or configurable path)

## Installation

### Global install (uv tool)

```bash
uv tool install "git+https://github.com/ekmungi/youtube-transcribe.git#subdirectory=server"
```

This installs `yt-transcribe` (CLI) and `yt-transcribe-server` (MCP server) globally.

### From source (development)

```bash
git clone https://github.com/ekmungi/youtube-transcribe.git
cd youtube-transcribe/server
uv sync
```

## MCP server

The MCP server exposes 5 tools via stdio transport for use with Claude Code, Claude Desktop, or any MCP-compatible client.

**Global install (recommended):** After `uv tool install`, add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "yt-transcribe": {
      "command": "yt-transcribe-server",
      "args": []
    }
  }
}
```

**From source:** Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "yt-transcribe": {
      "command": "uv",
      "args": ["run", "yt-transcribe-server"],
      "cwd": "/path/to/youtube-transcription"
    }
  }
}
```

**Available tools:**

| Tool | Description |
|------|-------------|
| `get_transcript` | Transcribe a single YouTube video and save it to the vault |
| `get_playlist_transcripts` | Transcribe all videos in a playlist |
| `list_transcripts` | List saved transcripts in the vault |
| `search_transcripts` | Full-text search across transcript content |
| `server_status` | Check server health, uptime, config, and activity |

`get_transcript` and `get_playlist_transcripts` accept an optional `strategy` argument (`captions` or `cloud`) and an `include_text` flag to return the transcript text inline instead of just the saved file path. Responses always include `source` and `caption_language` provenance.

## CLI

```bash
# Transcribe a single video
uv run yt-transcribe video https://youtube.com/watch?v=VIDEO_ID

# Transcribe a playlist
uv run yt-transcribe playlist https://youtube.com/playlist?list=PLAYLIST_ID

# List saved transcripts
uv run yt-transcribe list

# Search transcripts
uv run yt-transcribe search "query"

# Show configuration
uv run yt-transcribe config

# Update a configuration value
uv run yt-transcribe config set transcription_strategy captions
```

The CLI uses the strategy from your config file; switch with `config set transcription_strategy cloud` if you need speech-to-text for a caption-less video, and switch back afterwards.

## Configuration

Settings are stored in `~/.yt-transcribe/config.yaml` (auto-created on first use):

| Setting | Default | Description |
|---------|---------|-------------|
| `obsidian_vault_path` | `~/Obsidian` | Path to Obsidian vault |
| `transcript_folder` | `Sources/YouTube Transcripts` | Subfolder within the vault |
| `transcription_strategy` | `captions` | `captions` (default) or `cloud` (AssemblyAI opt-in) |
| `ffmpeg_location` | (auto-detect) | Path to ffmpeg binary (only used by `cloud`) |

The AssemblyAI API key is read from the `ASSEMBLYAI_API_KEY` environment variable or the OS keyring (service `yt-transcribe`). Legacy strategy values from older versions (`auto`, `local`) migrate to `captions` automatically.

## Obsidian plugin

A companion Obsidian plugin lives in its own repository:
[ekmungi/obsidian-youtube-transcribe](https://github.com/ekmungi/obsidian-youtube-transcribe).
It is a thin UI over this CLI: paste a YouTube URL and it runs
`yt-transcribe video <url> --json`, then opens the resulting vault note. Install
it with [BRAT](https://github.com/TfTHacker/obsidian42-brat) or from its releases.

The plugin depends on this CLI's `--json` output contract, so changes to that
contract must stay in sync across both repositories.

## Architecture

```
src/yt_transcribe/       # Core library
  config.py              # YAML config + keyring for API keys
  models.py              # Immutable dataclasses (frozen=True)
  exceptions.py          # Typed error hierarchy
  captions.py            # YouTube caption track fetching and parsing
  download.py            # yt-dlp: metadata, captions, audio download
  transcribe.py          # Strategy orchestration (captions / cloud)
  assemblyai_engine.py   # Cloud speech-to-text engine (opt-in)
  storage.py             # Markdown output with frontmatter
  search.py              # Full-text search across vault
  mcp_server.py          # MCP server (5 tools, stdio transport)
  tool_schemas.py        # Static MCP tool schema definitions
  worker_runner.py       # Subprocess spawn, progress relay, watchdog
  worker.py              # Subprocess worker for memory-heavy tasks
  cli.py                 # CLI (click + rich)
```

## Changelog

### 0.9.0

- New `get_transcripts` MCP tool: accepts a single URL or a list, auto-detects each as a video or a playlist (via `url_classify`) and routes accordingly. A watch URL carrying `&list=` is treated as a single video.
- `get_transcript`, `get_playlist_transcripts`, and `get_transcripts` gained an `output_dir` parameter so callers choose where transcripts are written, overriding the configured vault for that call (cache lookup is rooted there too).
- Engine moved into the `youtube-transcribe` repository under `server/`, alongside the Obsidian plugin. The plugin and engine install independently (BRAT for the plugin, `uv` for the engine).

### 0.8.1

- Transcript bodies are now formatted as flowing paragraphs instead of one caption fragment per line (which rendered as a tall single column). Segments are joined into readable paragraphs separated by [timestamp] markers; markers past one hour show as [H:MM:SS]. Applies to newly transcribed videos.

### 0.8.0

- `yt-transcribe video` gained `--strategy`, `--vault`, `--folder`, and `--json` options so a single run can target a specific strategy, vault, and subfolder and emit a machine-readable result. These power the Obsidian plugin.
- `yt-transcribe setup-ffmpeg` downloads a static ffmpeg into `~/.yt-transcribe/bin` for the cloud strategy; an optional `[cloud]` extra bundles one too.

### 0.7.0

- Desktop app (Flet) and Windows installer removed. The MCP server and CLI are the two supported interfaces. If you installed an earlier desktop version, uninstall "YT Transcribe" via Windows Settings > Apps.
- Whisper local transcription removed. Strategies are now `captions` (default) and `cloud` (AssemblyAI opt-in); legacy `auto` and `local` config values migrate to `captions`.
- `check_job_status` MCP tool removed along with the async job queue; transcriptions run to completion with streamed progress.

## License

MIT
