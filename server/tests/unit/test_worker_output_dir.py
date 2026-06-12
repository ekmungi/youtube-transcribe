"""Tests for the worker's output_dir override: writing transcripts to a
caller-specified directory instead of the configured Obsidian vault."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_transcribe.models import Config, TranscriptionStrategy, TranscriptSource


def _base_config() -> Config:
    """A concrete Config with a non-empty vault and folder to override."""
    return Config(
        obsidian_vault_path="/configured/vault",
        transcript_folder="Sources/YouTube Transcripts",
        transcription_strategy=TranscriptionStrategy.CAPTIONS,
        ffmpeg_location="",
    )


class TestApplyOverridesOutputDir:
    """_apply_overrides maps output_dir onto the vault root with no subfolder."""

    def test_output_dir_becomes_vault_root_with_empty_folder(self):
        """A given output_dir is written directly (vault=output_dir, folder='')."""
        from yt_transcribe.worker import _apply_overrides

        with patch("yt_transcribe.config.load_config", return_value=_base_config()):
            cfg = _apply_overrides(strategy=None, output_dir="/tmp/out")

        assert cfg.obsidian_vault_path == "/tmp/out"
        assert cfg.transcript_folder == ""

    def test_omitting_output_dir_keeps_configured_location(self):
        """No output_dir leaves the configured vault and folder untouched."""
        from yt_transcribe.worker import _apply_overrides

        with patch("yt_transcribe.config.load_config", return_value=_base_config()):
            cfg = _apply_overrides(strategy=None, output_dir=None)

        assert cfg.obsidian_vault_path == "/configured/vault"
        assert cfg.transcript_folder == "Sources/YouTube Transcripts"

    def test_strategy_and_output_dir_apply_together(self):
        """strategy and output_dir overrides are independent and both apply."""
        from yt_transcribe.worker import _apply_overrides

        with patch("yt_transcribe.config.load_config", return_value=_base_config()):
            cfg = _apply_overrides(strategy="cloud", output_dir="/tmp/out")

        assert cfg.transcription_strategy == TranscriptionStrategy.CLOUD
        assert cfg.obsidian_vault_path == "/tmp/out"
        assert cfg.transcript_folder == ""


class TestHandlersThreadOutputDir:
    """The worker handlers pass output_dir from the request to _apply_overrides."""

    @patch("yt_transcribe.worker._apply_overrides")
    def test_single_video_threads_output_dir(self, mock_overrides: MagicMock):
        """_handle_get_transcript forwards request output_dir to overrides."""
        from yt_transcribe.worker import _handle_get_transcript

        config = MagicMock()
        config.transcription_strategy.value = "captions"
        mock_overrides.return_value = config

        video = MagicMock()
        video.title = "V"
        video.duration_seconds = 10
        video_data = MagicMock()
        video_data.video_info = video
        transcript = MagicMock()
        transcript.text = "a b"
        transcript.source = TranscriptSource.MANUAL_CAPTIONS
        transcript.caption_language = "en"

        with (
            patch("yt_transcribe.download.extract_video_data", return_value=video_data),
            patch("yt_transcribe.transcribe.transcribe_video_fast", return_value=transcript),
            patch("yt_transcribe.storage.save_transcript", return_value=Path("/tmp/out/V.md")),
        ):
            _handle_get_transcript({
                "video_url": "https://youtu.be/abc",
                "output_dir": "/tmp/out",
            })

        mock_overrides.assert_called_once_with(None, "/tmp/out")

    @patch("yt_transcribe.worker._apply_overrides")
    def test_playlist_threads_output_dir(self, mock_overrides: MagicMock):
        """_handle_get_playlist_transcripts forwards output_dir to overrides."""
        from yt_transcribe.worker import _handle_get_playlist_transcripts

        config = MagicMock()
        config.transcription_strategy.value = "captions"
        mock_overrides.return_value = config

        with (
            patch("yt_transcribe.download.get_playlist_info", return_value=[]),
        ):
            _handle_get_playlist_transcripts({
                "playlist_url": "https://youtube.com/playlist?list=PL1",
                "output_dir": "/tmp/out",
            })

        mock_overrides.assert_called_once_with(None, "/tmp/out")
