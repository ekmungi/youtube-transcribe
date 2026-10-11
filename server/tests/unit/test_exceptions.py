"""Tests for custom exception hierarchy."""

import pytest

from yt_transcribe import exceptions
from yt_transcribe.exceptions import (
    CaptionFetchError,
    NoCaptionsError,
    PlaylistNotFoundError,
    VideoNotFoundError,
    VideoUnavailableError,
    YtTranscribeError,
)


class TestExceptionHierarchy:
    def test_base_error(self):
        with pytest.raises(YtTranscribeError):
            raise YtTranscribeError("base error")

    def test_video_not_found_is_yt_error(self):
        assert issubclass(VideoNotFoundError, YtTranscribeError)

    def test_video_unavailable_is_yt_error(self):
        assert issubclass(VideoUnavailableError, YtTranscribeError)

    def test_playlist_not_found_is_yt_error(self):
        assert issubclass(PlaylistNotFoundError, YtTranscribeError)

    def test_no_captions_is_yt_error(self):
        assert issubclass(NoCaptionsError, YtTranscribeError)

    def test_caption_fetch_error_is_yt_error(self):
        assert issubclass(CaptionFetchError, YtTranscribeError)

    def test_caption_fetch_error_is_not_no_captions(self):
        """Fetch failure (retryable) and caption-less (permanent) are distinct
        types so callers can give mode-appropriate advice."""
        assert not issubclass(CaptionFetchError, NoCaptionsError)
        assert not issubclass(NoCaptionsError, CaptionFetchError)

    def test_audio_and_speech_to_text_errors_are_gone(self):
        """They belonged to the audio download and AssemblyAI paths."""
        assert not hasattr(exceptions, "DownloadError")
        assert not hasattr(exceptions, "TranscriptionError")

    def test_error_message_preserved(self):
        err = VideoNotFoundError("video xyz not found")
        assert str(err) == "video xyz not found"
