"""YouTube download module using yt-dlp Python API for metadata, captions, and audio.

Performance-critical: uses a single extract_info call via extract_video_data() to
avoid redundant network round-trips for metadata, captions, and audio URLs.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yt_dlp
from tenacity import retry, stop_after_attempt, wait_exponential

from yt_transcribe.captions import CaptionResult, fetch_captions
from yt_transcribe.exceptions import (
    CaptionFetchError,
    DownloadError,
    PlaylistNotFoundError,
    VideoNotFoundError,
    VideoUnavailableError,
)
from yt_transcribe.models import Segment, VideoInfo

logger = logging.getLogger(__name__)

# Strings in yt-dlp errors that indicate a private/unavailable video
_UNAVAILABLE_PATTERNS = ("private video", "age-restricted", "not available", "sign in")


@dataclass(frozen=True)
class VideoData:
    """All data extracted from a single yt-dlp call: metadata, captions, audio URL.

    caption_kind/caption_language record the provenance of the winning caption
    track ("manual" or "auto" plus its language key), or None when captions are
    absent. captions_fetch_failed distinguishes a video whose caption tracks
    exist but could not be fetched (retryable) from a truly caption-less one.
    """
    video_info: VideoInfo
    captions: tuple[Segment, ...] | None
    audio_url: str | None
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


def _extract_audio_url(info: dict[str, Any]) -> str | None:
    """Extract the best audio stream URL from yt-dlp info dict.

    Args:
        info: yt-dlp extracted info dictionary.

    Returns:
        Direct URL to best audio stream, or None if not found.
    """
    # yt-dlp populates 'url' with the selected format URL when format is specified
    # For audio-only, check formats list for best audio
    formats = info.get("formats", [])
    if not formats:
        return cast(str | None, info.get("url"))

    # Find best audio-only format (sorted by quality)
    audio_formats = [
        f for f in formats if f.get("acodec") != "none" and f.get("vcodec") in ("none", None)
    ]
    if audio_formats:
        # Sort by audio bitrate (abr), pick highest
        best = max(audio_formats, key=lambda f: f.get("abr", 0) or 0)
        return cast(str | None, best.get("url"))

    # Fallback: any format with audio
    with_audio = [f for f in formats if f.get("acodec") != "none"]
    if with_audio:
        best = max(with_audio, key=lambda f: f.get("abr", 0) or 0)
        return cast(str | None, best.get("url"))

    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
def extract_video_data(url: str) -> VideoData:
    """Extract metadata, captions, and audio URL in a single yt-dlp call.

    This is the primary entry point for video processing. It combines what was
    previously 3 separate extract_info calls into one, saving 15-30 seconds.

    Args:
        url: YouTube video URL.

    Returns:
        VideoData with video_info, captions (if available), and audio_url.

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
                    # Recorded on VideoData rather than raised: metadata and
                    # audio URL stay usable (e.g. for the cloud strategy), and
                    # the captions strategy reports a retryable error later.
                    captions_fetch_failed = True
    except Exception as exc:
        msg = str(exc)
        if _is_unavailable_error(msg):
            raise VideoUnavailableError(msg) from exc
        raise VideoNotFoundError(msg) from exc

    if info is None:
        raise VideoNotFoundError(f"No info returned for URL: {url}")

    video_info = _build_video_info(info)
    audio_url = _extract_audio_url(info)

    return VideoData(
        video_info=video_info,
        captions=caption_result.segments if caption_result is not None else None,
        audio_url=audio_url,
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


def _imageio_ffmpeg_path() -> str | None:
    """Return the static ffmpeg binary bundled by imageio-ffmpeg, if installed.

    imageio-ffmpeg is an optional dependency pulled in by the ``[cloud]`` extra.
    It is absent in the captions-only install, so the import is best-effort.

    Returns:
        Absolute path to the bundled ffmpeg binary, or None if unavailable.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - defensive against backend errors
        return None
    return path if path and Path(path).exists() else None


def _find_ffmpeg(ffmpeg_location: str) -> str | None:
    """Locate ffmpeg: explicit path > system PATH > common dirs > bundled.

    Args:
        ffmpeg_location: User-configured path, or empty string.

    Returns:
        A path to hand yt-dlp for an explicit/bundled binary, an empty string
        when ffmpeg is already on PATH (yt-dlp finds it itself), or None when
        ffmpeg cannot be located anywhere.
    """
    # User-configured path takes priority
    if ffmpeg_location and Path(ffmpeg_location).exists():
        return ffmpeg_location

    # Check if ffmpeg is on PATH already
    if shutil.which("ffmpeg"):
        return ""

    # Check common Windows install locations
    candidates = [
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            logger.info("Auto-detected ffmpeg at %s", candidate)
            return str(candidate)

    # Last resort: the static binary from the optional [cloud] extra
    bundled = _imageio_ffmpeg_path()
    if bundled:
        logger.info("Using bundled ffmpeg at %s", bundled)
        return bundled

    return None


def ensure_ffmpeg(ffmpeg_location: str = "") -> None:
    """Raise a clear, actionable error if ffmpeg cannot be located.

    Captions transcription (the default) never needs ffmpeg; only the cloud
    file-upload path does. Calling this before an audio download turns a
    cryptic yt-dlp post-processing failure into guidance the user can act on.

    Args:
        ffmpeg_location: User-configured ffmpeg path, or empty string.

    Raises:
        DownloadError: If ffmpeg is not found on the system.
    """
    if _find_ffmpeg(ffmpeg_location) is None:
        raise DownloadError(
            "ffmpeg is required for cloud transcription but was not found. "
            "The default captions strategy does not need it. To use cloud "
            "transcription, install ffmpeg -- on Windows run "
            "'winget install Gyan.FFmpeg', or reinstall with the cloud extra: "
            "pip install 'yt-transcribe[cloud]'. Alternatively set "
            "ffmpeg_location in ~/.yt-transcribe/config.yaml."
        )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
def download_audio(
    url: str,
    output_dir: Path,
    ffmpeg_location: str = "",
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    """Download audio from a YouTube video to a local directory.

    Args:
        url: YouTube video URL.
        output_dir: Directory to save the audio file.
        ffmpeg_location: Path to ffmpeg binary or directory. Uses PATH if empty.
        progress_callback: Optional callback receiving download progress (0.0 to 1.0).

    Returns:
        Path to the downloaded audio file.

    Raises:
        DownloadError: Network or extraction failure during download.
    """
    def _dl_hook(d: dict[str, Any]) -> None:
        """Forward yt-dlp download progress to callback."""
        if progress_callback and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                progress_callback(downloaded / total)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
        }],
        "progress_hooks": [_dl_hook],
    }
    resolved = _find_ffmpeg(ffmpeg_location)
    if resolved:
        opts["ffmpeg_location"] = resolved
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError(f"No info returned during download: {url}")
            filename = ydl.prepare_filename(info)
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(str(exc)) from exc

    # prepare_filename returns the pre-postprocessor name (e.g. .webm).
    # FFmpegExtractAudio converts to .m4a, so swap the extension.
    audio_path = Path(filename).with_suffix(".m4a")
    if audio_path.exists():
        return audio_path

    # Fallback: scan output_dir for any audio file matching the video ID
    video_id = info.get("id", "")
    for ext in (".m4a", ".mp3", ".opus", ".ogg", ".wav", ".webm"):
        candidate = output_dir / f"{video_id}{ext}"
        if candidate.exists():
            return candidate

    raise DownloadError(f"Audio file not found after download: {filename}")
