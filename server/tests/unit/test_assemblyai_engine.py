"""Tests for AssemblyAI cloud transcription engine. assemblyai SDK is fully mocked."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_transcribe.assemblyai_engine import transcribe, transcribe_url
from yt_transcribe.exceptions import TranscriptionError
from yt_transcribe.models import Segment

# -- Mock helpers --

def _make_mock_sentence(start_ms: int, end_ms: int, text: str) -> MagicMock:
    """Create a mock AssemblyAI sentence with timing in milliseconds."""
    sentence = MagicMock()
    sentence.start = start_ms
    sentence.end = end_ms
    sentence.text = text
    return sentence


class TestTranscribe:
    """Tests for file-based transcription."""

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_returns_tuple_of_segments(self, mock_aai: MagicMock, tmp_path: Path):
        """transcribe returns an immutable tuple of Segment dataclasses."""
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_transcript = MagicMock()
        mock_transcript.status = "completed"
        mock_transcript.error = None
        mock_transcript.get_sentences.return_value = [
            _make_mock_sentence(0, 5000, "Hello world"),
            _make_mock_sentence(5000, 10000, "Second sentence"),
        ]

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        result = transcribe(audio_file, "test-api-key")

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], Segment)
        assert result[0].start_seconds == 0.0
        assert result[0].end_seconds == 5.0
        assert result[0].text == "Hello world"

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_sets_api_key(self, mock_aai: MagicMock, tmp_path: Path):
        """transcribe sets the AssemblyAI API key before calling the SDK."""
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_transcript = MagicMock()
        mock_transcript.status = "completed"
        mock_transcript.error = None
        mock_transcript.get_sentences.return_value = []
        mock_transcript.text = None
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        transcribe(audio_file, "my-secret-key")

        mock_aai.settings.api_key = "my-secret-key"

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_raises_transcription_error_on_failure(self, mock_aai: MagicMock, tmp_path: Path):
        """transcribe raises TranscriptionError when AssemblyAI reports an error."""
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_transcript = MagicMock()
        mock_transcript.status = "error"
        mock_transcript.error = "Audio too short"
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        with pytest.raises(TranscriptionError, match="Audio too short"):
            transcribe(audio_file, "test-api-key")

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_raises_transcription_error_on_sdk_exception(
        self, mock_aai: MagicMock, tmp_path: Path
    ):
        """transcribe raises TranscriptionError when the SDK throws an exception."""
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.side_effect = RuntimeError("Network error")
        mock_aai.Transcriber.return_value = mock_transcriber

        with pytest.raises(TranscriptionError, match="Network error"):
            transcribe(audio_file, "test-api-key")

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_empty_sentences_returns_empty_tuple(self, mock_aai: MagicMock, tmp_path: Path):
        """transcribe returns empty tuple when no sentences or text are returned."""
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_transcript = MagicMock()
        mock_transcript.status = "completed"
        mock_transcript.error = None
        mock_transcript.get_sentences.return_value = None
        mock_transcript.text = None
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        result = transcribe(audio_file, "test-api-key")

        assert result == ()

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_fallback_to_full_text(self, mock_aai: MagicMock, tmp_path: Path):
        """transcribe falls back to full text when no sentences available."""
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_transcript = MagicMock()
        mock_transcript.status = "completed"
        mock_transcript.error = None
        mock_transcript.get_sentences.return_value = None
        mock_transcript.text = "Full transcript text here"
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        result = transcribe(audio_file, "test-api-key")

        assert len(result) == 1
        assert result[0].text == "Full transcript text here"

    def test_raises_on_missing_file(self, tmp_path: Path):
        """transcribe raises TranscriptionError for non-existent audio file."""
        with pytest.raises(TranscriptionError, match="not found"):
            transcribe(tmp_path / "missing.m4a", "key")


class TestTranscribeUrl:
    """Tests for URL-based transcription (no download/upload)."""

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_returns_segments_from_url(self, mock_aai: MagicMock):
        """transcribe_url returns segments from a direct audio URL."""
        mock_transcript = MagicMock()
        mock_transcript.status = "completed"
        mock_transcript.error = None
        mock_transcript.get_sentences.return_value = [
            _make_mock_sentence(0, 3000, "From URL"),
        ]

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        result = transcribe_url("https://audio.youtube.com/stream/abc", "test-key")

        assert len(result) == 1
        assert result[0].text == "From URL"
        # Verify the URL was passed directly (not a file path)
        call_args = mock_transcriber.transcribe.call_args
        assert call_args[0][0] == "https://audio.youtube.com/stream/abc"

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_raises_on_api_error(self, mock_aai: MagicMock):
        """transcribe_url raises TranscriptionError on AssemblyAI error."""
        mock_transcript = MagicMock()
        mock_transcript.status = "error"
        mock_transcript.error = "Invalid audio URL"
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        with pytest.raises(TranscriptionError, match="Invalid audio URL"):
            transcribe_url("https://bad-url.com/audio", "test-key")

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_raises_on_sdk_exception(self, mock_aai: MagicMock):
        """transcribe_url raises TranscriptionError on SDK failure."""
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.side_effect = RuntimeError("Connection timeout")
        mock_aai.Transcriber.return_value = mock_transcriber

        with pytest.raises(TranscriptionError, match="Connection timeout"):
            transcribe_url("https://audio.example.com/stream", "test-key")

    @patch("yt_transcribe.assemblyai_engine.aai")
    def test_sets_api_key(self, mock_aai: MagicMock):
        """transcribe_url sets API key on aai.settings."""
        mock_transcript = MagicMock()
        mock_transcript.status = "completed"
        mock_transcript.error = None
        mock_transcript.get_sentences.return_value = []
        mock_transcript.text = None
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = mock_transcript
        mock_aai.Transcriber.return_value = mock_transcriber

        transcribe_url("https://audio.example.com/stream", "secret-key-123")

        mock_aai.settings.api_key = "secret-key-123"
