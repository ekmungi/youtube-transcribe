"""Integration tests for the unified get_transcripts MCP tool: it accepts one
URL or many, auto-detects video vs playlist, and routes each accordingly."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

_VIDEO = "https://youtu.be/dQw4w9WgXcQ"
_PLAYLIST = "https://www.youtube.com/playlist?list=PLabc123"


class TestGetTranscriptsRouting:
    """A URL is dispatched to the video or playlist handler by classification."""

    @pytest.mark.asyncio()
    async def test_single_video_string_routes_to_video_handler(self):
        from yt_transcribe.mcp_server import handle_get_transcripts

        with (
            patch(
                "yt_transcribe.mcp_server.handle_get_transcript",
                new_callable=AsyncMock, return_value={"path": "/x", "title": "V"},
            ) as video_h,
            patch(
                "yt_transcribe.mcp_server.handle_get_playlist_transcripts",
                new_callable=AsyncMock,
            ) as playlist_h,
        ):
            result = await handle_get_transcripts(_VIDEO)

        video_h.assert_awaited_once()
        playlist_h.assert_not_awaited()
        assert result["results"][0]["kind"] == "video"

    @pytest.mark.asyncio()
    async def test_playlist_string_routes_to_playlist_handler(self):
        from yt_transcribe.mcp_server import handle_get_transcripts

        with (
            patch(
                "yt_transcribe.mcp_server.handle_get_transcript",
                new_callable=AsyncMock,
            ) as video_h,
            patch(
                "yt_transcribe.mcp_server.handle_get_playlist_transcripts",
                new_callable=AsyncMock, return_value={"transcripts": []},
            ) as playlist_h,
        ):
            result = await handle_get_transcripts(_PLAYLIST)

        playlist_h.assert_awaited_once()
        video_h.assert_not_awaited()
        assert result["results"][0]["kind"] == "playlist"

    @pytest.mark.asyncio()
    async def test_list_of_mixed_urls_routes_each(self):
        from yt_transcribe.mcp_server import handle_get_transcripts

        with (
            patch(
                "yt_transcribe.mcp_server.handle_get_transcript",
                new_callable=AsyncMock, return_value={"path": "/x"},
            ) as video_h,
            patch(
                "yt_transcribe.mcp_server.handle_get_playlist_transcripts",
                new_callable=AsyncMock, return_value={"transcripts": []},
            ) as playlist_h,
        ):
            result = await handle_get_transcripts([_VIDEO, _PLAYLIST])

        video_h.assert_awaited_once()
        playlist_h.assert_awaited_once()
        assert len(result["results"]) == 2

    @pytest.mark.asyncio()
    async def test_output_dir_forwarded_to_routed_handler(self):
        from yt_transcribe.mcp_server import handle_get_transcripts

        with patch(
            "yt_transcribe.mcp_server.handle_get_transcript",
            new_callable=AsyncMock, return_value={"path": "/x"},
        ) as video_h:
            await handle_get_transcripts(_VIDEO, output_dir="/tmp/out")

        assert video_h.call_args.kwargs["output_dir"] == "/tmp/out"


class TestSchemaExposesGetTranscripts:
    """The unified tool is advertised with a urls parameter."""

    def test_tool_present_with_urls_and_output_dir(self):
        from yt_transcribe.tool_schemas import TOOLS

        by_name = {t.name: t for t in TOOLS}
        assert "get_transcripts" in by_name
        props = by_name["get_transcripts"].inputSchema["properties"]
        assert "urls" in props
        assert "output_dir" in props
