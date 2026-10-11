"""Record shape for a playlist video that could not be transcribed.

A playlist keeps going past one bad video and lists it under "failed"; this is
the shape of each entry in that list.
"""

from __future__ import annotations


def failure_entry(video_id: str, title: str, exc: Exception) -> dict[str, str]:
    """Describe one failed playlist video for a JSON result.

    Args:
        video_id: YouTube video ID of the video that failed.
        title: Video title, so the caller can show a readable message.
        exc: The engine error that stopped this video.

    Returns:
        Dict with video_id, title, error (the message) and error_type (the
        exception class name, so callers can branch on e.g. NoCaptionsError).
    """
    return {
        "video_id": video_id,
        "title": title,
        "error": str(exc),
        "error_type": type(exc).__name__,
    }
