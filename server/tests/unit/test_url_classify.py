"""Tests for classifying a YouTube URL as a single video or a playlist."""

from __future__ import annotations

import pytest

from yt_transcribe.url_classify import classify_youtube_url, extract_video_id


class TestSingleVideo:
    """URLs that point at one specific video classify as 'video'."""

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
    ])
    def test_plain_video_urls(self, url: str):
        assert classify_youtube_url(url) == "video"

    def test_watch_url_with_list_is_still_a_video(self):
        """A watch URL carrying &list= points at one video; the playlist is
        only context, so it classifies as 'video', not 'playlist'."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc123"
        assert classify_youtube_url(url) == "video"


class TestPlaylist:
    """URLs that point at a playlist (no specific video) classify as 'playlist'."""

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/playlist?list=PLabc123",
        "https://www.youtube.com/watch?list=PLabc123",
    ])
    def test_playlist_urls(self, url: str):
        assert classify_youtube_url(url) == "playlist"


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
