"""Tests for classifying a YouTube URL as a single video or a playlist."""

from __future__ import annotations

import pytest

from yt_transcribe.url_classify import classify_youtube_url


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
