"""Tests that the reported version is read from package metadata, not hardcoded."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

import yt_transcribe
from yt_transcribe.cli import cli

# pyproject.toml is the single place the version is edited.
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


class TestPackageVersion:
    """__version__ must track pyproject.toml via installed metadata."""

    def test_version_matches_pyproject(self):
        declared = tomllib.loads(_PYPROJECT.read_text())["project"]["version"]
        assert yt_transcribe.__version__ == declared

    def test_resolve_returns_fallback_when_not_installed(self):
        with patch("yt_transcribe.version", side_effect=PackageNotFoundError):
            assert yt_transcribe._resolve_version() == "0.0.0+unknown"


class TestCliVersionFlag:
    """`yt-transcribe --version` lets tooling (the Obsidian plugin) read the engine version."""

    def test_version_flag_prints_package_version(self):
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.strip() == f"yt-transcribe, version {yt_transcribe.__version__}"

    def test_unknown_flag_still_fails(self):
        # Guards against --version swallowing option parsing for other flags.
        result = CliRunner().invoke(cli, ["--no-such-flag"])
        assert result.exit_code != 0
