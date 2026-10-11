---
name: yt-transcribe
description: >
  Use when the user gives a YouTube video or playlist link to transcribe or save, or asks
  to list or search saved YouTube transcripts, or asks to update the yt-transcribe command.
  Runs the local yt-transcribe command, which saves a markdown note into the vault's
  Youtube Transcriptions folder.
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
- `NoCaptionsError`: the video has no captions, so it cannot be transcribed. Say so; there is no other source of text.
- `CaptionFetchError`: YouTube is rate limiting. Suggest retrying in a few minutes.
- `failed` entries in a playlist: list them. Running the same playlist again retries only those.
- Command not found: run the update script below. It reinstalls the command when the launcher is missing.

## Updating the command
Run the script that sits next to this file, from this skill's base directory. Do not run `uv tool upgrade` by hand: on Windows it breaks the command if anything from the tool is still running.

`powershell -NoProfile -ExecutionPolicy Bypass -File "<base directory>\update-engine.ps1"`

Exit code 0 means updated and working. Exit code 2 means a transcription or server from the tool is still running: tell the user, and do not stop it for them. Exit code 1 means the update failed: show the output.
