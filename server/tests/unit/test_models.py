"""Tests for immutable data models."""

import pytest

from yt_transcribe.models import (
    Config,
    Segment,
    Transcript,
    TranscriptionStrategy,
    TranscriptSource,
    VideoInfo,
)


class TestTranscriptionStrategy:
    def test_values(self):
        """Only two strategies exist: captions (default) and cloud (opt-in)."""
        assert TranscriptionStrategy.CAPTIONS == "captions"
        assert TranscriptionStrategy.CLOUD == "cloud"

    def test_exactly_two_members(self):
        """The local STT tier and the auto cascade were removed in Phase B."""
        assert len(TranscriptionStrategy) == 2

    def test_legacy_values_rejected(self):
        """Legacy strategy names are not enum members (migration happens in config)."""
        with pytest.raises(ValueError):
            TranscriptionStrategy("auto")
        with pytest.raises(ValueError):
            TranscriptionStrategy("local")


class TestTranscriptSource:
    def test_values(self):
        """Source provenance covers cache, both caption kinds, and AssemblyAI."""
        assert TranscriptSource.CACHE == "cache"
        assert TranscriptSource.MANUAL_CAPTIONS == "manual_captions"
        assert TranscriptSource.AUTO_CAPTIONS == "auto_captions"
        assert TranscriptSource.ASSEMBLYAI == "assemblyai"


class TestConfig:
    def test_creation(self):
        config = Config(
            obsidian_vault_path="/vault",
            transcript_folder="Transcripts",
            transcription_strategy=TranscriptionStrategy.CAPTIONS,        )
        assert config.obsidian_vault_path == "/vault"
        assert config.transcription_strategy == TranscriptionStrategy.CAPTIONS

    def test_frozen(self):
        config = Config(
            obsidian_vault_path="/vault",
            transcript_folder="Transcripts",
            transcription_strategy=TranscriptionStrategy.CAPTIONS,        )
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
        """AssemblyAI transcripts have no caption language."""
        transcript = Transcript(
            video=self._video(),
            text="Hi",
            segments=(Segment(0.0, 1.0, "Hi"),),
            source=TranscriptSource.ASSEMBLYAI,
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
