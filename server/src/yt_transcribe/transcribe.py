"""Transcription from YouTube's own caption tracks.

The caption track is fetched together with the video metadata (see
download.extract_video_data); this module turns it into a Transcript with
provenance. There is no speech-to-text: a video without captions has no
transcript.
"""

from __future__ import annotations

from collections.abc import Callable

from yt_transcribe.download import VideoData
from yt_transcribe.exceptions import CaptionFetchError, NoCaptionsError
from yt_transcribe.formatting import format_transcript_body
from yt_transcribe.models import Transcript, TranscriptSource


def transcribe_video_fast(
    video_data: VideoData,
    phase_callback: Callable[[str], None] | None = None,
) -> Transcript:
    """Build a Transcript from the caption track pre-fetched in VideoData.

    Args:
        video_data: Pre-fetched video metadata and caption track.
        phase_callback: Optional callback receiving status text.

    Returns:
        Immutable Transcript with formatted text, segments, and provenance
        (manual or auto-generated captions, plus the caption language).

    Raises:
        NoCaptionsError: The video has no caption track.
        CaptionFetchError: Captions exist but their fetch failed (YouTube rate
            limit or network failure). Retryable.
    """
    report = phase_callback or (lambda _: None)
    video_info = video_data.video_info
    report("checking captions...")

    if video_data.captions is None:
        # Distinguish a transient fetch failure (retry later) from a video that
        # truly has no captions (nothing to retry).
        if video_data.captions_fetch_failed:
            raise CaptionFetchError(
                f"Captions exist for '{video_info.title}' but could not be "
                "fetched: YouTube is rate-limiting or unreachable right now. "
                "This is usually temporary -- retry in a few minutes."
            )
        raise NoCaptionsError(
            f"No captions are available for '{video_info.title}'. YouTube "
            "generates captions only for some videos, typically in the "
            "video's original language, so this video cannot be transcribed."
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
