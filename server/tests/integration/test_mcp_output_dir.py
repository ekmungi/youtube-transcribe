"""Integration tests for the output_dir parameter on the get_transcript and
get_playlist_transcripts MCP tools: callers choose where transcripts land."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from yt_transcribe.models import Config, TranscriptionStrategy


def _config(vault: str = "/configured/vault", folder: str = "Transcripts") -> Config:
    """A concrete Config to be overridden by output_dir."""
    return Config(
        obsidian_vault_path=vault,
        transcript_folder=folder,
        transcription_strategy=TranscriptionStrategy.CAPTIONS,
    )


_WORKER_RESULT = {
    "title": "Test Video",
    "source": "manual_captions",
    "caption_language": "en",
    "path": "/tmp/out/Test Video [abc123abcde].md",
    "word_count": 2,
    "duration_seconds": 120,
}


class TestSchemaExposesOutputDir:
    """Both heavy tools advertise output_dir so Claude can set the location."""

    def test_get_transcript_schema_has_output_dir(self):
        from yt_transcribe.tool_schemas import TOOLS

        by_name = {t.name: t for t in TOOLS}
        props = by_name["get_transcript"].inputSchema["properties"]
        assert "output_dir" in props

    def test_get_playlist_schema_has_output_dir(self):
        from yt_transcribe.tool_schemas import TOOLS

        by_name = {t.name: t for t in TOOLS}
        props = by_name["get_playlist_transcripts"].inputSchema["properties"]
        assert "output_dir" in props


class TestGetTranscriptOutputDir:
    """output_dir routes both the cache check and the worker to a chosen dir."""

    @pytest.mark.asyncio()
    async def test_output_dir_forwarded_to_worker(self):
        """The worker payload carries output_dir so the file lands there."""
        from yt_transcribe.mcp_server import handle_get_transcript

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=_config()),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.mcp_server._run_worker",
                new_callable=AsyncMock,
                return_value=_WORKER_RESULT,
            ) as mock_worker,
        ):
            await handle_get_transcript(
                "https://youtube.com/watch?v=abc123abcde", output_dir="/tmp/out"
            )

        mock_worker.assert_called_once_with({
            "command": "get_transcript",
            "video_url": "https://youtube.com/watch?v=abc123abcde",
            "strategy": None,
            "include_text": False,
            "output_dir": "/tmp/out",
        })

    @pytest.mark.asyncio()
    async def test_cache_check_looks_in_output_dir(self):
        """The cache lookup is rooted at output_dir, not the configured vault."""
        from yt_transcribe.mcp_server import handle_get_transcript

        captured: dict[str, Any] = {}

        def _spy_find_existing(config: Config, video_id: str):
            captured["vault"] = config.obsidian_vault_path
            captured["folder"] = config.transcript_folder
            return None

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=_config()),
            patch(
                "yt_transcribe.mcp_server.storage.find_existing",
                side_effect=_spy_find_existing,
            ),
            patch(
                "yt_transcribe.mcp_server._run_worker",
                new_callable=AsyncMock,
                return_value=_WORKER_RESULT,
            ),
        ):
            await handle_get_transcript(
                "https://youtube.com/watch?v=abc123abcde", output_dir="/tmp/out"
            )

        assert captured["vault"] == "/tmp/out"
        assert captured["folder"] == ""


class TestGetPlaylistOutputDir:
    """output_dir flows through the playlist handler to the worker."""

    @pytest.mark.asyncio()
    async def test_output_dir_forwarded_to_worker(self):
        from yt_transcribe.mcp_server import handle_get_playlist_transcripts

        with patch(
            "yt_transcribe.mcp_server._run_worker",
            new_callable=AsyncMock,
            return_value={"transcripts": []},
        ) as mock_worker:
            await handle_get_playlist_transcripts(
                "https://youtube.com/playlist?list=PL123", output_dir="/tmp/out"
            )

        mock_worker.assert_called_once_with({
            "command": "get_playlist_transcripts",
            "playlist_url": "https://youtube.com/playlist?list=PL123",
            "strategy": None,
            "include_text": False,
            "output_dir": "/tmp/out",
        })
