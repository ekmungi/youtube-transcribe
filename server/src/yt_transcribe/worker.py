"""Subprocess worker for memory-heavy transcription tasks.

Runs in a separate process so that heavy dependencies (assemblyai,
yt-dlp) are loaded only here and fully freed when the worker exits.
The MCP server stays lean at ~20 MB.

Protocol:
  - Reads a JSON request from stdin.
  - Writes progress lines to stderr: ``PROGRESS:{"stage":...,"elapsed":...}``
  - Writes a JSON response to stdout, then exits with code 0 or 1.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from dataclasses import replace
from typing import Any

# Heavy imports are deferred to handler functions so the worker
# module itself stays light until a command actually runs.

# Prefix for progress lines on stderr (parsed by MCP server)
_PROGRESS_PREFIX = "PROGRESS:"


def _progress(stage: str, status: str = "started", **extra: Any) -> None:
    """Write a progress event to stderr for the MCP server to relay.

    Args:
        stage: Current stage name (downloading, transcribing, saving).
        status: Stage status (started, done).
        **extra: Additional fields (elapsed, strategy, title, etc.).
    """
    event = {"stage": stage, "status": status, **extra}
    sys.stderr.write(f"{_PROGRESS_PREFIX}{json.dumps(event)}\n")
    sys.stderr.flush()


def _apply_overrides(
    strategy: str | None = None,
    output_dir: str | None = None,
) -> Any:
    """Load config and apply optional per-call overrides.

    Args:
        strategy: Override transcription strategy (captions, cloud).
        output_dir: Absolute directory to write the transcript into. When
            given, it becomes the vault root with an empty subfolder so files
            land directly in output_dir; when None, the configured location
            (vault + transcript_folder) is kept.

    Returns:
        Config with the overrides applied.
    """
    from yt_transcribe.config import load_config
    from yt_transcribe.models import TranscriptionStrategy

    config = load_config()
    if strategy:
        config = replace(config, transcription_strategy=TranscriptionStrategy(strategy))
    if output_dir:
        config = replace(
            config, obsidian_vault_path=output_dir, transcript_folder="",
        )
    return config


def _transcript_metadata(transcript: Any) -> dict[str, Any]:
    """Extract response metadata fields from a Transcript.

    Args:
        transcript: Transcript with source and caption_language provenance.

    Returns:
        Dict with source (str) and caption_language (str or None).
    """
    return {
        "source": transcript.source.value,
        "caption_language": transcript.caption_language,
    }


def _handle_get_transcript(request: dict[str, Any]) -> dict[str, Any]:
    """Transcribe a single video: download, transcribe, save.

    Always transcribes inline regardless of video duration.

    Args:
        request: Dict with video_url and optional strategy/include_text/
            output_dir keys.

    Returns:
        Dict with path, word count, and source metadata (text if requested).
    """
    from yt_transcribe import storage, transcribe
    from yt_transcribe.download import extract_video_data

    video_url = request["video_url"]
    config = _apply_overrides(request.get("strategy"), request.get("output_dir"))

    # Stage 1: Download metadata + captions + audio URL
    _progress("downloading", "started")
    t0 = time.monotonic()
    video_data = extract_video_data(video_url)
    video = video_data.video_info
    dl_elapsed = round(time.monotonic() - t0, 1)
    _progress("downloading", "done", elapsed=dl_elapsed, title=video.title)

    # Stage 2: Transcribe (always inline)
    strategy = str(config.transcription_strategy.value)
    _progress("transcribing", "started", strategy=strategy)
    t1 = time.monotonic()
    transcript_result = transcribe.transcribe_video_fast(video_data, config)
    tx_elapsed = round(time.monotonic() - t1, 1)
    _progress("transcribing", "done", elapsed=tx_elapsed)

    # Stage 3: Save to vault
    _progress("saving", "started")
    t2 = time.monotonic()
    saved_path = storage.save_transcript(config, transcript_result)
    save_elapsed = round(time.monotonic() - t2, 1)
    total_elapsed = round(time.monotonic() - t0, 1)
    _progress("saving", "done", elapsed=save_elapsed, total=total_elapsed)

    result: dict[str, Any] = {
        "title": video.title,
        "path": str(saved_path),
        "word_count": len(transcript_result.text.split()),
        "duration_seconds": video.duration_seconds,
        **_transcript_metadata(transcript_result),
    }
    if request.get("include_text"):
        result["text"] = transcript_result.text
    return result


def _handle_get_playlist_transcripts(request: dict[str, Any]) -> dict[str, Any]:
    """Transcribe all videos in a playlist.

    Always processes inline regardless of total duration. Already-saved
    videos are skipped and reported with source='cache'.

    Args:
        request: Dict with playlist_url and optional strategy/include_text/
            output_dir keys.

    Returns:
        Dict with per-video results carrying path and source metadata.
    """
    from yt_transcribe import download, storage, transcribe
    from yt_transcribe.download import extract_video_data
    from yt_transcribe.models import TranscriptSource

    playlist_url = request["playlist_url"]
    config = _apply_overrides(request.get("strategy"), request.get("output_dir"))

    _progress("playlist_fetch", "started")
    t0 = time.monotonic()
    videos = download.get_playlist_info(playlist_url)
    _progress("playlist_fetch", "done",
              elapsed=round(time.monotonic() - t0, 1), count=len(videos))

    results: list[dict[str, Any]] = []
    for i, video in enumerate(videos, 1):
        existing = storage.find_existing(config, video.video_id)
        if existing is not None:
            _progress("video", "done",
                      index=i, total=len(videos), title=video.title,
                      source=TranscriptSource.CACHE.value)
            # Honor the tool contract for cached entries too: read the stored
            # provenance back (original_source/caption_language are None for
            # files saved before 0.7.0) and the body when text was requested.
            stored = storage.read_stored_transcript(existing)
            cached_entry: dict[str, Any] = {
                "title": video.title,
                "source": TranscriptSource.CACHE.value,
                "original_source": stored.source,
                "caption_language": stored.caption_language,
                "path": str(existing),
                "word_count": len(stored.body.split()),
            }
            if request.get("include_text"):
                cached_entry["text"] = stored.body
            results.append(cached_entry)
            continue

        _progress("video", "started",
                  index=i, total=len(videos), title=video.title)
        tv0 = time.monotonic()
        video_data = extract_video_data(video.url)
        transcript_result = transcribe.transcribe_video_fast(video_data, config)
        saved_path = storage.save_transcript(config, transcript_result)
        _progress("video", "done",
                  index=i, total=len(videos), title=video.title,
                  elapsed=round(time.monotonic() - tv0, 1),
                  source=transcript_result.source.value)
        entry: dict[str, Any] = {
            "title": video.title,
            "path": str(saved_path),
            "word_count": len(transcript_result.text.split()),
            **_transcript_metadata(transcript_result),
        }
        if request.get("include_text"):
            entry["text"] = transcript_result.text
        results.append(entry)

    total_elapsed = round(time.monotonic() - t0, 1)
    _progress("playlist_complete", "done",
              count=len(results), total_elapsed=total_elapsed)
    return {"transcripts": results}


_HANDLERS: dict[str, Any] = {
    "get_transcript": _handle_get_transcript,
    "get_playlist_transcripts": _handle_get_playlist_transcripts,
}


def main() -> None:
    """Read JSON request from stdin, dispatch to handler, write JSON response.

    Stdout is redirected to stderr during handler execution so that any
    library output (e.g. yt-dlp download progress) doesn't corrupt the
    JSON response.  The JSON result is written to the real stdout fd
    after the handler completes.
    """
    import os

    # Graceful shutdown: on SIGTERM/SIGINT, exit cleanly instead of traceback
    def _shutdown(signum: int, _frame: Any) -> None:
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    raw = sys.stdin.buffer.read()
    if not raw:
        json.dump({"error": "Empty request"}, sys.stdout)
        sys.exit(1)

    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"error": f"Invalid JSON: {exc}"}, sys.stdout)
        sys.exit(1)

    command = request.get("command", "")
    handler = _HANDLERS.get(command)

    if handler is None:
        json.dump({"error": f"Unknown command: {command}"}, sys.stdout)
        sys.exit(1)

    # Redirect stdout -> stderr so yt-dlp progress doesn't corrupt JSON
    real_stdout_fd = os.dup(1)
    os.dup2(2, 1)

    try:
        result = handler(request)
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}

    # Restore real stdout and write the JSON result
    os.dup2(real_stdout_fd, 1)
    os.close(real_stdout_fd)

    json.dump(result, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
