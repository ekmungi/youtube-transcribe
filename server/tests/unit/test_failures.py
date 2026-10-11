"""Tests for the playlist failure record shared by the CLI and the worker."""

from __future__ import annotations

from yt_transcribe.exceptions import CaptionFetchError, NoCaptionsError
from yt_transcribe.failures import failure_entry


class TestFailureEntry:
    """failure_entry describes a failed video for JSON results."""

    def test_carries_identity_message_and_error_type(self) -> None:
        entry = failure_entry("abc", "A video", NoCaptionsError("none"))
        assert entry == {
            "video_id": "abc",
            "title": "A video",
            "error": "none",
            "error_type": "NoCaptionsError",
        }

    def test_error_type_follows_the_exception_class(self) -> None:
        entry = failure_entry("abc", "A video", CaptionFetchError("rate limited"))
        assert entry["error_type"] == "CaptionFetchError"
