"""Read the video ID out of a YouTube URL.

Used to look a video up in the vault without contacting YouTube. Deciding whether
a link is a single video or a playlist is left to the caller: the CLI has one
command for each, and the Obsidian plugin classifies the link itself.
"""

from __future__ import annotations

import re

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
