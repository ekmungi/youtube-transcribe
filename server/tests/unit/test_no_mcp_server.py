"""Tests that prove the MCP server was removed in 0.14.0 and stays removed."""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[2]
_PYPROJECT = tomllib.loads((_SERVER_DIR / "pyproject.toml").read_text(encoding="utf-8"))
_SOURCE_DIR = _SERVER_DIR / "src" / "yt_transcribe"

# Modules that existed only to run the MCP server and its background worker process.
_REMOVED_MODULES = ["mcp_server", "tool_schemas", "worker_runner", "worker"]


class TestModulesAreGone:
    """Nothing of the server or its worker may be importable."""

    @pytest.mark.parametrize("name", _REMOVED_MODULES)
    def test_module_is_not_importable(self, name: str):
        assert importlib.util.find_spec(f"yt_transcribe.{name}") is None

    def test_no_source_file_mentions_mcp(self):
        offenders = [
            path.name
            for path in _SOURCE_DIR.glob("*.py")
            if re.search(r"\bmcp\b", path.read_text(encoding="utf-8"), re.IGNORECASE)
        ]
        assert offenders == []


class TestPackaging:
    """The package declares a CLI and nothing else."""

    def test_only_the_cli_is_installed_as_a_command(self):
        assert list(_PYPROJECT["project"]["scripts"]) == ["yt-transcribe"]

    def test_no_dependency_on_the_mcp_sdk(self):
        names = [re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0].lower()
                 for dep in _PYPROJECT["project"]["dependencies"]]
        assert "mcp" not in names

    def test_description_does_not_advertise_a_server(self):
        assert "mcp" not in _PYPROJECT["project"]["description"].lower()

    def test_no_register_scripts_remain(self):
        assert not (_SERVER_DIR / "scripts").exists()
