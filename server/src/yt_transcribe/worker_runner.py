"""Subprocess worker execution for the MCP server: spawn, progress relay,
and inactivity watchdog. Moved out of mcp_server.py; no behavior change."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any, Literal

from mcp.server.lowlevel.server import request_ctx

# Inactivity timeout: kill worker if no stderr output for this long
_INACTIVITY_TIMEOUT_SECONDS = 300  # 5 minutes
# How often the watchdog checks for inactivity
_WATCHDOG_CHECK_INTERVAL = 30  # seconds

# Human-readable labels for worker progress stages
_STAGE_LABELS = {
    "downloading": "Downloading video metadata",
    "transcribing": "Transcribing",
    "saving": "Saving to vault",
    "playlist_fetch": "Fetching playlist info",
    "video": "Processing video",
    "playlist_complete": "Playlist complete",
}


async def log_to_client(
    message: str,
    level: Literal["debug", "info", "warning", "error"] = "info",
) -> None:
    """Send a log notification to the MCP client (Claude Code).

    Messages appear inline in the conversation, giving the user
    visibility into what the server is doing during long operations.

    Args:
        message: Human-readable status message.
        level: Log level (debug, info, warning, error).
    """
    try:
        ctx = request_ctx.get()
        await ctx.session.send_log_message(
            level=level, data=message, logger="yt-transcribe",
        )
    except Exception:
        pass  # Outside request context or client doesn't support logging


def _format_started_message(event: dict[str, Any]) -> str:
    """Format a 'started' progress event into a log line.

    Args:
        event: Parsed progress event dict from the worker's stderr.

    Returns:
        Human-readable status line ending with '...'.
    """
    label = _STAGE_LABELS.get(event.get("stage", "?"), event.get("stage", "?"))
    extra = ""
    if "strategy" in event:
        extra = f" ({event['strategy']})"
    if "index" in event and "total" in event:
        extra = f" [{event['index']}/{event['total']}]"
    if "title" in event:
        extra += f" - {event['title']}"
    return f"{label}{extra}..."


def _format_done_message(event: dict[str, Any]) -> str:
    """Format a 'done' progress event into a log line.

    'total' is overloaded in worker events: per-video playlist events carry
    it as the video COUNT (paired with 'index'), while the single-video
    saving-done event carries it as total elapsed SECONDS. Only the latter
    is displayed as a duration; playlists report 'total_elapsed' instead.

    Args:
        event: Parsed progress event dict from the worker's stderr.

    Returns:
        Human-readable status line ending with 'done'.
    """
    label = _STAGE_LABELS.get(event.get("stage", "?"), event.get("stage", "?"))
    parts = [label]
    if "index" in event and "total" in event:
        parts = [f"{label} [{event['index']}/{event['total']}]"]
    if "title" in event:
        parts.append(f"- {event['title']}")
    if "elapsed" in event:
        parts.append(f"({event['elapsed']}s)")
    total_seconds = event.get("total_elapsed")
    if total_seconds is None and "index" not in event:
        total_seconds = event.get("total")
    if total_seconds is not None:
        parts.append(f"[total: {total_seconds}s]")
    if event.get("source") == "cache":
        parts.append("[cached]")
    return f"{' '.join(parts)} done"


async def _relay_progress(
    proc: asyncio.subprocess.Process,
    last_activity: dict[str, float],
) -> str:
    """Read stderr lines from worker and relay progress events as MCP logs.

    Progress lines have the format: PROGRESS:{"stage":"...","status":"..."}
    Other stderr lines are collected as error output. Every line (progress
    or not) updates last_activity["t"] for the inactivity watchdog.

    Args:
        proc: The running worker subprocess.
        last_activity: Mutable dict with key "t" tracking last activity time.

    Returns:
        Non-progress stderr content (for error reporting).
    """
    progress_prefix = "PROGRESS:"
    error_lines: list[str] = []

    assert proc.stderr is not None
    while True:
        line_bytes = await proc.stderr.readline()
        if not line_bytes:
            break
        # Every stderr line is a heartbeat
        last_activity["t"] = time.monotonic()
        line = line_bytes.decode(errors="replace").rstrip()

        if line.startswith(progress_prefix):
            try:
                event = json.loads(line[len(progress_prefix):])
                status = event.get("status", "?")
                if status == "started":
                    await log_to_client(_format_started_message(event))
                elif status == "done":
                    await log_to_client(_format_done_message(event))
            except (json.JSONDecodeError, KeyError):
                error_lines.append(line)
        else:
            error_lines.append(line)

    return "\n".join(error_lines)


async def _inactivity_watchdog(
    proc: asyncio.subprocess.Process,
    last_activity: dict[str, float],
) -> str:
    """Kill the worker if no stderr activity for _INACTIVITY_TIMEOUT_SECONDS.

    Checks every _WATCHDOG_CHECK_INTERVAL seconds. Returns an error message
    if the worker is killed, or empty string if the worker finishes normally.

    Args:
        proc: The running worker subprocess.
        last_activity: Mutable dict with key "t" tracking last activity time.

    Returns:
        Error message if killed, empty string otherwise.
    """
    while proc.returncode is None:
        await asyncio.sleep(_WATCHDOG_CHECK_INTERVAL)
        if proc.returncode is not None:
            break
        elapsed = time.monotonic() - last_activity["t"]
        if elapsed > _INACTIVITY_TIMEOUT_SECONDS:
            proc.kill()
            await proc.wait()
            minutes = int(_INACTIVITY_TIMEOUT_SECONDS // 60)
            await log_to_client(
                f"Worker killed: no activity for {minutes} minutes",
                level="error",
            )
            return f"Worker killed: no activity for {minutes} minutes"
    return ""


async def run_worker(request: dict[str, Any]) -> dict[str, Any]:
    """Spawn a subprocess worker for memory-heavy transcription.

    The worker imports heavy dependencies (yt-dlp, assemblyai, etc.),
    does the work, writes JSON to stdout, then exits -- freeing all memory.
    Progress events are streamed via stderr in real time.

    Uses an inactivity-based timeout instead of a hard deadline, so long
    videos can transcribe as long as they keep producing progress output.

    Args:
        request: Dict with 'command' key and command-specific arguments.

    Returns:
        Dict with the worker's JSON response, or an error dict.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "yt_transcribe.worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Send request to worker's stdin, then close it
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(request).encode())
    proc.stdin.close()

    # Shared mutable state for inactivity tracking
    last_activity: dict[str, float] = {"t": time.monotonic()}

    assert proc.stdout is not None
    stderr_task = asyncio.create_task(_relay_progress(proc, last_activity))
    stdout_task = asyncio.create_task(proc.stdout.read())
    watchdog_task = asyncio.create_task(_inactivity_watchdog(proc, last_activity))

    # Bundle work tasks so we can race them against the watchdog
    work_task: asyncio.Future[Any] = asyncio.ensure_future(
        asyncio.gather(stdout_task, stderr_task)
    )

    # Wait for either normal completion or watchdog kill
    racing: set[asyncio.Future[Any]] = {work_task, watchdog_task}
    done, pending = await asyncio.wait(
        racing,
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Cancel whichever side didn't finish
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # If watchdog killed the process, return its error
    if watchdog_task in done:
        watchdog_error = watchdog_task.result()
        if watchdog_error:
            return {"error": watchdog_error}

    # Normal completion path
    await proc.wait()

    stdout_bytes = b""
    error_output = ""
    if work_task.done() and not work_task.cancelled():
        try:
            stdout_bytes, error_output = work_task.result()
        except Exception:
            pass

    if proc.returncode != 0:
        err_msg = error_output.strip()[-500:] if error_output else "unknown error"
        return {"error": f"Worker failed (exit {proc.returncode}): {err_msg}"}

    raw = stdout_bytes.decode(errors="replace").strip()
    if not raw:
        return {"error": "Worker returned empty response"}

    try:
        response: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Worker returned invalid JSON: {raw[:200]}"}
    return response
