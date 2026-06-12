"""Integration tests for CLI commands using click.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from yt_transcribe.models import (
    Config,
    Segment,
    Transcript,
    TranscriptionStrategy,
    TranscriptSource,
    VideoInfo,
)

# -- Fixtures ----------------------------------------------------------------

@pytest.fixture()
def runner() -> CliRunner:
    """Return a click test runner."""
    return CliRunner()


@pytest.fixture()
def sample_config(tmp_path: Path) -> Config:
    """Return a Config pointing at a temp vault."""
    return Config(
        obsidian_vault_path=str(tmp_path / "vault"),
        transcript_folder="Transcripts",
        transcription_strategy=TranscriptionStrategy.CAPTIONS,    )


@pytest.fixture()
def sample_video() -> VideoInfo:
    """Return a minimal VideoInfo."""
    return VideoInfo(
        video_id="abc123abcde",
        title="Test Video",
        channel="Test Channel",
        url="https://youtube.com/watch?v=abc123abcde",
        duration_seconds=120,
        playlist_title=None,
    )


@pytest.fixture()
def sample_transcript(sample_video: VideoInfo) -> Transcript:
    """Return a Transcript for the sample video."""
    return Transcript(
        video=sample_video,
        text="Hello world transcript",
        segments=(Segment(0.0, 5.0, "Hello world transcript"),),
        source=TranscriptSource.MANUAL_CAPTIONS,
        caption_language="en",
    )


# -- video command -----------------------------------------------------------

class TestVideoCommand:
    """Tests for `yt-transcribe video <url>`."""

    def test_video_success(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """Successful transcription prints title and saves."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video,
            captions=None,
            audio_url="https://audio.example.com/abc123",
            raw_info={"id": "abc123abcde"},
        )

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch("yt_transcribe.cli.storage.save_transcript"),
        ):
            result = runner.invoke(cli, ["video", "https://youtube.com/watch?v=abc123abcde"])

        assert result.exit_code == 0
        assert "Test Video" in result.output

    def test_video_cached(
        self, runner: CliRunner, sample_config: Config, sample_video: VideoInfo,
    ) -> None:
        """Already-cached transcript skips transcription."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video,
            captions=None,
            audio_url="https://audio.example.com/abc123",
            raw_info={"id": "abc123abcde"},
        )

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=Path("/v/cached.md")),
        ):
            result = runner.invoke(cli, ["video", "https://youtube.com/watch?v=abc123abcde"])

        assert result.exit_code == 0
        assert "already exists" in result.output.lower() or "cached" in result.output.lower()

    def test_video_missing_url(self, runner: CliRunner) -> None:
        """Missing URL argument shows error."""
        from yt_transcribe.cli import cli

        result = runner.invoke(cli, ["video"])
        assert result.exit_code != 0


class TestVideoJsonOutput:
    """Tests for `yt-transcribe video <url> --json` (the plugin contract)."""

    def test_json_success_emits_single_line(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """Fresh transcription emits one JSON line with path and provenance."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            audio_url=None, raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch(
                "yt_transcribe.cli.storage.save_transcript",
                return_value=Path("/vault/Test Video [abc123abcde].md"),
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--json"],
            )

        assert result.exit_code == 0
        lines = [ln for ln in result.output.splitlines() if ln.strip()]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["cached"] is False
        assert payload["source"] == "manual_captions"
        assert payload["caption_language"] == "en"
        assert payload["path"].endswith("abc123abcde].md")
        assert payload["title"] == "Test Video"

    def test_json_cached_reads_stored_provenance(
        self, runner: CliRunner, sample_config: Config, sample_video: VideoInfo,
    ) -> None:
        """Cache hit emits cached=true with the stored provenance."""
        import json
        from unittest.mock import MagicMock

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            audio_url=None, raw_info={"id": "abc123abcde"},
        )
        stored = MagicMock(source="auto_captions", caption_language="en")
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.storage.find_existing",
                return_value=Path("/vault/cached.md"),
            ),
            patch(
                "yt_transcribe.cli.storage.read_stored_transcript",
                return_value=stored,
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload["cached"] is True
        assert payload["source"] == "cache"
        assert payload["original_source"] == "auto_captions"

    def test_json_error_emits_error_object_and_exit_1(
        self, runner: CliRunner, sample_config: Config, sample_video: VideoInfo,
    ) -> None:
        """A known error is reported as JSON with error_type and exit code 1."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData
        from yt_transcribe.exceptions import NoCaptionsError

        video_data = VideoData(
            video_info=sample_video, captions=None,
            audio_url=None, raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                side_effect=NoCaptionsError("no captions here"),
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--json"],
            )

        assert result.exit_code == 1
        payload = json.loads(result.output.strip())
        assert payload["error_type"] == "NoCaptionsError"
        assert "no captions here" in payload["error"]

    def test_strategy_override_passed_to_transcription(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--strategy cloud overrides the configured strategy for this run."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData
        from yt_transcribe.models import TranscriptionStrategy

        video_data = VideoData(
            video_info=sample_video, captions=None,
            audio_url=None, raw_info={"id": "abc123abcde"},
        )
        captured: dict[str, Config] = {}

        def _capture(vd: VideoData, cfg: Config) -> Transcript:
            captured["cfg"] = cfg
            return sample_transcript

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                side_effect=_capture,
            ),
            patch(
                "yt_transcribe.cli.storage.save_transcript",
                return_value=Path("/vault/x.md"),
            ),
        ):
            result = runner.invoke(
                cli,
                ["video", "https://youtube.com/watch?v=abc123abcde",
                 "--strategy", "cloud", "--json"],
            )

        assert result.exit_code == 0
        assert captured["cfg"].transcription_strategy == TranscriptionStrategy.CLOUD

    def test_vault_and_folder_overrides_passed_to_storage(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--vault and --folder override where the transcript is written."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            audio_url=None, raw_info={"id": "abc123abcde"},
        )
        captured: dict[str, Config] = {}

        def _capture_save(cfg: Config, _result: Transcript) -> Path:
            captured["cfg"] = cfg
            return Path("/v/x.md")

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch(
                "yt_transcribe.cli.storage.save_transcript", side_effect=_capture_save,
            ),
        ):
            result = runner.invoke(
                cli,
                ["video", "https://youtube.com/watch?v=abc123abcde",
                 "--vault", "D:/MyVault", "--folder", "Media/YouTube", "--json"],
            )

        assert result.exit_code == 0
        assert captured["cfg"].obsidian_vault_path == "D:/MyVault"
        assert captured["cfg"].transcript_folder == "Media/YouTube"


class TestSetupFfmpegCommand:
    """Tests for `yt-transcribe setup-ffmpeg`."""

    def test_json_success_reports_path(self, runner: CliRunner) -> None:
        """--json emits the installed path and configured flag."""
        import json

        from yt_transcribe.cli import cli

        with patch(
            "yt_transcribe.ffmpeg_setup.setup_ffmpeg",
            return_value=Path("/home/u/.yt-transcribe/bin"),
        ):
            result = runner.invoke(cli, ["setup-ffmpeg", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload["configured"] is True
        assert payload["path"].endswith("bin")

    def test_json_error_reports_error_type(self, runner: CliRunner) -> None:
        """A download failure is reported as JSON with exit code 1."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.exceptions import DownloadError

        with patch(
            "yt_transcribe.ffmpeg_setup.setup_ffmpeg",
            side_effect=DownloadError("network down"),
        ):
            result = runner.invoke(cli, ["setup-ffmpeg", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output.strip())
        assert payload["error_type"] == "DownloadError"
        assert "network down" in payload["error"]


# -- playlist command --------------------------------------------------------

class TestPlaylistCommand:
    """Tests for `yt-transcribe playlist <url>`."""

    def test_playlist_success(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """Playlist processes each video."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video,
            captions=None,
            audio_url="https://audio.example.com/abc123",
            raw_info={"id": "abc123abcde"},
        )

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.download.get_playlist_info", return_value=(sample_video,)),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch("yt_transcribe.cli.storage.save_transcript"),
        ):
            result = runner.invoke(cli, ["playlist", "https://youtube.com/playlist?list=PL1"])

        assert result.exit_code == 0

    def test_playlist_missing_url(self, runner: CliRunner) -> None:
        """Missing URL argument shows error."""
        from yt_transcribe.cli import cli

        result = runner.invoke(cli, ["playlist"])
        assert result.exit_code != 0


# -- list command ------------------------------------------------------------

class TestListCommand:
    """Tests for `yt-transcribe list`."""

    def test_list_shows_transcripts(self, runner: CliRunner, sample_config: Config) -> None:
        """List command shows saved transcript titles."""
        from yt_transcribe.cli import cli
        from yt_transcribe.search import TranscriptEntry

        entries = [
            TranscriptEntry(Path("/v/a.md"), "Video A", "Ch1", "a1"),
        ]
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.search.list_transcripts", return_value=entries),
        ):
            result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "Video A" in result.output

    def test_list_with_folder(self, runner: CliRunner, sample_config: Config) -> None:
        """Folder flag is forwarded."""
        from yt_transcribe.cli import cli

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.search.list_transcripts", return_value=[]
            ) as mock_list,
        ):
            result = runner.invoke(cli, ["list", "--folder", "MIT"])

        assert result.exit_code == 0
        mock_list.assert_called_once_with(sample_config, folder="MIT")


# -- search command ----------------------------------------------------------

class TestSearchCommand:
    """Tests for `yt-transcribe search <query>`."""

    def test_search_shows_matches(self, runner: CliRunner, sample_config: Config) -> None:
        """Search shows matching snippets."""
        from yt_transcribe.cli import cli
        from yt_transcribe.search import SearchResult

        matches = [
            SearchResult(Path("/v/ml.md"), "ML Intro", "Prof", "...gradient..."),
        ]
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.search.search_transcripts", return_value=matches),
        ):
            result = runner.invoke(cli, ["search", "gradient"])

        assert result.exit_code == 0
        assert "gradient" in result.output

    def test_search_no_results(self, runner: CliRunner, sample_config: Config) -> None:
        """No matches shows a message."""
        from yt_transcribe.cli import cli

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.search.search_transcripts", return_value=[]),
        ):
            result = runner.invoke(cli, ["search", "zzzznonexistent"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output


# -- config command ----------------------------------------------------------

class TestConfigCommand:
    """Tests for `yt-transcribe config` and `config set`."""

    def test_config_shows_values(self, runner: CliRunner, sample_config: Config) -> None:
        """Config command prints current settings."""
        from yt_transcribe.cli import cli

        with patch("yt_transcribe.cli.load_config", return_value=sample_config):
            result = runner.invoke(cli, ["config"])

        assert result.exit_code == 0
        assert "captions" in result.output.lower()

    def test_config_set_updates_value(self, runner: CliRunner, sample_config: Config) -> None:
        """Config set writes new value."""
        from yt_transcribe.cli import cli

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.config_mod.save_config") as mock_save,
        ):
            result = runner.invoke(cli, ["config", "set", "transcription_strategy", "cloud"])

        assert result.exit_code == 0
        mock_save.assert_called_once()

    def test_config_set_invalid_key(self, runner: CliRunner, sample_config: Config) -> None:
        """Unknown config key shows error."""
        from yt_transcribe.cli import cli

        with patch("yt_transcribe.cli.load_config", return_value=sample_config):
            result = runner.invoke(cli, ["config", "set", "bogus_key", "value"])

        assert result.exit_code != 0 or "unknown" in result.output.lower()

    def test_config_set_rejects_legacy_strategy(
        self, runner: CliRunner, sample_config: Config,
    ) -> None:
        """Legacy strategy names (auto, local) are no longer accepted."""
        from yt_transcribe.cli import cli

        with patch("yt_transcribe.cli.load_config", return_value=sample_config):
            result = runner.invoke(cli, ["config", "set", "transcription_strategy", "local"])

        assert result.exit_code != 0
        assert "invalid" in result.output.lower()
