# YT Transcribe

YouTube transcript extractor. Fetches YouTube's own caption tracks (manual or auto-generated) in seconds and saves them as Markdown with YAML frontmatter to an Obsidian vault. Used through a CLI (by Claude Code through a skill, and by the Obsidian plugin).

## How it works

YouTube already has a transcript for nearly every video: a manual caption track uploaded by the creator, or an auto-generated one. The tool fetches that track directly -- no audio download, no speech-to-text, no cost, typically a few seconds per video.

The text always comes from YouTube's captions and there is no other source, so a video without captions cannot be transcribed. The command then reports a clear error (`NoCaptionsError`) and nothing else is tried.

Every saved transcript records its provenance in the frontmatter: `source` (`manual_captions` or `auto_captions`) and `caption_language`.

### Foreign-language videos

For videos in other languages, you get the transcript in the video's original language. YouTube's auto-translated caption tracks are unreliable in practice, so auto-translation is deprioritized; translate the saved Markdown afterwards if you need it in another language.

## Features

- **Captions only**: YouTube's own caption tracks -- free, fast, nothing leaves YouTube
- **Obsidian vault output**: Markdown with YAML frontmatter (title, channel, url, video_id, date, duration, source, caption_language, tags)
- **Playlist support**: Expand and transcribe entire YouTube playlists; a video that fails is listed under `failed` and the rest continue
- **Deduplication**: Skips videos already saved in the vault, so re-running a playlist retries only the failed videos
- **Full-text search**: Search across all saved transcripts

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

### Global install (uv tool)

```bash
uv tool install "git+https://github.com/ekmungi/youtube-transcribe.git#subdirectory=server"
```

This installs the `yt-transcribe` command globally.

### From source (development)

```bash
git clone https://github.com/ekmungi/youtube-transcribe.git
cd youtube-transcribe/server
uv sync
```

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
uv run yt-transcribe config set transcript_folder "03 RESOURCES/Youtube Transcriptions"
```

## Configuration

Settings are stored in `~/.yt-transcribe/config.yaml` (auto-created on first use):

| Setting | Default | Description |
|---------|---------|-------------|
| `obsidian_vault_path` | `~/Obsidian` | Path to Obsidian vault |
| `transcript_folder` | `Sources/YouTube Transcripts` | Subfolder within the vault |

Keys written by older versions (the transcription strategy and the ffmpeg location) are ignored and dropped the next time the config is saved.

## Obsidian plugin

The companion Obsidian plugin lives in the repository root, next to this
folder. It is a thin UI over this CLI: paste a YouTube URL and it runs
`yt-transcribe video <url> --json` (or `playlist`), then opens the resulting
vault note. Install it with [BRAT](https://github.com/TfTHacker/obsidian42-brat).

The plugin depends on this CLI's `--json` output contract, so change both
together. On the first transcription of a session it runs `yt-transcribe
--version` and shows a notice when the engine is older than the plugin needs;
update it as described under "Update the engine" in the top-level README (on Windows, use
`skills/yt-transcribe/update-engine.ps1` so a running process cannot break the upgrade).

## Architecture

```
src/yt_transcribe/       # Core library
  config.py              # YAML config (vault path and folder)
  models.py              # Immutable dataclasses (frozen=True)
  exceptions.py          # Typed error hierarchy
  captions.py            # YouTube caption track fetching and parsing
  download.py            # yt-dlp: metadata and captions in one call
  transcribe.py          # Transcript built from the caption track
  storage.py             # Markdown output with frontmatter
  search.py              # Full-text search across vault
  failures.py            # Record for a failed playlist video
  video_id.py            # Video ID from a YouTube URL
  cli.py                 # CLI (click + rich)
```

## Changelog

### 0.14.0

- **The MCP server is removed.** Claude Code and the Obsidian plugin run the `yt-transcribe` command, so the server was a long-running process (about 60 to 80 MB per Claude session) that kept running the code it started with and held the install's files open on Windows. Gone with it: the `yt-transcribe-server` command, its six tools (`get_transcripts`, `get_transcript`, `get_playlist_transcripts`, `list_transcripts`, `search_transcripts`, `server_status`), the `output_dir` argument (use `--vault` and `--folder` on the CLI), the background worker and its progress protocol, the registration scripts, the URL classifier that only the server called (the plugin classifies links itself), and the `mcp` dependency with the libraries only it needed (the lock file goes from 53 to 24 packages). The CLI, its `--json` contract and the saved notes are unchanged.
- If you registered the server in a client, remove the registration (for Claude Code: `claude mcp remove yt-transcribe`). `uv tool upgrade` removes the old `yt-transcribe-server` launcher from uv's executable folder (`~/.local/bin`) by itself.
- Added `skills/yt-transcribe/update-engine.ps1` (tooling around the engine). On Windows, `uv tool upgrade` fails while any process from the tool is running and leaves the `yt-transcribe.exe` launcher deleted, and a second plain upgrade then reports "Nothing to upgrade". The script refuses while the tool is in use (exit code 2), upgrades or installs, checks that `yt-transcribe --version` answers, and reinstalls when it does not. The Claude Code skill now tells Claude to run it. Pester tests are in `skills/yt-transcribe/update-engine.Tests.ps1`.

### 0.13.0

- **The cloud (AssemblyAI) strategy is removed.** Captions are the only source of text. Gone with it: the `assemblyai` provenance value, the `setup-ffmpeg` command, the `[cloud]` extra, the AssemblyAI key lookup (environment variable and OS keyring), the `strategy` argument of the MCP tools, the `transcription_strategy` and `ffmpeg_location` settings, and the `assemblyai`, `keyring` and `imageio-ffmpeg` dependencies (eleven fewer packages in all). A video without captions fails with `NoCaptionsError` and nothing else is tried.
- `--strategy` is still accepted as `captions`, hidden from the help, so plugin versions before 0.5.0 keep working. `--strategy cloud` is refused with a message saying the strategy was removed.
- Old config files load unchanged: the obsolete keys are ignored and dropped on the next save. Notes already saved with `source: assemblyai` stay readable.
- On a machine that used the cloud strategy, two leftovers can be deleted by hand: the downloaded ffmpeg in `~/.yt-transcribe/bin` and any AssemblyAI key stored in the OS credential store under the service name `yt-transcribe`.

### 0.12.1

- `yt-transcribe video` now looks for a saved note by the video ID in the URL before it contacts YouTube, so a video that is already in the vault is answered in about the engine's start-up time (about 2 seconds) instead of about 5, with no network request. The MCP server already worked this way. A link form the ID pattern does not recognise still works: the vault is checked again once YouTube reports the ID. The reported title now comes from the saved note.
- The repository ships a Claude Code skill, `skills/yt-transcribe`, that runs the CLI instead of the MCP server. The MCP server stays in the package and is now optional.

### 0.12.0

- `yt-transcribe --version` prints the engine version. The MCP `server_status` tool now reads the same installed-package version instead of a separate constant that had fallen out of date. The Obsidian plugin (0.4.0) uses the flag to warn when the engine is older than it needs.
- A playlist no longer stops at the first video that fails. Failed videos are listed under `failed` (`video_id`, `title`, `error`, `error_type`) in the `playlist --json` output and in the MCP playlist result, with a warning logged per video; the rest are saved. Re-run the same playlist to retry only the failed videos, since saved ones are skipped. Playlist-level errors (invalid or empty playlist) still exit 1.
- Dependency updates clear every advisory `pip-audit` reported (yt-dlp, mcp, starlette, cryptography, pyjwt, python-multipart, anyio, idna, pydantic-settings, pygments, pytest). `yt-dlp` has a floor of 2026.7.4, `mcp` is held to `>=1.28.1,<2` (mcp 2.x removes the server API this code uses) and `assemblyai` to `>=1,<2` (tested on 1.6.1; the cloud path was not run against the live service).

### 0.11.0

- `yt-transcribe video --no-save` prints the transcript text as one JSON line and writes no file, for backend tools that store the transcript themselves.

### 0.10.0

- `yt-transcribe playlist` gained `--json`, `--vault`, `--folder`, and `--strategy` options, mirroring the `video` command. `--json` emits a single line with a `count` and a per-video `transcripts` list (one markdown file is written per video). This lets the Obsidian plugin drive playlists and parse the results.

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
