"""Tests for the subprocess worker: inline transcription and source metadata."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_transcribe.models import TranscriptSource

# -- Fixtures --

def _make_video_info() -> MagicMock:
    """Create a mock VideoInfo with long duration."""
    info = MagicMock()
    info.video_id = "long123"
    info.title = "Long Video"
    info.url = "https://youtube.com/watch?v=long123"
    info.duration_seconds = 7200  # 2 hours
    return info


def _make_config() -> MagicMock:
    """Create a mock Config with captions strategy."""
    config = MagicMock()
    config.transcription_strategy.value = "captions"
    config.ffmpeg_location = ""
    return config


def _make_video_data(video_info: MagicMock) -> MagicMock:
    """Create a mock VideoData wrapping the given video_info."""
    vd = MagicMock()
    vd.video_info = video_info
    return vd


def _make_transcript(
    text: str = "Hello world",
    source: TranscriptSource = TranscriptSource.MANUAL_CAPTIONS,
    caption_language: str | None = "en",
) -> MagicMock:
    """Create a mock Transcript with text and source metadata."""
    t = MagicMock()
    t.text = text
    t.source = source
    t.caption_language = caption_language
    return t


class TestSingleVideoInline:
    """Single videos always transcribe inline and report source metadata."""

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_transcribes_inline_regardless_of_duration(
        self, mock_overrides: MagicMock,
    ):
        """Long video (2h) transcribes inline without creating an async job."""
        from yt_transcribe.worker import _handle_get_transcript

        video = _make_video_info()
        mock_overrides.return_value = _make_config()

        video_data = _make_video_data(video)
        transcript = _make_transcript()
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript,
            ) as mock_tx,
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_transcript({"video_url": video.url})

        assert "job_id" not in result
        mock_tx.assert_called_once()

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_returns_path_not_text(
        self, mock_overrides: MagicMock,
    ):
        """Fresh transcription returns path and no text by default."""
        from yt_transcribe.worker import _handle_get_transcript

        video = _make_video_info()
        mock_overrides.return_value = _make_config()

        video_data = _make_video_data(video)
        transcript = _make_transcript("Hello world")
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_transcript({"video_url": video.url})

        assert result["path"] == str(saved_path)
        assert "text" not in result
        assert result["title"] == "Long Video"

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_reports_manual_caption_source(
        self, mock_overrides: MagicMock,
    ):
        """Manual-caption transcripts report source and caption_language."""
        from yt_transcribe.worker import _handle_get_transcript

        video = _make_video_info()
        mock_overrides.return_value = _make_config()
        video_data = _make_video_data(video)
        transcript = _make_transcript(
            source=TranscriptSource.MANUAL_CAPTIONS, caption_language="en",
        )
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_transcript({"video_url": video.url})

        assert result["source"] == "manual_captions"
        assert result["caption_language"] == "en"

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_reports_assemblyai_source(
        self, mock_overrides: MagicMock,
    ):
        """Cloud transcripts report assemblyai source with no caption language."""
        from yt_transcribe.worker import _handle_get_transcript

        video = _make_video_info()
        mock_overrides.return_value = _make_config()
        video_data = _make_video_data(video)
        transcript = _make_transcript(
            source=TranscriptSource.ASSEMBLYAI, caption_language=None,
        )
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_transcript({"video_url": video.url})

        assert result["source"] == "assemblyai"
        assert result["caption_language"] is None

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_returns_word_count(
        self, mock_overrides: MagicMock,
    ):
        """Result includes word_count so Claude can gauge transcript size."""
        from yt_transcribe.worker import _handle_get_transcript

        video = _make_video_info()
        mock_overrides.return_value = _make_config()

        video_data = _make_video_data(video)
        transcript = _make_transcript("one two three four five")
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_transcript({"video_url": video.url})

        assert result["word_count"] == 5

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_returns_text_when_requested(
        self, mock_overrides: MagicMock,
    ):
        """include_text=True returns inline text alongside path."""
        from yt_transcribe.worker import _handle_get_transcript

        video = _make_video_info()
        mock_overrides.return_value = _make_config()

        video_data = _make_video_data(video)
        transcript = _make_transcript("Hello world")
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_transcript({
                "video_url": video.url,
                "include_text": True,
            })

        assert result["path"] == str(saved_path)
        assert result["text"] == "Hello world"
        assert result["word_count"] == 2


class TestPlaylistInline:
    """Playlists always process inline and report per-video source metadata."""

    @patch("yt_transcribe.worker._apply_overrides")
    def test_playlist_transcribes_inline_regardless_of_duration(
        self, mock_overrides: MagicMock,
    ):
        """Playlist with long total duration processes inline, no job creation."""
        from yt_transcribe.worker import _handle_get_playlist_transcripts

        videos = [_make_video_info() for _ in range(3)]
        mock_overrides.return_value = _make_config()

        video_data = _make_video_data(videos[0])
        transcript = _make_transcript(source=TranscriptSource.AUTO_CAPTIONS,
                                      caption_language="de")
        saved_path = Path("/vault/Transcripts/Long Video [long123].md")

        with (
            patch("yt_transcribe.download.get_playlist_info", return_value=videos),
            patch("yt_transcribe.storage.find_existing", return_value=None),
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=saved_path),
        ):
            result = _handle_get_playlist_transcripts(
                {"playlist_url": "https://youtube.com/playlist?list=PL123"}
            )

        assert "transcripts" in result
        assert "job_id" not in result
        assert len(result["transcripts"]) == 3
        # Each fresh video result carries path and source metadata, not text
        for entry in result["transcripts"]:
            assert "path" in entry
            assert "text" not in entry
            assert "word_count" in entry
            assert entry["source"] == "auto_captions"
            assert entry["caption_language"] == "de"

    @patch("yt_transcribe.worker._apply_overrides")
    def test_playlist_cached_video_reports_cache_source(
        self, mock_overrides: MagicMock, tmp_path: Path,
    ):
        """Already-saved videos are skipped, reported with source='cache', and
        carry the stored provenance metadata per the tool contract."""
        from yt_transcribe.worker import _handle_get_playlist_transcripts

        videos = [_make_video_info()]
        mock_overrides.return_value = _make_config()
        cached_path = tmp_path / "Long Video [long123].md"
        cached_path.write_text(
            "---\n"
            'title: "Long Video"\n'
            'video_id: "long123"\n'
            "source: auto_captions\n"
            'caption_language: "en"\n'
            "---\n"
            "\n# Long Video\n\nCached transcript body\n",
            encoding="utf-8",
        )

        with (
            patch("yt_transcribe.download.get_playlist_info", return_value=videos),
            patch("yt_transcribe.storage.find_existing", return_value=cached_path),
        ):
            result = _handle_get_playlist_transcripts(
                {"playlist_url": "https://youtube.com/playlist?list=PL123"}
            )

        assert len(result["transcripts"]) == 1
        entry = result["transcripts"][0]
        assert entry["source"] == "cache"
        assert entry["path"] == str(cached_path)
        assert entry["title"] == "Long Video"
        assert entry["original_source"] == "auto_captions"
        assert entry["caption_language"] == "en"
        assert entry["word_count"] > 0
        assert "text" not in entry

    @patch("yt_transcribe.worker._apply_overrides")
    def test_playlist_cached_video_honors_include_text(
        self, mock_overrides: MagicMock, tmp_path: Path,
    ):
        """include_text=True returns the stored body for cached entries, same
        as the non-cache playlist path does for fresh entries."""
        from yt_transcribe.worker import _handle_get_playlist_transcripts

        videos = [_make_video_info()]
        mock_overrides.return_value = _make_config()
        cached_path = tmp_path / "Long Video [long123].md"
        cached_path.write_text(
            "---\n"
            'title: "Long Video"\n'
            'video_id: "long123"\n'
            "source: manual_captions\n"
            'caption_language: "en"\n'
            "---\n"
            "\n# Long Video\n\nCached transcript body\n",
            encoding="utf-8",
        )

        with (
            patch("yt_transcribe.download.get_playlist_info", return_value=videos),
            patch("yt_transcribe.storage.find_existing", return_value=cached_path),
        ):
            result = _handle_get_playlist_transcripts({
                "playlist_url": "https://youtube.com/playlist?list=PL123",
                "include_text": True,
            })

        entry = result["transcripts"][0]
        assert "Cached transcript body" in entry["text"]
