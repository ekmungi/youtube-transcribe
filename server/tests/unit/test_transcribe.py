"""Tests for the captions-first transcription orchestrator. All engines mocked."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_transcribe.download import VideoData
from yt_transcribe.exceptions import (
    CaptionFetchError,
    DownloadError,
    NoCaptionsError,
    TranscriptionError,
)
from yt_transcribe.models import (
    Config,
    Segment,
    Transcript,
    TranscriptionStrategy,
    TranscriptSource,
    VideoInfo,
)
from yt_transcribe.transcribe import transcribe_video_fast

# -- Fixtures --

SAMPLE_VIDEO = VideoInfo(
    video_id="abc123",
    title="Test Video",
    channel="Test Channel",
    url="https://www.youtube.com/watch?v=abc123",
    duration_seconds=600,
    playlist_title=None,
)

SAMPLE_SEGMENTS = (
    Segment(start_seconds=0.0, end_seconds=5.0, text="Hello world"),
    Segment(start_seconds=5.0, end_seconds=10.0, text="Second line"),
)

CAPTIONS_CONFIG = Config(
    obsidian_vault_path="/vault",
    transcript_folder="Transcripts",
    transcription_strategy=TranscriptionStrategy.CAPTIONS,)

CLOUD_CONFIG = Config(
    obsidian_vault_path="/vault",
    transcript_folder="Transcripts",
    transcription_strategy=TranscriptionStrategy.CLOUD,)

MANUAL_CAPTIONS_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=SAMPLE_SEGMENTS,
    audio_url="https://audio.youtube.com/stream/abc123",
    raw_info={"id": "abc123"},
    caption_kind="manual",
    caption_language="en",
)

AUTO_CAPTIONS_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=SAMPLE_SEGMENTS,
    audio_url="https://audio.youtube.com/stream/abc123",
    raw_info={"id": "abc123"},
    caption_kind="auto",
    caption_language="de",
)

NO_CAPTIONS_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=None,
    audio_url="https://audio.youtube.com/stream/abc123",
    raw_info={"id": "abc123"},
    caption_kind=None,
    caption_language=None,
)

NO_CAPTIONS_NO_URL_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=None,
    audio_url=None,
    raw_info={"id": "abc123"},
    caption_kind=None,
    caption_language=None,
)

# Caption tracks existed but every fetch attempt failed (rate limit / network)
CAPTIONS_FETCH_FAILED_DATA = VideoData(
    video_info=SAMPLE_VIDEO,
    captions=None,
    audio_url="https://audio.youtube.com/stream/abc123",
    raw_info={"id": "abc123"},
    caption_kind=None,
    caption_language=None,
    captions_fetch_failed=True,
)


class TestCaptionsStrategy:
    """CAPTIONS is the default: pre-fetched captions only, no network engines."""

    def test_manual_captions_produce_transcript(self):
        """Manual captions yield a transcript with manual_captions source."""
        result = transcribe_video_fast(MANUAL_CAPTIONS_DATA, CAPTIONS_CONFIG)

        assert isinstance(result, Transcript)
        assert result.video == SAMPLE_VIDEO
        assert result.segments == SAMPLE_SEGMENTS
        assert "Hello world" in result.text
        assert result.source == TranscriptSource.MANUAL_CAPTIONS
        assert result.caption_language == "en"

    def test_auto_captions_produce_transcript(self):
        """Auto-generated captions yield auto_captions source with language."""
        result = transcribe_video_fast(AUTO_CAPTIONS_DATA, CAPTIONS_CONFIG)

        assert result.source == TranscriptSource.AUTO_CAPTIONS
        assert result.caption_language == "de"

    def test_no_captions_raises_actionable_error(self):
        """Missing captions raise NoCaptionsError pointing at the cloud opt-in."""
        with pytest.raises(NoCaptionsError) as exc_info:
            transcribe_video_fast(NO_CAPTIONS_DATA, CAPTIONS_CONFIG)

        message = str(exc_info.value)
        assert "Test Video" in message
        assert "strategy='cloud'" in message
        assert "AssemblyAI" in message
        assert "API key" in message
        assert "original" in message  # foreign-language note

    def test_fetch_failure_raises_retryable_error_not_no_captions(self):
        """Captions that exist but could not be fetched raise CaptionFetchError
        telling the user to retry later -- never NoCaptionsError, which would
        wrongly recommend the paid cloud strategy."""
        with pytest.raises(CaptionFetchError) as exc_info:
            transcribe_video_fast(CAPTIONS_FETCH_FAILED_DATA, CAPTIONS_CONFIG)

        message = str(exc_info.value)
        assert "Test Video" in message
        assert "rate-limiting" in message
        assert "retry" in message
        # The fetch-failure message must NOT push the user to the paid path
        assert "strategy='cloud'" not in message

    def test_no_captions_and_fetch_failure_messages_differ(self):
        """The two failure modes produce distinct, mode-appropriate messages."""
        with pytest.raises(NoCaptionsError) as no_captions_info:
            transcribe_video_fast(NO_CAPTIONS_DATA, CAPTIONS_CONFIG)
        with pytest.raises(CaptionFetchError) as fetch_failed_info:
            transcribe_video_fast(CAPTIONS_FETCH_FAILED_DATA, CAPTIONS_CONFIG)

        no_captions_msg = str(no_captions_info.value)
        fetch_failed_msg = str(fetch_failed_info.value)
        assert no_captions_msg != fetch_failed_msg
        assert "strategy='cloud'" in no_captions_msg
        assert "rate-limiting" in fetch_failed_msg

    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_cloud_never_triggered_implicitly(
        self, mock_get_key: MagicMock, mock_download: MagicMock, mock_aai: MagicMock,
    ):
        """Even with an API key configured, CAPTIONS never falls back to cloud."""
        with pytest.raises(NoCaptionsError):
            transcribe_video_fast(NO_CAPTIONS_DATA, CAPTIONS_CONFIG)

        mock_aai.transcribe_url.assert_not_called()
        mock_aai.transcribe.assert_not_called()
        mock_download.download_audio.assert_not_called()


class TestCloudStrategy:
    """CLOUD is an explicit opt-in: AssemblyAI directly, URL-first then upload."""

    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_uses_url_transcription(self, mock_get_key: MagicMock, mock_aai: MagicMock):
        """Cloud strategy passes the audio URL straight to AssemblyAI."""
        mock_aai.transcribe_url.return_value = SAMPLE_SEGMENTS

        result = transcribe_video_fast(NO_CAPTIONS_DATA, CLOUD_CONFIG)

        assert isinstance(result, Transcript)
        assert result.source == TranscriptSource.ASSEMBLYAI
        assert result.caption_language is None
        mock_aai.transcribe_url.assert_called_once_with(
            "https://audio.youtube.com/stream/abc123", "test-key"
        )

    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_cloud_ignores_available_captions(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
    ):
        """Explicit cloud opt-in transcribes audio even when captions exist."""
        mock_aai.transcribe_url.return_value = SAMPLE_SEGMENTS

        result = transcribe_video_fast(MANUAL_CAPTIONS_DATA, CLOUD_CONFIG)

        assert result.source == TranscriptSource.ASSEMBLYAI
        mock_aai.transcribe_url.assert_called_once()

    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_cloud_unaffected_by_caption_fetch_failure(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
    ):
        """Explicit cloud opt-in never consults captions, so a caption fetch
        failure does not block it."""
        mock_aai.transcribe_url.return_value = SAMPLE_SEGMENTS

        result = transcribe_video_fast(CAPTIONS_FETCH_FAILED_DATA, CLOUD_CONFIG)

        assert result.source == TranscriptSource.ASSEMBLYAI

    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value=None)
    def test_raises_when_no_api_key(self, mock_get_key: MagicMock):
        """Cloud strategy fails fast when no AssemblyAI API key is configured."""
        with pytest.raises(TranscriptionError, match="API key"):
            transcribe_video_fast(NO_CAPTIONS_DATA, CLOUD_CONFIG)

    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_falls_back_to_file_upload_when_url_fails(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
        mock_download: MagicMock, tmp_path: Path,
    ):
        """Signed/IP-locked CDN URLs fail; cloud falls back to file upload."""
        mock_aai.transcribe_url.side_effect = TranscriptionError("Download error")
        mock_download.download_audio.return_value = tmp_path / "audio.m4a"
        mock_aai.transcribe.return_value = SAMPLE_SEGMENTS

        result = transcribe_video_fast(NO_CAPTIONS_DATA, CLOUD_CONFIG)

        assert result.source == TranscriptSource.ASSEMBLYAI
        mock_aai.transcribe.assert_called_once()

    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_uses_file_upload_when_no_audio_url(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
        mock_download: MagicMock, tmp_path: Path,
    ):
        """Without an extractable audio URL, cloud goes straight to file upload."""
        mock_download.download_audio.return_value = tmp_path / "audio.m4a"
        mock_aai.transcribe.return_value = SAMPLE_SEGMENTS

        result = transcribe_video_fast(NO_CAPTIONS_NO_URL_DATA, CLOUD_CONFIG)

        assert result.source == TranscriptSource.ASSEMBLYAI
        mock_aai.transcribe_url.assert_not_called()
        mock_aai.transcribe.assert_called_once()

    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_file_upload_preflights_ffmpeg(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
        mock_download: MagicMock, tmp_path: Path,
    ):
        """The file-upload path checks ffmpeg before attempting a download."""
        mock_download.download_audio.return_value = tmp_path / "audio.m4a"
        mock_aai.transcribe.return_value = SAMPLE_SEGMENTS

        transcribe_video_fast(NO_CAPTIONS_NO_URL_DATA, CLOUD_CONFIG)

        mock_download.ensure_ffmpeg.assert_called_once()

    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_missing_ffmpeg_raises_before_download(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
        mock_download: MagicMock,
    ):
        """A missing ffmpeg surfaces the actionable error and skips the download."""
        mock_download.ensure_ffmpeg.side_effect = DownloadError("ffmpeg is required")

        with pytest.raises(DownloadError, match="ffmpeg is required"):
            transcribe_video_fast(NO_CAPTIONS_NO_URL_DATA, CLOUD_CONFIG)

        mock_download.download_audio.assert_not_called()


class TestTextFormatting:
    """Formatted text includes [MM:SS] timestamps at 5-minute boundaries."""

    def test_text_includes_timestamps_at_five_minute_intervals(self):
        segments = (
            Segment(0.0, 60.0, "Intro text here."),
            Segment(60.0, 300.0, "More content before five minutes."),
            Segment(300.0, 360.0, "Content after five minutes."),
            Segment(360.0, 600.0, "Even more content."),
            Segment(600.0, 660.0, "At ten minutes."),
        )
        video_data = VideoData(
            video_info=SAMPLE_VIDEO,
            captions=segments,
            audio_url=None,
            raw_info={"id": "abc123"},
            caption_kind="manual",
            caption_language="en",
        )

        result = transcribe_video_fast(video_data, CAPTIONS_CONFIG)

        assert "[05:00]" in result.text
        assert "[10:00]" in result.text


class TestCloudTempDirCleanup:
    """File-upload fallback cleans up its temp directory."""

    @patch("yt_transcribe.transcribe.shutil")
    @patch("yt_transcribe.transcribe.tempfile")
    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_temp_dir_cleaned_up_on_success(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
        mock_download: MagicMock, mock_tempfile: MagicMock, mock_shutil: MagicMock,
    ):
        mock_temp_dir = "/tmp/yt-transcribe-abc"
        mock_tempfile.mkdtemp.return_value = mock_temp_dir
        mock_download.download_audio.return_value = Path(mock_temp_dir) / "audio.m4a"
        mock_aai.transcribe.return_value = SAMPLE_SEGMENTS

        result = transcribe_video_fast(NO_CAPTIONS_NO_URL_DATA, CLOUD_CONFIG)

        assert isinstance(result, Transcript)
        mock_shutil.rmtree.assert_called_once_with(mock_temp_dir, ignore_errors=True)

    @patch("yt_transcribe.transcribe.shutil")
    @patch("yt_transcribe.transcribe.tempfile")
    @patch("yt_transcribe.transcribe.download")
    @patch("yt_transcribe.transcribe.assemblyai_engine")
    @patch("yt_transcribe.transcribe.get_assemblyai_api_key", return_value="test-key")
    def test_temp_dir_cleaned_up_on_failure(
        self, mock_get_key: MagicMock, mock_aai: MagicMock,
        mock_download: MagicMock, mock_tempfile: MagicMock, mock_shutil: MagicMock,
    ):
        mock_temp_dir = "/tmp/yt-transcribe-abc"
        mock_tempfile.mkdtemp.return_value = mock_temp_dir
        mock_download.download_audio.return_value = Path(mock_temp_dir) / "audio.m4a"
        mock_aai.transcribe.side_effect = TranscriptionError("Failed")

        with pytest.raises(TranscriptionError):
            transcribe_video_fast(NO_CAPTIONS_NO_URL_DATA, CLOUD_CONFIG)

        mock_shutil.rmtree.assert_called_once_with(mock_temp_dir, ignore_errors=True)
