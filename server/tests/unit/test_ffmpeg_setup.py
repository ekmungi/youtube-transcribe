"""Tests for ffmpeg_setup. All network and config writes are mocked."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from yt_transcribe.exceptions import DownloadError
from yt_transcribe.ffmpeg_setup import (
    _binary_name,
    _extract_binaries,
    default_url,
    setup_ffmpeg,
)


def _make_zip(path: Path, members: dict[str, bytes]) -> None:
    """Write a zip file containing the given archive-name -> bytes members."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


class TestExtractBinaries:
    """Tests for pulling ffmpeg binaries out of a downloaded archive."""

    def test_extracts_ffmpeg_and_ffprobe_flattened(self, tmp_path: Path):
        """Both binaries are extracted from nested paths into dest_dir."""
        archive = tmp_path / "dl.zip"
        ffmpeg = _binary_name("ffmpeg")
        ffprobe = _binary_name("ffprobe")
        _make_zip(archive, {
            f"ffmpeg-7.0-essentials/bin/{ffmpeg}": b"FFMPEG-BINARY",
            f"ffmpeg-7.0-essentials/bin/{ffprobe}": b"FFPROBE-BINARY",
            "ffmpeg-7.0-essentials/README.txt": b"docs",
        })
        dest = tmp_path / "bin"
        dest.mkdir()

        extracted = _extract_binaries(archive, dest)

        names = {p.name for p in extracted}
        assert ffmpeg in names
        assert ffprobe in names
        assert (dest / ffmpeg).read_bytes() == b"FFMPEG-BINARY"

    def test_raises_when_no_ffmpeg_in_archive(self, tmp_path: Path):
        """An archive without ffmpeg is a clear error, not a silent success."""
        archive = tmp_path / "dl.zip"
        _make_zip(archive, {"some/other.txt": b"x"})
        dest = tmp_path / "bin"
        dest.mkdir()

        with pytest.raises(DownloadError, match="No ffmpeg binary"):
            _extract_binaries(archive, dest)

    def test_raises_when_not_a_zip(self, tmp_path: Path):
        """A non-zip download is rejected with guidance."""
        archive = tmp_path / "dl.zip"
        archive.write_bytes(b"not a zip")
        dest = tmp_path / "bin"
        dest.mkdir()

        with pytest.raises(DownloadError, match="not a zip"):
            _extract_binaries(archive, dest)


class TestDefaultUrl:
    """Tests for platform default URL resolution."""

    def test_returns_url_for_known_platform(self):
        """A known platform yields a concrete URL."""
        with patch("sys.platform", "win32"):
            assert default_url().startswith("https://")

    def test_raises_for_unknown_platform(self):
        """An unknown platform raises with actionable guidance."""
        with patch("sys.platform", "sunos"):
            with pytest.raises(DownloadError, match="No default ffmpeg URL"):
                default_url()


class TestSetupFfmpeg:
    """Tests for the end-to-end setup flow (config writes mocked)."""

    def test_uses_imageio_binary_when_available(self, tmp_path: Path):
        """When the [cloud] extra is present, its binary is copied in."""
        source = tmp_path / "src_ffmpeg"
        source.write_bytes(b"STATIC-FFMPEG")
        dest = tmp_path / "bin"

        with (
            patch(
                "yt_transcribe.ffmpeg_setup._imageio_ffmpeg_path",
                return_value=str(source),
            ),
            patch("yt_transcribe.ffmpeg_setup._record_in_config") as rec,
        ):
            result = setup_ffmpeg(dest_dir=dest)

        assert result == dest
        assert (dest / _binary_name("ffmpeg")).read_bytes() == b"STATIC-FFMPEG"
        rec.assert_called_once_with(dest)

    def test_downloads_and_extracts_when_no_imageio(self, tmp_path: Path):
        """Without imageio, it downloads then extracts the static build."""
        dest = tmp_path / "bin"
        ffmpeg = _binary_name("ffmpeg")

        def fake_download(url: str, archive: Path, on_progress: object) -> None:
            _make_zip(archive, {f"build/bin/{ffmpeg}": b"DOWNLOADED"})

        with (
            patch(
                "yt_transcribe.ffmpeg_setup._imageio_ffmpeg_path",
                return_value=None,
            ),
            patch("yt_transcribe.ffmpeg_setup._download", side_effect=fake_download),
            patch("yt_transcribe.ffmpeg_setup._record_in_config") as rec,
        ):
            result = setup_ffmpeg(url="https://example.com/ffmpeg.zip", dest_dir=dest)

        assert result == dest
        assert (dest / ffmpeg).read_bytes() == b"DOWNLOADED"
        # The temp archive is cleaned up after extraction.
        assert not (dest / "ffmpeg-download.zip").exists()
        rec.assert_called_once_with(dest)

    def test_record_in_config_writes_directory(self, tmp_path: Path):
        """_record_in_config persists the directory to ffmpeg_location."""
        from yt_transcribe.ffmpeg_setup import _record_in_config
        from yt_transcribe.models import Config, TranscriptionStrategy

        base = Config(
            obsidian_vault_path="/v", transcript_folder="",
            transcription_strategy=TranscriptionStrategy.CAPTIONS,
            ffmpeg_location="",
        )
        saved: dict[str, Config] = {}
        with (
            patch("yt_transcribe.ffmpeg_setup.load_config", return_value=base),
            patch(
                "yt_transcribe.ffmpeg_setup.save_config",
                side_effect=lambda c: saved.update(cfg=c),
            ),
        ):
            _record_in_config(Path("/home/x/.yt-transcribe/bin"))

        assert saved["cfg"].ffmpeg_location.endswith("bin")
