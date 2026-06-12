"""Captions-first transcription orchestrator with explicit cloud opt-in.

Two strategies: CAPTIONS (default) uses the caption track pre-fetched in
VideoData; CLOUD sends audio to AssemblyAI (URL-first, then file upload).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from yt_transcribe import assemblyai_engine, download
from yt_transcribe.config import get_assemblyai_api_key
from yt_transcribe.download import VideoData
from yt_transcribe.exceptions import (
    CaptionFetchError,
    NoCaptionsError,
    TranscriptionError,
)
from yt_transcribe.formatting import format_transcript_body
from yt_transcribe.models import (
    Config,
    Segment,
    Transcript,
    TranscriptionStrategy,
    TranscriptSource,
    VideoInfo,
)

logger = logging.getLogger(__name__)


def transcribe_video_fast(
    video_data: VideoData,
    config: Config,
    phase_callback: Callable[[str], None] | None = None,
) -> Transcript:
    """Transcribe a video using pre-fetched VideoData.

    CAPTIONS strategy uses the caption track already fetched into VideoData
    and never touches any speech-to-text engine. CLOUD strategy is an
    explicit opt-in that sends audio to AssemblyAI even when captions exist.

    Args:
        video_data: Pre-fetched video metadata, captions, and audio URL.
        config: Application configuration with the strategy setting.
        phase_callback: Optional callback receiving status text.

    Returns:
        Immutable Transcript with formatted text, segments, and provenance.

    Raises:
        NoCaptionsError: CAPTIONS strategy and the video has no captions.
        CaptionFetchError: CAPTIONS strategy; captions exist but their fetch
            failed (rate limit / network). Retryable.
        TranscriptionError: CLOUD strategy without an API key, or AssemblyAI
            failure.
    """
    _report = phase_callback or (lambda _: None)

    if config.transcription_strategy == TranscriptionStrategy.CLOUD:
        return _transcribe_cloud(video_data, config, _report)
    return _transcribe_captions(video_data, _report)


def _transcribe_captions(
    video_data: VideoData,
    report: Callable[[str], None],
) -> Transcript:
    """Build a Transcript from the pre-fetched caption track.

    Args:
        video_data: Pre-fetched video data carrying captions and their kind.
        report: Phase status callback.

    Returns:
        Transcript sourced from manual or auto captions.

    Raises:
        NoCaptionsError: If the video truly has no caption track.
        CaptionFetchError: If caption tracks exist but could not be fetched
            (YouTube rate limit or network failure). Retryable.
    """
    video_info = video_data.video_info
    report("checking captions...")

    if video_data.captions is None:
        # Distinguish a transient fetch failure (retry later, free) from a
        # truly caption-less video (cloud opt-in is the only alternative).
        if video_data.captions_fetch_failed:
            raise CaptionFetchError(
                f"Captions exist for '{video_info.title}' but could not be "
                "fetched: YouTube is rate-limiting or unreachable right now. "
                "This is usually temporary -- retry in a few minutes. There "
                "is no need to switch to the paid cloud strategy for this "
                "video."
            )
        raise NoCaptionsError(
            f"No captions are available for '{video_info.title}'. YouTube "
            "auto-generates captions only for some videos, typically in the "
            "video's original language. To transcribe the audio with "
            "speech-to-text instead, retry with strategy='cloud', which sends "
            "the audio to AssemblyAI and requires an AssemblyAI API key."
        )

    # Provenance: trust the explicit kind from caption extraction; anything
    # that is not explicitly manual is reported as auto-generated.
    source = (
        TranscriptSource.MANUAL_CAPTIONS
        if video_data.caption_kind == "manual"
        else TranscriptSource.AUTO_CAPTIONS
    )
    return Transcript(
        video=video_info,
        text=format_transcript_body(video_data.captions),
        segments=video_data.captions,
        source=source,
        caption_language=video_data.caption_language,
    )


def _transcribe_cloud(
    video_data: VideoData,
    config: Config,
    report: Callable[[str], None],
) -> Transcript:
    """Transcribe audio with AssemblyAI: direct URL first, then file upload.

    Args:
        video_data: Pre-fetched video data with an optional direct audio URL.
        config: Application configuration (ffmpeg location for downloads).
        report: Phase status callback.

    Returns:
        Transcript sourced from AssemblyAI (caption_language is None).

    Raises:
        TranscriptionError: If no API key is configured or AssemblyAI fails.
    """
    video_info = video_data.video_info
    api_key = get_assemblyai_api_key()
    if not api_key:
        raise TranscriptionError(
            "Cloud strategy requires an AssemblyAI API key. Set the "
            "ASSEMBLYAI_API_KEY environment variable or store it in the OS keyring."
        )

    segments: tuple[Segment, ...] | None = None
    if video_data.audio_url:
        try:
            report("transcribing (cloud, direct URL)...")
            segments = assemblyai_engine.transcribe_url(video_data.audio_url, api_key)
        except TranscriptionError:
            # YouTube CDN URLs are often signed/IP-locked/time-limited and
            # unreadable from AssemblyAI's side. Fall back to file upload.
            logger.warning(
                "AssemblyAI URL transcription failed for %s, falling back to file upload",
                video_info.url,
            )

    if segments is None:
        segments = _cloud_file_upload(video_info, config, report, api_key)

    return Transcript(
        video=video_info,
        text=format_transcript_body(segments),
        segments=segments,
        source=TranscriptSource.ASSEMBLYAI,
        caption_language=None,
    )


def _cloud_file_upload(
    video_info: VideoInfo,
    config: Config,
    report: Callable[[str], None],
    api_key: str,
) -> tuple[Segment, ...]:
    """Download audio to a temp dir and transcribe via AssemblyAI upload.

    The temp directory is removed afterwards, on success or failure.

    Args:
        video_info: Video metadata (URL used for the download).
        config: Application configuration (ffmpeg location).
        report: Phase status callback.
        api_key: AssemblyAI API key.

    Returns:
        Tuple of Segment dataclasses from AssemblyAI.

    Raises:
        TranscriptionError: If download or AssemblyAI transcription fails.
    """
    # Audio extraction needs ffmpeg; fail early with actionable guidance
    # rather than a cryptic yt-dlp post-processing error mid-download.
    download.ensure_ffmpeg(config.ffmpeg_location)

    temp_dir = tempfile.mkdtemp(prefix="yt-transcribe-")
    try:
        report("downloading audio...")
        audio_path = download.download_audio(
            video_info.url, Path(temp_dir), config.ffmpeg_location,
        )
        report("transcribing (cloud, file upload)...")
        return assemblyai_engine.transcribe(audio_path, api_key)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
