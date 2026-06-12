"""Classify a YouTube URL as a single video or a playlist.

Used to auto-route a URL to the right transcription path without the caller
having to know which kind it is.
"""

from __future__ import annotations

import re
from typing import Literal

UrlKind = Literal["video", "playlist"]

# A specific-video selector: any of these means the URL targets one video,
# even if a list= parameter is also present (the playlist is just context).
_VIDEO_SELECTOR = re.compile(r"(?:v=|youtu\.be/|/embed/|/v/|/shorts/)[a-zA-Z0-9_-]{11}")


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
