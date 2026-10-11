"""Tests for immutable data models."""

import pytest

from yt_transcribe import models
from yt_transcribe.models import (
    Config,
    Segment,
    Transcript,
    TranscriptSource,
    VideoInfo,
)


class TestRemovedCloudTypes:
    def test_no_transcription_strategy(self):
        """Captions are the only source, so there is nothing to choose between."""
        assert not hasattr(models, "TranscriptionStrategy")

    def test_no_assemblyai_source(self):
        assert not hasattr(TranscriptSource, "ASSEMBLYAI")


class TestTranscriptSource:
    def test_values(self):
        """Source provenance covers the cache and both caption kinds."""
        assert TranscriptSource.CACHE == "cache"
        assert TranscriptSource.MANUAL_CAPTIONS == "manual_captions"
        assert TranscriptSource.AUTO_CAPTIONS == "auto_captions"

    def test_exactly_three_members(self):
        assert len(TranscriptSource) == 3


class TestConfig:
    def test_creation(self):
        config = Config(
            obsidian_vault_path="/vault",
            transcript_folder="Transcripts",
        )
        assert config.obsidian_vault_path == "/vault"
        assert config.transcript_folder == "Transcripts"

    def test_has_only_the_vault_location_fields(self):
        """The strategy and ffmpeg settings went away with the cloud strategy."""
        assert set(Config.__dataclass_fields__) == {"obsidian_vault_path", "transcript_folder"}

    def test_frozen(self):
        config = Config(
            obsidian_vault_path="/vault",
            transcript_folder="Transcripts",
        )
        with pytest.raises(AttributeError):
            config.obsidian_vault_path = "/other"  # type: ignore[misc]


class TestVideoInfo:
    def test_creation(self):
        video = VideoInfo(
            video_id="abc123",
            title="Test Video",
            channel="Test Channel",
            url="https://youtube.com/watch?v=abc123",
            duration_seconds=600,
            playlist_title=None,
        )
        assert video.video_id == "abc123"
        assert video.playlist_title is None

    def test_with_playlist(self):
        video = VideoInfo(
            video_id="abc123",
            title="Lecture 1",
            channel="MIT",
            url="https://youtube.com/watch?v=abc123",
            duration_seconds=3600,
            playlist_title="MIT 6.034",
        )
        assert video.playlist_title == "MIT 6.034"


class TestSegment:
    def test_creation(self):
        seg = Segment(start_seconds=0.0, end_seconds=5.5, text="Hello world")
        assert seg.start_seconds == 0.0
        assert seg.text == "Hello world"


class TestTranscript:
    def _video(self) -> VideoInfo:
        """Build a minimal VideoInfo for transcript tests."""
        return VideoInfo(
            video_id="abc", title="T", channel="C",
            url="http://y.com", duration_seconds=60, playlist_title=None,
        )

    def test_creation_with_source_metadata(self):
        """Transcript carries source provenance and caption language."""
        segments = (Segment(0.0, 5.0, "Hello"),)
        transcript = Transcript(
            video=self._video(),
            text="Hello",
            segments=segments,
            source=TranscriptSource.MANUAL_CAPTIONS,
            caption_language="en",
        )
        assert transcript.text == "Hello"
        assert transcript.source == TranscriptSource.MANUAL_CAPTIONS
        assert transcript.caption_language == "en"

    def test_caption_language_defaults_to_none(self):
        """The language is optional: it is None when the track's language is unknown."""
        transcript = Transcript(
            video=self._video(),
            text="Hi",
            segments=(Segment(0.0, 1.0, "Hi"),),
            source=TranscriptSource.AUTO_CAPTIONS,
        )
        assert transcript.caption_language is None

    def test_segments_is_tuple(self):
        transcript = Transcript(
            video=self._video(),
            text="Hi",
            segments=(Segment(0.0, 1.0, "Hi"),),
            source=TranscriptSource.AUTO_CAPTIONS,
        )
        assert isinstance(transcript.segments, tuple)
