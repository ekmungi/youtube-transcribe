"""Tests for reading the video ID out of a YouTube URL."""

from __future__ import annotations

import pytest

from yt_transcribe import video_id
from yt_transcribe.video_id import extract_video_id


class TestExtractVideoId:
    """extract_video_id pulls the 11-character ID out of a video URL."""

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=42",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc&index=3",
        "https://www.youtube.com/watch?list=PLabc&v=dQw4w9WgXcQ",
    ])
    def test_returns_the_id(self, url: str):
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/playlist?list=PLabc123",
        "https://www.youtube.com/@somechannel",
        "not a url",
        "",
    ])
    def test_returns_none_when_there_is_no_video_id(self, url: str):
        assert extract_video_id(url) is None


class TestModuleSurface:
    """The module only reads IDs; routing a URL to video or playlist is the caller's choice."""

    def test_no_url_classifier_is_left_behind(self):
        # classify_youtube_url existed only to route calls inside the removed MCP server.
        assert not hasattr(video_id, "classify_youtube_url")
