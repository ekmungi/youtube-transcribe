"""Tests for YouTube download module. All yt-dlp calls are mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_transcribe.download import (
    VideoData,
    _extract_audio_url,
    _find_ffmpeg,
    download_audio,
    ensure_ffmpeg,
    extract_video_data,
    get_playlist_info,
)
from yt_transcribe.exceptions import (
    CaptionFetchError,
    DownloadError,
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


# -- download_audio tests --

class TestDownloadAudio:
    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_returns_path_to_audio_file(self, mock_ydl_cls: MagicMock, tmp_path: Path):
        """download_audio returns a Path to the downloaded audio."""
        mock_ydl = _make_ydl(mock_ydl_cls, {**SAMPLE_INFO_DICT})

        # Simulate yt-dlp writing a file
        audio_file = tmp_path / "audio.m4a"
        audio_file.write_bytes(b"fake audio data")
        mock_ydl.prepare_filename.return_value = str(audio_file)

        result = download_audio("https://www.youtube.com/watch?v=abc123", tmp_path)

        assert isinstance(result, Path)

    @patch("yt_transcribe.download.yt_dlp.YoutubeDL")
    def test_raises_download_error_on_failure(self, mock_ydl_cls: MagicMock, tmp_path: Path):
        """download_audio raises DownloadError on network failure."""
        mock_ydl = _make_ydl(mock_ydl_cls, SAMPLE_INFO_DICT)
        mock_ydl.extract_info.side_effect = Exception("Network error")

        with pytest.raises(DownloadError):
            download_audio("https://www.youtube.com/watch?v=abc123", tmp_path)


# -- extract_video_data tests (single-call optimization) --

# Mirrors the real yt-dlp info dict: subtitle entries have ext/url/name, NEVER data
SAMPLE_INFO_WITH_SUBS = {
    **SAMPLE_INFO_DICT,
    "language": "en",
    "formats": [
        {
            "format_id": "251",
            "acodec": "opus",
            "vcodec": "none",
            "abr": 128,
            "url": "https://audio.example.com/251",
        },
        {
            "format_id": "140",
            "acodec": "mp4a",
            "vcodec": "none",
            "abr": 96,
            "url": "https://audio.example.com/140",
        },
    ],
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
        """extract_video_data returns VideoData with metadata, captions, and audio URL."""
        _make_ydl(mock_ydl_cls, SAMPLE_INFO_WITH_SUBS, body=SAMPLE_JSON3_BODY)

        result = extract_video_data("https://www.youtube.com/watch?v=abc123")

        assert isinstance(result, VideoData)
        assert result.video_info.video_id == "abc123"
        assert result.captions is not None
        assert len(result.captions) == 2
        assert result.audio_url == "https://audio.example.com/251"  # highest abr

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
            "formats": [],
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
        metadata and audio URL remain usable (e.g. for the cloud strategy)."""
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


class TestExtractAudioUrl:
    """Tests for _extract_audio_url helper."""

    def test_picks_highest_bitrate_audio(self):
        """Selects audio format with highest abr."""
        info = {
            "formats": [
                {"acodec": "opus", "vcodec": "none", "abr": 64, "url": "https://low.com"},
                {"acodec": "opus", "vcodec": "none", "abr": 128, "url": "https://high.com"},
            ]
        }
        assert _extract_audio_url(info) == "https://high.com"

    def test_returns_none_for_no_formats(self):
        """Returns None when no formats available."""
        assert _extract_audio_url({"formats": []}) is None

    def test_fallback_to_format_with_video(self):
        """Falls back to video+audio format when no audio-only available."""
        info = {
            "formats": [
                {"acodec": "mp4a", "vcodec": "h264", "abr": 128, "url": "https://mixed.com"},
            ]
        }
        assert _extract_audio_url(info) == "https://mixed.com"


class TestFindFfmpeg:
    """Tests for ffmpeg resolution (_find_ffmpeg) and the ensure_ffmpeg guard."""

    def test_explicit_existing_path_wins(self, tmp_path: Path):
        """A configured path that exists is returned verbatim."""
        binary = tmp_path / "ffmpeg.exe"
        binary.write_text("x")
        assert _find_ffmpeg(str(binary)) == str(binary)

    def test_empty_string_when_on_path(self):
        """Returns empty string (let yt-dlp find it) when ffmpeg is on PATH."""
        with patch("yt_transcribe.download.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert _find_ffmpeg("") == ""

    def test_bundled_fallback_when_extra_installed(self):
        """Falls back to the imageio-ffmpeg static binary when present."""
        with (
            patch("yt_transcribe.download.shutil.which", return_value=None),
            patch("pathlib.Path.exists", return_value=False),
            patch(
                "yt_transcribe.download._imageio_ffmpeg_path",
                return_value="/bundled/ffmpeg",
            ),
        ):
            assert _find_ffmpeg("") == "/bundled/ffmpeg"

    def test_returns_none_when_nothing_found(self):
        """Returns None when ffmpeg cannot be located anywhere."""
        with (
            patch("yt_transcribe.download.shutil.which", return_value=None),
            patch("pathlib.Path.exists", return_value=False),
            patch("yt_transcribe.download._imageio_ffmpeg_path", return_value=None),
        ):
            assert _find_ffmpeg("") is None

    def test_ensure_ffmpeg_raises_actionable_error_when_missing(self):
        """ensure_ffmpeg raises DownloadError naming the install options."""
        with patch("yt_transcribe.download._find_ffmpeg", return_value=None):
            with pytest.raises(DownloadError, match="ffmpeg is required"):
                ensure_ffmpeg("")

    def test_ensure_ffmpeg_passes_when_available(self):
        """ensure_ffmpeg is a no-op when ffmpeg resolves."""
        with patch("yt_transcribe.download._find_ffmpeg", return_value=""):
            ensure_ffmpeg("")  # must not raise
