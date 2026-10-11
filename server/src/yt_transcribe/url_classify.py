"""Classify a YouTube URL as a single video or a playlist, and read its video ID.

Used to auto-route a URL to the right transcription path without the caller
having to know which kind it is, and to look a video up in the vault without
contacting YouTube.
"""

from __future__ import annotations

import re
from typing import Literal

UrlKind = Literal["video", "playlist"]

# A specific-video selector: any of these means the URL targets one video,
# even if a list= parameter is also present (the playlist is just context).
# The group captures the 11-character video ID.
_VIDEO_SELECTOR = re.compile(r"(?:v=|youtu\.be/|/embed/|/v/|/shorts/)([a-zA-Z0-9_-]{11})")


def extract_video_id(url: str) -> str | None:
    """Read the video ID out of a YouTube video URL.

    Args:
        url: A YouTube URL in any common format (watch, youtu.be, shorts, embed).

    Returns:
        The 11-character video ID, or None when the URL names no specific video
        (a playlist-only link, a channel link, or text that is not a URL).
    """
    match = _VIDEO_SELECTOR.search(url)
    return match.group(1) if match else None


def classify_youtube_url(url: str) -> UrlKind:
    """Decide whether a YouTube URL points to a single video or a playlist.

    A URL is a playlist only when it carries a ``list=`` parameter and has no
    specific-video selector. A watch URL that also carries ``&list=...`` is
    treated as a single video, because the user pointed at one specific video.

    Args:
        url: A YouTube URL in any common format.

    Returns:
        "playlist" if the URL targets a playlist with no specific video,
        otherwise "video".
    """
    if _VIDEO_SELECTOR.search(url):
        return "video"
    if "list=" in url:
        return "playlist"
    return "video"
