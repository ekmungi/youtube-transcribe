---
name: yt-transcribe
description: >
  Use when the user gives a YouTube video or playlist link to transcribe or save, or asks
  to list or search saved YouTube transcripts. Runs the local yt-transcribe command, which
  saves a markdown note into the vault's Youtube Transcriptions folder.
---

# yt-transcribe

The tool is a command, `yt-transcribe`, already on PATH. Run it with the Bash tool. It reads its settings from `~/.yt-transcribe/config.yaml`, so the working directory does not matter. By default it saves into `03 RESOURCES/Youtube Transcriptions` in the vault, the folder `vault-map.md` assigns to saved transcripts, and it skips videos already saved there.

## Commands
- One video: `yt-transcribe video "<url>" --json`
- Playlist (a link with `list=` and no `v=`): `yt-transcribe playlist "<url>" --json`. Run it in the background; it can take minutes.
- Text only, nothing saved: add `--no-save`.
- Another folder: add both `--vault "<vault root>"` and `--folder "<folder inside the vault>"`, resolving the folder through `vault-map.md`.
- Saved notes: `yt-transcribe list` and `yt-transcribe search "<words>"`.

## Reading the result
The last line of output is one JSON object.
- Success: `path`, `title`, `source`, `caption_language`, `cached`. For a playlist: `count`, `transcripts` and `failed`.
- Failure: `error` and `error_type`.
Tell the user the path. Read the note with the vault tools only if they want its content.

## When it fails
- `NoCaptionsError`: the video has no captions. Say so and ask before retrying with `--strategy cloud`, which sends the audio to AssemblyAI and costs money.
- `CaptionFetchError`: YouTube is rate limiting. Suggest retrying in a few minutes; do not offer cloud.
- `failed` entries in a playlist: list them. Running the same playlist again retries only those.
- Command not found: run `yt-transcribe --version`, then reinstall with `uv tool install --reinstall --native-tls --python 3.12 "git+https://github.com/ekmungi/youtube-transcribe.git#subdirectory=server"`.
