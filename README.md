# YouTube Transcribe (Obsidian plugin)

A lightweight Obsidian plugin that transcribes YouTube videos into vault notes by
calling the local `yt-transcribe` CLI. It is captions-first: by default it fetches
a video's existing captions (instant and free) and only uses cloud speech-to-text
when you explicitly opt in.

The plugin is a thin UI. The CLI does the work and writes a markdown note directly
into your vault; the plugin's job is to take a URL, invoke the CLI, and open the
resulting note.

## How it works

1. You provide a YouTube URL (via a prompt or your clipboard).
2. The plugin runs `yt-transcribe video <url> --json --strategy <captions|cloud>`.
3. The CLI writes a transcript note into the vault and prints a JSON result.
4. The plugin opens that note (or reports its location).

## Prerequisites

- The `yt-transcribe` CLI, version 0.7.0 or newer, installed and available on your
  PATH (or configured explicitly in the plugin settings).
- The vault path in `~/.yt-transcribe/config.yaml` must point at the same vault you
  run this plugin in, so the note the CLI writes lands inside this vault and can be
  opened directly.
- For the `cloud` strategy only: an AssemblyAI API key and `ffmpeg`. You can install
  ffmpeg with the "Download ffmpeg" button in this plugin's settings. The `captions`
  strategy needs neither.

## Installation

### Via BRAT (recommended)

[BRAT](https://github.com/TfTHacker/obsidian42-brat) installs and auto-updates
plugins from GitHub before they reach the community store.

1. Install the "BRAT" plugin from the community store and enable it.
2. Open the command palette and run "BRAT: Add a beta plugin for testing".
3. Enter this repository: `ekmungi/obsidian-youtube-transcribe`.
4. BRAT downloads the latest release and installs the plugin.
5. Enable "YouTube Transcribe" under Settings -> Community plugins.

BRAT keeps the plugin updated as new releases are published.

### Manual

1. Download `manifest.json`, `main.js`, and `styles.css` from the
   [latest release](https://github.com/ekmungi/obsidian-youtube-transcribe/releases/latest).
2. Copy them into `<vault>/.obsidian/plugins/youtube-transcribe/`.
3. Enable "YouTube Transcribe" under Settings -> Community plugins.

### Build from source

```
npm install
npm run build
```

This produces `main.js`. Copy it together with `manifest.json` and `styles.css`
into the plugin folder above.

## Usage

The plugin adds two commands (open the command palette with Ctrl/Cmd-P):

- **Transcribe YouTube video** - opens a prompt for a URL. If your clipboard holds
  a YouTube link, the field is pre-filled. Submit to transcribe.
- **Transcribe YouTube video from clipboard** - no prompt; reads the clipboard,
  checks that it looks like a YouTube URL, and transcribes it directly.

There is also a ribbon icon (a YouTube glyph in the left sidebar) that triggers the
prompt command.

When a video has no captions and you ran with the `captions` strategy, the plugin
offers a one-click retry using cloud speech-to-text.

## Settings

- **Executable path** - path to the `yt-transcribe` CLI. Defaults to
  `yt-transcribe` (assumes it is on your PATH). Set an absolute path if not.
- **Default strategy** - `captions` (default) or `cloud`.
- **Transcript folder** - vault folder to write transcripts into. Start typing
  to search your vault's folders. Leave empty to use the location configured in
  the CLI (`~/.yt-transcribe/config.yaml`). When set, the plugin writes into this
  vault at the chosen folder regardless of the CLI's configured vault.
- **Open note after transcribing** - whether to open the created note
  automatically on success (default on).
- **Download ffmpeg** - a button that runs `yt-transcribe setup-ffmpeg`, which
  downloads a static ffmpeg into `~/.yt-transcribe/bin` and records it in the CLI
  config. Only needed for the `cloud` strategy; `captions` never uses ffmpeg.

## Captions vs cloud

- **captions** is instant and free. It fetches the captions already published with
  the video. No API key or extra tooling required.
- **cloud** sends the video's audio to AssemblyAI for speech-to-text. It requires
  an AssemblyAI API key and `ffmpeg`, and incurs whatever cost your AssemblyAI plan
  charges. Use it only when a video has no usable captions.

## Notes

- Desktop only. The plugin uses Node's `child_process` to launch the CLI and the
  filesystem adapter to resolve the created note, neither of which is available on
  Obsidian mobile.
