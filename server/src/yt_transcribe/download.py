"""YouTube data module using the yt-dlp Python API for metadata and captions.

Performance-critical: uses a single extract_info call via extract_video_data() to
avoid redundant network round-trips for metadata and captions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yt_dlp
from tenacity import retry, stop_after_attempt, wait_exponential

from yt_transcribe.captions import CaptionResult, fetch_captions
from yt_transcribe.exceptions import (
    CaptionFetchError,
    PlaylistNotFoundError,
    VideoNotFoundError,
    VideoUnavailableError,
)
from yt_transcribe.models import Segment, VideoInfo

# Strings in yt-dlp errors that indicate a private/unavailable video
_UNAVAILABLE_PATTERNS = ("private video", "age-restricted", "not available", "sign in")


@dataclass(frozen=True)
class VideoData:
    """All data extracted from a single yt-dlp call: metadata and captions.

    caption_kind/caption_language record the provenance of the winning caption
    track ("manual" or "auto" plus its language key), or None when captions are
    absent. captions_fetch_failed distinguishes a video whose caption tracks
    exist but could not be fetched (retryable) from a truly caption-less one.
    """
    video_info: VideoInfo
    captions: tuple[Segment, ...] | None
    raw_info: dict[str, Any]
    caption_kind: str | None = None
    caption_language: str | None = None
    captions_fetch_failed: bool = False


def _is_unavailable_error(error_msg: str) -> bool:
    """Check if the error message indicates a private or unavailable video."""
    lower = error_msg.lower()
    return any(pattern in lower for pattern in _UNAVAILABLE_PATTERNS)


def _build_video_info(info: dict[str, Any], playlist_title: str | None = None) -> VideoInfo:
    """Build an immutable VideoInfo from a yt-dlp info dict.

    Args:
        info: yt-dlp extracted info dictionary.
        playlist_title: Title of the parent playlist, or None for standalone videos.

    Returns:
        A frozen VideoInfo dataclass instance.
    """
    return VideoInfo(
        video_id=info["id"],
        title=info.get("title", "Untitled"),
        channel=info.get("channel", info.get("uploader", "Unknown")),
        url=info.get("webpage_url", info.get("url", "")),
        duration_seconds=int(info.get("duration", 0)),
        playlist_title=playlist_title,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
def extract_video_data(url: str) -> VideoData:
    """Extract metadata and captions in a single yt-dlp call.

    This is the primary entry point for video processing. It combines what was
    previously 3 separate extract_info calls into one, saving 15-30 seconds.

    Args:
        url: YouTube video URL.

    Returns:
        VideoData with video_info and captions (if available).

    Raises:
        VideoNotFoundError: Video does not exist or URL is invalid.
        VideoUnavailableError: Video is private, age-restricted, or region-blocked.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3",
    }
    captions_fetch_failed = False
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # Captions must be fetched while this YoutubeDL is alive: its
            # urlopen opener carries the client headers/impersonation that
            # YouTube's timedtext endpoint expects. The info dict itself only
            # ever carries caption URLs, never inline data.
            caption_result: CaptionResult | None = None
            if info is not None:
                try:
                    caption_result = fetch_captions(ydl, info)
                except CaptionFetchError:
                    # Recorded on VideoData rather than raised: the metadata
                    # stays usable, and transcription reports a retryable
                    # error later.
                    captions_fetch_failed = True
    except Exception as exc:
        msg = str(exc)
        if _is_unavailable_error(msg):
            raise VideoUnavailableError(msg) from exc
        raise VideoNotFoundError(msg) from exc

    if info is None:
        raise VideoNotFoundError(f"No info returned for URL: {url}")

    video_info = _build_video_info(info)

    return VideoData(
        video_info=video_info,
        captions=caption_result.segments if caption_result is not None else None,
        raw_info=info,
        caption_kind=caption_result.kind if caption_result is not None else None,
        caption_language=caption_result.language if caption_result is not None else None,
        captions_fetch_failed=captions_fetch_failed,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
def get_playlist_info(url: str) -> tuple[VideoInfo, ...]:
    """Expand a playlist URL into a tuple of VideoInfo objects.

    Args:
        url: YouTube playlist URL.

    Returns:
        Tuple of VideoInfo, one per video in the playlist.

    Raises:
        PlaylistNotFoundError: Playlist does not exist or is empty.
    """
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": False}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PlaylistNotFoundError(str(exc)) from exc

    if info is None:
        raise PlaylistNotFoundError(f"No info returned for playlist: {url}")

    entries = info.get("entries", [])
    # Filter out None entries (unavailable videos in playlist)
    valid_entries = [e for e in entries if e is not None]

    if not valid_entries:
        raise PlaylistNotFoundError(f"Playlist is empty: {url}")

    playlist_title = info.get("title", "Unknown Playlist")
    return tuple(_build_video_info(entry, playlist_title) for entry in valid_entries)
