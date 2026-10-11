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
    )


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
        from unittest.mock import MagicMock

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video,
            captions=None,
            raw_info={"id": "abc123abcde"},
        )

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch("yt_transcribe.cli.storage.find_existing", return_value=Path("/v/cached.md")),
            patch(
                "yt_transcribe.cli.storage.read_stored_transcript",
                return_value=MagicMock(title="Test Video"),
            ),
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
            raw_info={"id": "abc123abcde"},
        )
        stored = MagicMock(title="Test Video", source="auto_captions", caption_language="en")
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
            raw_info={"id": "abc123abcde"},
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

    def test_vault_and_folder_overrides_passed_to_storage(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--vault and --folder override where the transcript is written."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
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


class TestVideoNoSave:
    """Tests for `yt-transcribe video <url> --no-save` (transcript text to stdout, no file)."""

    def test_no_save_emits_text_and_writes_no_file(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--no-save transcribes and emits the transcript TEXT as JSON, saving nothing."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch("yt_transcribe.cli.storage.save_transcript") as mock_save,
            patch("yt_transcribe.cli.storage.find_existing") as mock_find,
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--no-save"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload["text"] == "Hello world transcript"
        assert payload["title"] == "Test Video"
        assert payload["video_id"] == "abc123abcde"
        assert payload["source"] == "manual_captions"
        assert payload["caption_language"] == "en"
        assert payload["saved"] is False
        mock_save.assert_not_called()  # no vault file written
        mock_find.assert_not_called()  # no cache lookup -- always fresh

    def test_no_save_error_emits_error_json_and_exit_1(
        self, runner: CliRunner, sample_config: Config, sample_video: VideoInfo,
    ) -> None:
        """A known transcription error under --no-save is emitted as error JSON, exit 1."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData
        from yt_transcribe.exceptions import NoCaptionsError

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                side_effect=NoCaptionsError("no captions here"),
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--no-save"],
            )

        assert result.exit_code == 1
        payload = json.loads(result.output.strip())
        assert payload["error_type"] == "NoCaptionsError"
        assert "no captions here" in payload["error"]


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


class TestPlaylistJsonOutput:
    """Tests for `yt-transcribe playlist <url> --json` (the plugin contract)."""

    def test_json_emits_transcripts_list(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--json emits one line with a count and a per-video transcripts list."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.download.get_playlist_info",
                return_value=(sample_video, sample_video),
            ),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
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
                cli, ["playlist", "https://youtube.com/playlist?list=PL1", "--json"],
            )

        assert result.exit_code == 0
        lines = [ln for ln in result.output.splitlines() if ln.strip()]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["count"] == 2
        assert len(payload["transcripts"]) == 2
        first = payload["transcripts"][0]
        assert first["title"] == "Test Video"
        assert first["video_id"] == "abc123abcde"
        assert first["source"] == "manual_captions"
        assert first["cached"] is False
        assert first["path"].endswith("abc123abcde].md")

    def test_json_vault_and_folder_overrides(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--vault and --folder override where each transcript is written."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        captured: dict[str, Config] = {}

        def _capture_save(cfg: Config, _result: Transcript) -> Path:
            captured["cfg"] = cfg
            return Path("/v/x.md")

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.download.get_playlist_info",
                return_value=(sample_video,),
            ),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch("yt_transcribe.cli.storage.save_transcript", side_effect=_capture_save),
        ):
            result = runner.invoke(
                cli,
                ["playlist", "https://youtube.com/playlist?list=PL1",
                 "--vault", "D:/MyVault", "--folder", "Media/YT", "--json"],
            )

        assert result.exit_code == 0
        assert captured["cfg"].obsidian_vault_path == "D:/MyVault"
        assert captured["cfg"].transcript_folder == "Media/YT"

    def test_json_error_emits_error_object_and_exit_1(
        self, runner: CliRunner, sample_config: Config,
    ) -> None:
        """A playlist-level error is reported as JSON with exit code 1."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.exceptions import PlaylistNotFoundError

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.download.get_playlist_info",
                side_effect=PlaylistNotFoundError("no such playlist"),
            ),
        ):
            result = runner.invoke(
                cli, ["playlist", "https://youtube.com/playlist?list=BAD", "--json"],
            )

        assert result.exit_code == 1
        payload = json.loads(result.output.strip())
        assert payload["error_type"] == "PlaylistNotFoundError"
        assert "no such playlist" in payload["error"]


class TestRepeatRequestSkipsYoutube:
    """A video already in the vault is answered from the vault, with no YouTube request."""

    @staticmethod
    def _stored() -> object:
        from unittest.mock import MagicMock

        return MagicMock(
            title="Stored Title", source="auto_captions", caption_language="en",
        )

    def test_json_cache_hit_never_contacts_youtube(
        self, runner: CliRunner, sample_config: Config,
    ) -> None:
        """The ID in the URL is enough to find the saved note."""
        import json

        from yt_transcribe.cli import cli

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.extract_video_data",
                side_effect=AssertionError("must not contact YouTube"),
            ),
            patch(
                "yt_transcribe.cli.storage.find_existing",
                return_value=Path("/vault/cached.md"),
            ) as find,
            patch(
                "yt_transcribe.cli.storage.read_stored_transcript",
                return_value=self._stored(),
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload == {
            "path": str(Path("/vault/cached.md")),
            "title": "Stored Title",
            "video_id": "abc123abcde",
            "source": "cache",
            "original_source": "auto_captions",
            "caption_language": "en",
            "cached": True,
        }
        find.assert_called_once()
        assert find.call_args.args[1] == "abc123abcde"

    def test_json_falls_back_to_the_title_in_the_filename(
        self, runner: CliRunner, sample_config: Config,
    ) -> None:
        """Notes saved before titles were stored still report something readable."""
        import json
        from unittest.mock import MagicMock

        from yt_transcribe.cli import cli

        stored = MagicMock(title=None, source=None, caption_language=None)
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.extract_video_data",
                side_effect=AssertionError("must not contact YouTube"),
            ),
            patch(
                "yt_transcribe.cli.storage.find_existing",
                return_value=Path("/vault/Old Note [abc123abcde].md"),
            ),
            patch("yt_transcribe.cli.storage.read_stored_transcript", return_value=stored),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--json"],
            )

        assert json.loads(result.output.strip())["title"] == "Old Note [abc123abcde]"

    def test_json_url_without_an_id_still_checks_the_vault_after_fetching(
        self, runner: CliRunner, sample_config: Config, sample_video: VideoInfo,
    ) -> None:
        """A link form the ID pattern does not recognise keeps the old behaviour."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.extract_video_data", return_value=video_data,
            ) as fetch,
            patch(
                "yt_transcribe.cli.storage.find_existing",
                return_value=Path("/vault/cached.md"),
            ),
            patch(
                "yt_transcribe.cli.storage.read_stored_transcript",
                return_value=self._stored(),
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://www.youtube.com/live/abc123abcde", "--json"],
            )

        assert result.exit_code == 0
        assert json.loads(result.output.strip())["cached"] is True
        fetch.assert_called_once()

    def test_json_cache_miss_still_fetches_and_saves(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """Looking in the vault first must not stop a new video being transcribed."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.extract_video_data", return_value=video_data,
            ) as fetch,
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch(
                "yt_transcribe.cli.storage.save_transcript",
                return_value=Path("/vault/new.md"),
            ),
        ):
            result = runner.invoke(
                cli, ["video", "https://youtube.com/watch?v=abc123abcde", "--json"],
            )

        payload = json.loads(result.output.strip())
        assert payload["cached"] is False
        assert payload["path"] == str(Path("/vault/new.md"))
        fetch.assert_called_once()

    def test_text_mode_cache_hit_never_contacts_youtube(
        self, runner: CliRunner, sample_config: Config,
    ) -> None:
        from yt_transcribe.cli import cli

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.extract_video_data",
                side_effect=AssertionError("must not contact YouTube"),
            ),
            patch(
                "yt_transcribe.cli.storage.find_existing",
                return_value=Path("/vault/cached.md"),
            ),
            patch(
                "yt_transcribe.cli.storage.read_stored_transcript",
                return_value=self._stored(),
            ),
        ):
            result = runner.invoke(cli, ["video", "https://youtube.com/watch?v=abc123abcde"])

        assert result.exit_code == 0
        assert "cached" in result.output.lower()
        assert "Stored Title" in result.output


class TestPlaylistPartialFailure:
    """One failing video must not abort the rest of the playlist."""

    @staticmethod
    def _three_videos(sample_video: VideoInfo) -> tuple[VideoInfo, ...]:
        from dataclasses import replace

        return tuple(
            replace(sample_video, video_id=f"vid{n}vid{n}vi", title=f"Video {n}")
            for n in (1, 2, 3)
        )

    def test_json_reports_failed_videos_and_keeps_going(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """--json lists the failed video and still saves the others (exit 0)."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData
        from yt_transcribe.exceptions import NoCaptionsError

        videos = self._three_videos(sample_video)
        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.download.get_playlist_info", return_value=videos),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                side_effect=[sample_transcript, NoCaptionsError("no captions"),
                             sample_transcript],
            ),
            patch(
                "yt_transcribe.cli.storage.save_transcript",
                return_value=Path("/vault/x.md"),
            ),
        ):
            result = runner.invoke(
                cli, ["playlist", "https://youtube.com/playlist?list=PL1", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload["count"] == 2
        assert payload["failed"] == [{
            "video_id": "vid2vid2vi",
            "title": "Video 2",
            "error": "no captions",
            "error_type": "NoCaptionsError",
        }]

    def test_json_failed_is_empty_when_all_succeed(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """The failed key is always present so consumers need no existence check."""
        import json

        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.download.get_playlist_info",
                return_value=(sample_video,),
            ),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                return_value=sample_transcript,
            ),
            patch(
                "yt_transcribe.cli.storage.save_transcript",
                return_value=Path("/vault/x.md"),
            ),
        ):
            result = runner.invoke(
                cli, ["playlist", "https://youtube.com/playlist?list=PL1", "--json"],
            )

        assert json.loads(result.output.strip())["failed"] == []

    def test_text_mode_prints_failures_and_a_retry_hint(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo, sample_transcript: Transcript,
    ) -> None:
        """Without --json the failure and a re-run hint are shown to the user."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData
        from yt_transcribe.exceptions import CaptionFetchError

        videos = self._three_videos(sample_video)
        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.download.get_playlist_info", return_value=videos),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                side_effect=[sample_transcript, sample_transcript,
                             CaptionFetchError("rate limited")],
            ),
            patch("yt_transcribe.cli.storage.save_transcript"),
        ):
            result = runner.invoke(
                cli, ["playlist", "https://youtube.com/playlist?list=PL1"],
            )

        assert result.exit_code == 0
        assert "Failed" in result.output
        assert "rate limited" in result.output
        assert "1 failed" in result.output
        assert "re-run" in result.output.lower()

    def test_unexpected_errors_are_not_swallowed(
        self, runner: CliRunner, sample_config: Config,
        sample_video: VideoInfo,
    ) -> None:
        """Only known engine errors are recorded; a bug still surfaces."""
        from yt_transcribe.cli import cli
        from yt_transcribe.download import VideoData

        video_data = VideoData(
            video_info=sample_video, captions=None,
            raw_info={"id": "abc123abcde"},
        )
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.download.get_playlist_info",
                return_value=(sample_video,),
            ),
            patch("yt_transcribe.cli.storage.find_existing", return_value=None),
            patch("yt_transcribe.cli.extract_video_data", return_value=video_data),
            patch(
                "yt_transcribe.cli.transcribe.transcribe_video_fast",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = runner.invoke(
                cli, ["playlist", "https://youtube.com/playlist?list=PL1", "--json"],
            )

        assert isinstance(result.exception, RuntimeError)


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


# -- retired --strategy option --------------------------------------------

class TestRetiredStrategyOption:
    """--strategy was removed with the cloud strategy but is still accepted as 'captions'.

    Plugin versions before 0.5.0 always pass `--strategy captions`, so rejecting the
    option outright would break them until BRAT updates the plugin.
    """

    def test_captions_is_accepted_and_changes_nothing(
        self, runner: CliRunner, sample_config: Config, sample_video: VideoInfo,
    ) -> None:
        import json
        from unittest.mock import MagicMock

        from yt_transcribe.cli import cli

        stored = MagicMock(title="Stored Title", source="auto_captions", caption_language="en")
        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.cli.storage.find_existing",
                return_value=Path("/vault/cached.md"),
            ),
            patch("yt_transcribe.cli.storage.read_stored_transcript", return_value=stored),
        ):
            result = runner.invoke(
                cli,
                ["video", "https://youtube.com/watch?v=abc123abcde",
                 "--strategy", "captions", "--json"],
            )

        assert result.exit_code == 0
        assert json.loads(result.output.strip())["cached"] is True

    @pytest.mark.parametrize("command", ["video", "playlist"])
    def test_cloud_is_refused_with_a_clear_message(
        self, runner: CliRunner, command: str,
    ) -> None:
        from yt_transcribe.cli import cli

        result = runner.invoke(
            cli,
            [command, "https://youtube.com/watch?v=abc123abcde", "--strategy", "cloud"],
        )

        assert result.exit_code != 0
        assert "removed" in result.output
        assert "captions are the only source" in result.output

    def test_the_option_is_hidden_from_help(self, runner: CliRunner) -> None:
        from yt_transcribe.cli import cli

        for command in ("video", "playlist"):
            result = runner.invoke(cli, [command, "--help"])
            assert "--strategy" not in result.output

    def test_setup_ffmpeg_command_is_gone(self, runner: CliRunner) -> None:
        from yt_transcribe.cli import cli

        result = runner.invoke(cli, ["setup-ffmpeg"])
        assert result.exit_code != 0
        assert "No such command" in result.output


# -- config command ----------------------------------------------------------

class TestConfigCommand:
    """Tests for `yt-transcribe config` and `config set`."""

    def test_config_shows_values(self, runner: CliRunner, sample_config: Config) -> None:
        """Config command prints current settings."""
        from yt_transcribe.cli import cli

        with patch("yt_transcribe.cli.load_config", return_value=sample_config):
            result = runner.invoke(cli, ["config"])

        assert result.exit_code == 0
        assert "obsidian_vault_path" in result.output
        assert "transcript_folder" in result.output
        assert "strategy" not in result.output.lower()

    def test_config_set_updates_value(self, runner: CliRunner, sample_config: Config) -> None:
        """Config set writes new value."""
        from yt_transcribe.cli import cli

        with (
            patch("yt_transcribe.cli.load_config", return_value=sample_config),
            patch("yt_transcribe.cli.config_mod.save_config") as mock_save,
        ):
            result = runner.invoke(cli, ["config", "set", "transcript_folder", "Media/YT"])

        assert result.exit_code == 0
        mock_save.assert_called_once()
        assert mock_save.call_args.args[0].transcript_folder == "Media/YT"

    def test_config_set_invalid_key(self, runner: CliRunner, sample_config: Config) -> None:
        """Unknown config key shows error."""
        from yt_transcribe.cli import cli

        with patch("yt_transcribe.cli.load_config", return_value=sample_config):
            result = runner.invoke(cli, ["config", "set", "bogus_key", "value"])

        assert result.exit_code != 0 or "unknown" in result.output.lower()

    def test_config_set_rejects_the_removed_strategy_key(
        self, runner: CliRunner, sample_config: Config,
    ) -> None:
        """transcription_strategy went away with the cloud strategy."""
        from yt_transcribe.cli import cli

        with patch("yt_transcribe.cli.load_config", return_value=sample_config):
            result = runner.invoke(cli, ["config", "set", "transcription_strategy", "captions"])

        assert result.exit_code != 0
        assert "unknown config key" in result.output.lower()
