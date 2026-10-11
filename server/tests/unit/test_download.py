"""Tests for YouTube download module. All yt-dlp calls are mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest

from yt_transcribe.download import (
    VideoData,
    extract_video_data,
    get_playlist_info,
)
from yt_transcribe.exceptions import (
    CaptionFetchError,
    PlaylistNotFoundError,
    VideoNotFoundError,
    VideoUnavailableError,
)

# -- Fixtures --

SAMPLE_INFO_DICT = {
    "id": "abc123",
    "title": "Test Video",
    "channel": "Test Channel",
    "webpage_url": "https://www.youtube.com/watch?v=abc123",
    "duration": 600,
}

SAMPLE_PLAYLIST_DICT = {
    "id": "PLabc",
    "title": "Test Playlist",
    "entries": [
        {
            "id": "vid1",
            "title": "Video 1",
            "channel": "Ch",
            "webpage_url": "https://www.youtube.com/watch?v=vid1",
            "duration": 300,
        },
        {
            "id": "vid2",
            "title": "Video 2",
            "channel": "Ch",
            "webpage_url": "https://www.youtube.com/watch?v=vid2",
            "duration": 450,
        },
    ],
}

# json3 body matching the real timedtext response shape: events with utf8 segs
SAMPLE_JSON3_BODY = json.dumps({
    "events": [
        {"tStartMs": 0, "dDurationMs": 5000, "segs": [{"utf8": "Hello world"}]},
        {"tStartMs": 5000, "dDurationMs": 3000, "segs": [{"utf8": "Second line"}]},
    ]
})


def _make_ydl(mock_ydl_cls: MagicMock, info: dict, body: str | None = None) -> MagicMock:
    """Wire a mock YoutubeDL context manager returning info and optional caption body.

    Args:
        mock_ydl_cls: The patched YoutubeDL class mock.
        info: Dict returned by extract_info.
        body: Optional json3 body returned by ydl.urlopen(...).read().

    Returns:
        The inner mock ydl instance.
    """
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = info
    if body is not None:
        response = MagicMock()
        response.read.return_value = body.encode("utf-8")
        mock_ydl.urlopen.return_value = response
    return mock_ydl


# -- get_playlist_info tests --

class TestGetPlaylistInfo:
    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_returns_tuple_of_video_info(self, mock_ydl_cls: MagicMock):
        """get_playlist_info returns a tuple of VideoInfo objects."""
        _make_ydl(mock_ydl_cls, SAMPLE_PLAYLIST_DICT)

        result = get_playlist_info("https://www.youtube.com/playlist?list=PLabc")

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0].video_id == "vid1"
        assert result[0].playlist_title == "Test Playlist"
        assert result[1].video_id == "vid2"

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_raises_playlist_not_found_on_empty(self, mock_ydl_cls: MagicMock):
        """get_playlist_info raises PlaylistNotFoundError for empty playlists."""
        _make_ydl(mock_ydl_cls, {"id": "PL1", "title": "Empty", "entries": []})

        with pytest.raises(PlaylistNotFoundError):
            get_playlist_info("https://www.youtube.com/playlist?list=PL1")

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_raises_playlist_not_found_on_error(self, mock_ydl_cls: MagicMock):
        """get_playlist_info raises PlaylistNotFoundError on extraction failure."""
        mock_ydl = _make_ydl(mock_ydl_cls, SAMPLE_PLAYLIST_DICT)
        mock_ydl.extract_info.side_effect = Exception("Playlist not found")

        with pytest.raises(PlaylistNotFoundError):
            get_playlist_info("https://www.youtube.com/playlist?list=bad")


# -- extract_video_data tests (single-call optimization) --

# Mirrors the real yt-dlp info dict: subtitle entries have ext/url/name, NEVER data
SAMPLE_INFO_WITH_SUBS = {
    **SAMPLE_INFO_DICT,
    "language": "en",
    "subtitles": {
        "en": [
            {
                "ext": "json3",
                "url": "https://www.youtube.com/api/timedtext?fmt=json3&lang=en",
                "name": "English",
            },
            {
                "ext": "vtt",
                "url": "https://www.youtube.com/api/timedtext?fmt=vtt&lang=en",
                "name": "English",
            },
        ]
    },
    "automatic_captions": {},
}


class TestExtractVideoData:
    """Tests for the single-call extract_video_data function."""

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_regression_extracts_captions_from_url_only_entries(self, mock_ydl_cls: MagicMock):
        """Regression: yt-dlp never populates a data key for YouTube subtitles.

        Captions must be fetched from the entry url via the active ydl opener.
        This is the test that would have caught the dead captions tier.
        """
        mock_ydl = _make_ydl(mock_ydl_cls, SAMPLE_INFO_WITH_SUBS, body=SAMPLE_JSON3_BODY)

        result = extract_video_data("https://www.youtube.com/watch?v=abc123")

        assert result.captions is not None
        assert len(result.captions) == 2
        assert result.captions[0].text == "Hello world"
        mock_ydl.urlopen.assert_called_once_with(
            "https://www.youtube.com/api/timedtext?fmt=json3&lang=en"
        )

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_returns_video_data_with_all_fields(self, mock_ydl_cls: MagicMock):
        """extract_video_data returns VideoData with metadata and captions only."""
        _make_ydl(mock_ydl_cls, SAMPLE_INFO_WITH_SUBS, body=SAMPLE_JSON3_BODY)

        result = extract_video_data("https://www.youtube.com/watch?v=abc123")

        assert isinstance(result, VideoData)
        assert result.video_info.video_id == "abc123"
        assert result.captions is not None
        assert len(result.captions) == 2
        assert not hasattr(result, "audio_url")  # audio is never downloaded

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_reports_caption_provenance(self, mock_ydl_cls: MagicMock):
        """extract_video_data records which kind and language produced the captions."""
        _make_ydl(mock_ydl_cls, SAMPLE_INFO_WITH_SUBS, body=SAMPLE_JSON3_BODY)

        result = extract_video_data("https://www.youtube.com/watch?v=abc123")

        assert result.caption_kind == "manual"
        assert result.caption_language == "en"

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_returns_none_captions_when_no_subs(self, mock_ydl_cls: MagicMock):
        """extract_video_data returns None captions when video has no subtitles."""
        info_no_subs = {
            **SAMPLE_INFO_DICT,
            "subtitles": {},
            "automatic_captions": {},
        }
        _make_ydl(mock_ydl_cls, info_no_subs)

        result = extract_video_data("https://www.youtube.com/watch?v=abc123")

        assert result.captions is None
        assert result.caption_kind is None
        assert result.caption_language is None
        # Truly caption-less, not a failed fetch
        assert result.captions_fetch_failed is False

    @patch("yt_transcribe.download.fetch_captions")
    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_caption_fetch_failure_sets_flag_without_failing_extraction(
        self, mock_ydl_cls: MagicMock, mock_fetch: MagicMock,
    ):
        """A caption fetch failure is recorded on VideoData instead of raising:
        the metadata remains usable and transcription reports a retryable error."""
        _make_ydl(mock_ydl_cls, SAMPLE_INFO_WITH_SUBS)
        mock_fetch.side_effect = CaptionFetchError("rate limited")

        result = extract_video_data("https://www.youtube.com/watch?v=abc123")

        assert result.captions is None
        assert result.captions_fetch_failed is True
        assert result.video_info.video_id == "abc123"

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_raises_video_not_found(self, mock_ydl_cls: MagicMock):
        """extract_video_data raises VideoNotFoundError on missing video."""
        mock_ydl = _make_ydl(mock_ydl_cls, SAMPLE_INFO_DICT)
        mock_ydl.extract_info.side_effect = Exception("Video not found")

        with pytest.raises(VideoNotFoundError):
            extract_video_data("https://www.youtube.com/watch?v=missing")

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_raises_video_unavailable_for_private(self, mock_ydl_cls: MagicMock):
        """extract_video_data raises VideoUnavailableError for private videos."""
        mock_ydl = _make_ydl(mock_ydl_cls, SAMPLE_INFO_DICT)
        mock_ydl.extract_info.side_effect = Exception("Private video")

        with pytest.raises(VideoUnavailableError):
            extract_video_data("https://www.youtube.com/watch?v=private")

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_single_extract_info_call(self, mock_ydl_cls: MagicMock):
        """extract_video_data makes exactly one extract_info call."""
        mock_ydl = _make_ydl(mock_ydl_cls, SAMPLE_INFO_WITH_SUBS, body=SAMPLE_JSON3_BODY)

        extract_video_data("https://www.youtube.com/watch?v=abc123")

        mock_ydl.extract_info.assert_called_once()
