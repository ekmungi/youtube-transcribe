"""Tests for transcription from YouTube's caption tracks."""

import pytest

from yt_transcribe import transcribe
from yt_transcribe.download import VideoData
from yt_transcribe.exceptions import CaptionFetchError, NoCaptionsError
from yt_transcribe.models import Segment, Transcript, TranscriptSource, VideoInfo
from yt_transcribe.transcribe import transcribe_video_fast

# -- Fixtures --

SAMPLE_VIDEO = VideoInfo(
    video_id="abc123",
    title="Test Video",
    channel="Test Channel",
    url="https://www.youtube.com/watch?v=abc123",
    duration_seconds=600,
    playlist_title=None,
)

SAMPLE_SEGMENTS = (
    Segment(start_seconds=0.0, end_seconds=5.0, text="Hello world"),
    Segment(start_seconds=5.0, end_seconds=10.0, text="Second line"),
)

MANUAL_CAPTIONS_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=SAMPLE_SEGMENTS,
    raw_info={"id": "abc123"},
    caption_kind="manual",
    caption_language="en",
)

AUTO_CAPTIONS_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=SAMPLE_SEGMENTS,
    raw_info={"id": "abc123"},
    caption_kind="auto",
    caption_language="de",
)

NO_CAPTIONS_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=None,
    raw_info={"id": "abc123"},
    caption_kind=None,
    caption_language=None,
)

# Caption tracks existed but every fetch attempt failed (rate limit / network)
CAPTIONS_FETCH_FAILED_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=None,
    raw_info={"id": "abc123"},
    caption_kind=None,
    caption_language=None,
    captions_fetch_failed=True,
)


class TestCaptionsTranscription:
    """The transcript is built from the pre-fetched caption track."""

    def test_manual_captions_produce_transcript(self):
        """Manual captions yield a transcript with manual_captions source."""
        result = transcribe_video_fast(MANUAL_CAPTIONS_DATA)

        assert isinstance(result, Transcript)
        assert result.video == SAMPLE_VIDEO
        assert result.segments == SAMPLE_SEGMENTS
        assert "Hello world" in result.text
        assert result.source == TranscriptSource.MANUAL_CAPTIONS
        assert result.caption_language == "en"

    def test_auto_captions_produce_transcript(self):
        """Auto-generated captions yield auto_captions source with language."""
        result = transcribe_video_fast(AUTO_CAPTIONS_DATA)

        assert result.source == TranscriptSource.AUTO_CAPTIONS
        assert result.caption_language == "de"

    def test_unknown_caption_kind_is_reported_as_auto(self):
        """Anything not explicitly manual counts as auto-generated."""
        data = VideoData(
            video_info=SAMPLE_VIDEO, captions=SAMPLE_SEGMENTS,
            raw_info={"id": "abc123"}, caption_kind=None, caption_language="en",
        )
        assert transcribe_video_fast(data).source == TranscriptSource.AUTO_CAPTIONS

    def test_phase_callback_is_told_captions_are_being_checked(self):
        phases: list[str] = []
        transcribe_video_fast(MANUAL_CAPTIONS_DATA, phases.append)
        assert phases == ["checking captions..."]


class TestFailureModes:
    """A video with no captions and a failed caption fetch are different problems."""

    def test_no_captions_raises_a_final_error(self):
        """Missing captions raise NoCaptionsError that says the video cannot be
        transcribed, and offers no alternative path."""
        with pytest.raises(NoCaptionsError) as exc_info:
            transcribe_video_fast(NO_CAPTIONS_DATA)

        message = str(exc_info.value)
        assert "Test Video" in message
        assert "cannot be transcribed" in message
        assert "original" in message  # foreign-language note
        for removed in ("cloud", "AssemblyAI", "API key", "strategy"):
            assert removed not in message

    def test_fetch_failure_raises_retryable_error_not_no_captions(self):
        """Captions that exist but could not be fetched raise CaptionFetchError
        telling the user to retry later -- never NoCaptionsError, which says the
        video can never be transcribed."""
        with pytest.raises(CaptionFetchError) as exc_info:
            transcribe_video_fast(CAPTIONS_FETCH_FAILED_DATA)

        message = str(exc_info.value)
        assert "Test Video" in message
        assert "rate-limiting" in message
        assert "retry" in message
        for removed in ("cloud", "AssemblyAI", "strategy"):
            assert removed not in message

    def test_no_captions_and_fetch_failure_messages_differ(self):
        """The two failure modes produce distinct, mode-appropriate messages."""
        with pytest.raises(NoCaptionsError) as no_captions_info:
            transcribe_video_fast(NO_CAPTIONS_DATA)
        with pytest.raises(CaptionFetchError) as fetch_failed_info:
            transcribe_video_fast(CAPTIONS_FETCH_FAILED_DATA)

        no_captions_msg = str(no_captions_info.value)
        fetch_failed_msg = str(fetch_failed_info.value)
        assert no_captions_msg != fetch_failed_msg
        assert "cannot be transcribed" in no_captions_msg
        assert "rate-limiting" in fetch_failed_msg


class TestNoSpeechToText:
    def test_module_has_no_audio_or_cloud_machinery(self):
        """Captions are the only source: nothing downloads audio or calls an STT service."""
        for name in ("assemblyai_engine", "tempfile", "shutil", "get_assemblyai_api_key"):
            assert not hasattr(transcribe, name)


class TestTextFormatting:
    """Formatted text includes [MM:SS] timestamps at 5-minute boundaries."""

    def test_text_includes_timestamps_at_five_minute_intervals(self):
        segments = (
            Segment(0.0, 60.0, "Intro text here."),
            Segment(60.0, 300.0, "More content before five minutes."),
            Segment(300.0, 360.0, "Content after five minutes."),
            Segment(360.0, 600.0, "Even more content."),
            Segment(600.0, 660.0, "At ten minutes."),
        )
        video_data = VideoData(
            video_info=SAMPLE_VIDEO,
            captions=segments,
            raw_info={"id": "abc123"},
            caption_kind="manual",
            caption_language="en",
        )

        result = transcribe_video_fast(video_data)

        assert "[05:00]" in result.text
        assert "[10:00]" in result.text
