"""Tests for custom exception hierarchy."""

import pytest

from yt_transcribe.exceptions import (
    CaptionFetchError,
    DownloadError,
    NoCaptionsError,
    PlaylistNotFoundError,
    TranscriptionError,
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

    def test_download_error_is_yt_error(self):
        assert issubclass(DownloadError, YtTranscribeError)

    def test_no_captions_is_yt_error(self):
        assert issubclass(NoCaptionsError, YtTranscribeError)

    def test_caption_fetch_error_is_yt_error(self):
        assert issubclass(CaptionFetchError, YtTranscribeError)

    def test_caption_fetch_error_is_not_no_captions(self):
        """Fetch failure (retryable) and caption-less (permanent) are distinct
        types so callers can give mode-appropriate advice."""
        assert not issubclass(CaptionFetchError, NoCaptionsError)
        assert not issubclass(NoCaptionsError, CaptionFetchError)

    def test_transcription_error_is_yt_error(self):
        assert issubclass(TranscriptionError, YtTranscribeError)

    def test_error_message_preserved(self):
        err = VideoNotFoundError("video xyz not found")
        assert str(err) == "video xyz not found"
