"""MCP server exposing YouTube transcript tools via stdio transport.

5 tools: get_transcript, get_playlist_transcripts, list_transcripts,
search_transcripts, server_status.

Lightweight tools (list, search, status) run inline.  Heavy tools
(get_transcript, get_playlist) spawn a subprocess worker (see
worker_runner.py) so the MCP server process stays lean (~20 MB) and
all transcription memory is freed when the worker exits.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from yt_transcribe import search, storage
from yt_transcribe.config import load_config
from yt_transcribe.tool_schemas import TOOLS as _TOOLS
from yt_transcribe.url_classify import classify_youtube_url
from yt_transcribe.worker_runner import log_to_client as _log
from yt_transcribe.worker_runner import run_worker as _run_worker

# Server start time for uptime reporting
_START_TIME = time.monotonic()
_VERSION = "0.8.1"

# Track server activity for status reporting
_tool_call_count = 0
_last_tool_call: str | None = None
_active_tool: str | None = None

# Pattern to extract video ID from common YouTube URL formats
_VIDEO_ID_PATTERN = re.compile(
    r"(?:v=|youtu\.be/|/embed/|/v/|/shorts/)([a-zA-Z0-9_-]{11})"
)


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from a URL.

    Args:
        url: YouTube video URL in any common format.

    Returns:
        11-character video ID, or None if not found.
    """
    match = _VIDEO_ID_PATTERN.search(url)
    return match.group(1) if match else None


# -- Lightweight tool handlers (run inline) --------------------------------


def _sync_list_transcripts(folder: str | None = None) -> dict[str, Any]:
    """List saved transcripts in the Obsidian vault.

    Args:
        folder: Optional subfolder name to filter.

    Returns:
        Dict with list of transcript metadata entries.
    """
    config = load_config()
    entries = search.list_transcripts(config, folder=folder)
    return {
        "transcripts": [
            {
                "title": e.title,
                "channel": e.channel,
                "video_id": e.video_id,
                "path": str(e.file_path),
            }
            for e in entries
        ]
    }


def _sync_search_transcripts(query: str) -> dict[str, Any]:
    """Full-text search across saved transcript content.

    Args:
        query: Search string (case-insensitive).

    Returns:
        Dict with list of matching snippets.
    """
    config = load_config()
    matches = search.search_transcripts(config, query)
    return {
        "matches": [
            {
                "title": m.title,
                "channel": m.channel,
                "snippet": m.snippet,
                "path": str(m.file_path),
            }
            for m in matches
        ]
    }


def _cache_hit_result(
    video_id: str,
    existing_path: Path,
    include_text: bool,
) -> dict[str, Any]:
    """Build a cache-hit response that honors the tool contract.

    Reads the cached markdown back so the response carries title,
    caption_language, original_source (the stored provenance; None for files
    saved before 0.7.0), word_count, and the body text when requested.
    source stays 'cache' per the documented provenance values.

    Args:
        video_id: Extracted YouTube video ID.
        existing_path: Path to the cached transcript markdown file.
        include_text: If True, include the stored body text inline.

    Returns:
        Response dict for the get_transcript tool.
    """
    stored = storage.read_stored_transcript(existing_path)
    result: dict[str, Any] = {
        "video_id": video_id,
        "source": "cache",
        "path": str(existing_path),
        "title": stored.title,
        "original_source": stored.source,
        "caption_language": stored.caption_language,
        "word_count": len(stored.body.split()),
    }
    if include_text:
        result["text"] = stored.body
    return result


# -- Async tool handlers ---------------------------------------------------


async def handle_get_transcript(
    video_url: str,
    strategy: str | None = None,
    include_text: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Transcribe a single video via subprocess worker.

    Checks the cache first (lightweight, inline). On cache miss, spawns
    a worker subprocess for the heavy download + transcription work.

    Args:
        video_url: YouTube video URL.
        strategy: Transcription strategy override (captions or cloud).
        include_text: If True, include full transcript text in response.
        output_dir: Absolute directory to write into; when given, both the
            cache check and the save target are rooted here instead of the
            configured vault.

    Returns:
        Dict with metadata, source provenance, and file path (and
        optionally text).
    """
    # Cache-first: check by video_id (no heavy imports). Root the lookup at
    # output_dir when provided so we don't miss a transcript the caller already
    # saved there (or, worse, report a hit from the unrelated configured vault).
    await _log(f"Checking cache for {video_url}...")
    config = load_config()
    if output_dir:
        config = replace(config, obsidian_vault_path=output_dir, transcript_folder="")
    video_id = _extract_video_id(video_url)
    if video_id:
        existing_path = storage.find_existing(config, video_id)
        if existing_path is not None:
            await _log(f"Cache hit: {existing_path.name}")
            return _cache_hit_result(video_id, existing_path, include_text)

    # Cache miss: delegate to subprocess worker
    await _log(f"Transcribing video (strategy: {strategy or 'captions'})...")
    result = await _run_worker({
        "command": "get_transcript",
        "video_url": video_url,
        "strategy": strategy,
        "include_text": include_text,
        "output_dir": output_dir,
    })
    if "error" in result:
        await _log(f"Transcription failed: {result['error']}", level="error")
    else:
        await _log(f"Transcription complete: {result.get('title', video_url)}")
    return result


async def handle_get_playlist_transcripts(
    playlist_url: str,
    strategy: str | None = None,
    include_text: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Transcribe all videos in a playlist via subprocess worker.

    Args:
        playlist_url: YouTube playlist URL.
        strategy: Transcription strategy override (captions or cloud).
        include_text: If True, include full transcript text per video.
        output_dir: Absolute directory to write into; when given, the playlist
            transcripts are saved here instead of the configured vault.

    Returns:
        Dict with per-video results carrying paths and source provenance.
    """
    await _log(f"Processing playlist (strategy: {strategy or 'captions'})...")
    result = await _run_worker({
        "command": "get_playlist_transcripts",
        "playlist_url": playlist_url,
        "strategy": strategy,
        "include_text": include_text,
        "output_dir": output_dir,
    })
    if "error" in result:
        await _log(f"Playlist failed: {result['error']}", level="error")
    elif "transcripts" in result:
        count = len(result["transcripts"])
        await _log(f"Playlist complete: {count} video(s) transcribed")
    return result


async def handle_get_transcripts(
    urls: str | list[str],
    include_text: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Transcribe one or more YouTube URLs, auto-routing each by kind.

    Each URL is classified as a single video or a playlist and dispatched to
    the matching handler, so the caller never has to know which it is. Accepts
    a single URL string or a list (videos and playlists may be mixed).

    Args:
        urls: One YouTube URL, or a list of YouTube URLs.
        include_text: If True, include full transcript text in each result.
        output_dir: Absolute directory to write into; forwarded to every route.

    Returns:
        Dict with a "results" list, one entry per input URL, each tagged with
        its "kind" ("video" or "playlist") plus the routed handler's output.
    """
    url_list = [urls] if isinstance(urls, str) else list(urls)
    results: list[dict[str, Any]] = []
    for url in url_list:
        kind = classify_youtube_url(url)
        if kind == "playlist":
            routed = await handle_get_playlist_transcripts(
                url, include_text=include_text, output_dir=output_dir,
            )
        else:
            routed = await handle_get_transcript(
                url, include_text=include_text, output_dir=output_dir,
            )
        results.append({"url": url, "kind": kind, **routed})
    return {"results": results}


async def handle_list_transcripts(folder: str | None = None) -> dict[str, Any]:
    """List saved transcripts. Lightweight, runs inline."""
    return await asyncio.to_thread(_sync_list_transcripts, folder)


async def handle_search_transcripts(query: str) -> dict[str, Any]:
    """Search transcripts. Lightweight, runs inline."""
    return await asyncio.to_thread(_sync_search_transcripts, query)


async def handle_server_status() -> dict[str, Any]:
    """Return server health info: uptime, version, config, and activity."""
    uptime_seconds = time.monotonic() - _START_TIME
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)

    config = load_config()

    return {
        "status": "running",
        "version": _VERSION,
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": round(uptime_seconds),
        "tool_calls": _tool_call_count,
        "active_tool": _active_tool,
        "last_tool_called": _last_tool_call,
        "config": {
            "strategy": str(config.transcription_strategy.value),
            "vault_path": str(config.obsidian_vault_path),
        },
    }


# -- MCP server wiring -------------------------------------------------------

_TOOL_HANDLERS: dict[str, Any] = {
    "get_transcript": lambda args: handle_get_transcript(
        args["video_url"], args.get("strategy"),
        args.get("include_text", False), args.get("output_dir"),
    ),
    "get_playlist_transcripts": lambda args: handle_get_playlist_transcripts(
        args["playlist_url"], args.get("strategy"),
        args.get("include_text", False), args.get("output_dir"),
    ),
    "get_transcripts": lambda args: handle_get_transcripts(
        args["urls"], args.get("include_text", False), args.get("output_dir"),
    ),
    "list_transcripts": lambda args: handle_list_transcripts(args.get("folder")),
    "search_transcripts": lambda args: handle_search_transcripts(args["query"]),
    "server_status": lambda args: handle_server_status(),
}


def _create_server() -> Server:
    """Create and configure the MCP server with all tool handlers.

    Returns:
        Configured MCP Server instance.
    """
    server = Server("yt-transcribe")

    # The MCP SDK decorators are untyped; ignore strict-mode decorator errors.
    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        """Return the list of available tools."""
        return list(_TOOLS)

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Dispatch a tool call to the appropriate handler.

        Tracks activity state so server_status can report what's happening.

        Args:
            name: Tool name string.
            arguments: Tool arguments dict.

        Returns:
            List with single TextContent containing JSON result.
        """
        global _tool_call_count, _last_tool_call, _active_tool

        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        _tool_call_count += 1
        _active_tool = name
        _last_tool_call = name

        try:
            result = await handler(arguments)
            return [TextContent(type="text", text=json.dumps(result))]
        finally:
            _active_tool = None

    return server


async def _run_server() -> None:
    """Start the MCP server with stdio transport.

    No parent-process watchdog: on Windows, os.getppid() returns an
    intermediate shell PID that exits immediately, causing the watchdog
    to kill the server after 5 seconds.  The stdio transport already
    closes cleanly when the parent disconnects.
    """
    server = _create_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for yt-transcribe-server."""
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
