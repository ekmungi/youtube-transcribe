"""Integration tests for MCP server tools.

Lightweight tools (list, search) mock their data sources.
Heavy tools (get_transcript, get_playlist) mock _run_worker since
the actual transcription now runs in a subprocess.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

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
        video_id="abc123",
        title="Test Video",
        channel="Test Channel",
        url="https://youtube.com/watch?v=abc123",
        duration_seconds=120,
        playlist_title=None,
    )


@pytest.fixture()
def sample_transcript(sample_video: VideoInfo) -> Transcript:
    """Return a Transcript for the sample video."""
    return Transcript(
        video=sample_video,
        text="Hello world",
        segments=(Segment(0.0, 5.0, "Hello world"),),
        source=TranscriptSource.MANUAL_CAPTIONS,
        caption_language="en",
    )


# -- get_transcript ----------------------------------------------------------

# A cache file in the current (0.7.0+) format with source/caption_language
_CACHED_MARKDOWN = (
    "---\n"
    'title: "Cached Video"\n'
    'channel: "Test Channel"\n'
    'url: "https://youtube.com/watch?v=abc123abcde"\n'
    'video_id: "abc123abcde"\n'
    "date: 2026-06-01\n"
    'duration: "2:00"\n'
    "source: manual_captions\n"
    'caption_language: "en"\n'
    "tags:\n"
    "  - youtube\n"
    "  - transcript\n"
    "---\n"
    "\n"
    "# Cached Video\n"
    "\n"
    "Hello cached world\n"
)


def _write_cache_file(tmp_path: Path, content: str) -> Path:
    """Write a transcript markdown file into the temp vault and return it."""
    cache_path = tmp_path / "vault" / "Transcripts" / "cached.md"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(content, encoding="utf-8")
    return cache_path


class TestGetTranscript:
    """Tests for the get_transcript MCP tool handler."""

    @pytest.mark.asyncio()
    async def test_returns_cached_transcript(
        self, sample_config: Config, tmp_path: Path
    ) -> None:
        """Cache hit returns path plus the metadata the tool contract promises
        (title, caption_language, word_count) without spawning a worker."""
        from yt_transcribe.mcp_server import handle_get_transcript

        cache_path = _write_cache_file(tmp_path, _CACHED_MARKDOWN)

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=cache_path),
        ):
            result = await handle_get_transcript("https://youtube.com/watch?v=abc123abcde")

        assert result["source"] == "cache"
        assert result["path"] == str(cache_path)
        assert result["title"] == "Cached Video"
        assert result["original_source"] == "manual_captions"
        assert result["caption_language"] == "en"
        assert result["word_count"] > 0
        assert "text" not in result

    @pytest.mark.asyncio()
    async def test_cached_transcript_honors_include_text(
        self, sample_config: Config, tmp_path: Path
    ) -> None:
        """include_text=True on a cache hit returns the stored body text."""
        from yt_transcribe.mcp_server import handle_get_transcript

        cache_path = _write_cache_file(tmp_path, _CACHED_MARKDOWN)

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=cache_path),
        ):
            result = await handle_get_transcript(
                "https://youtube.com/watch?v=abc123abcde", include_text=True
            )

        assert result["source"] == "cache"
        assert "Hello cached world" in result["text"]

    @pytest.mark.asyncio()
    async def test_cached_pre_070_file_returns_null_metadata(
        self, sample_config: Config, tmp_path: Path
    ) -> None:
        """Cache files saved before 0.7.0 lack source/caption_language; the
        response carries null for them instead of failing."""
        from yt_transcribe.mcp_server import handle_get_transcript

        legacy_markdown = (
            "---\n"
            'title: "Old Cached Video"\n'
            'channel: "Test Channel"\n'
            'video_id: "abc123abcde"\n'
            "---\n"
            "\n# Old Cached Video\n\nOld body\n"
        )
        cache_path = _write_cache_file(tmp_path, legacy_markdown)

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=cache_path),
        ):
            result = await handle_get_transcript("https://youtube.com/watch?v=abc123abcde")

        assert result["source"] == "cache"
        assert result["title"] == "Old Cached Video"
        assert result["original_source"] is None
        assert result["caption_language"] is None

    @pytest.mark.asyncio()
    async def test_sync_transcription_for_short_video(self) -> None:
        """Cache miss spawns worker subprocess and returns path, not text."""
        from yt_transcribe.mcp_server import handle_get_transcript

        worker_result = {
            "title": "Test Video",
            "source": "manual_captions",
            "caption_language": "en",
            "path": "/vault/Transcripts/Test Video [abc123abcde].md",
            "word_count": 2,
            "duration_seconds": 120,
        }

        with (
            patch("yt_transcribe.mcp_server.load_config"),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.mcp_server._run_worker",
                new_callable=AsyncMock,
                return_value=worker_result,
            ) as mock_worker,
        ):
            result = await handle_get_transcript(
                "https://youtube.com/watch?v=abc123abcde", strategy="captions"
            )

        assert "text" not in result
        assert result["path"] == "/vault/Transcripts/Test Video [abc123abcde].md"
        assert result["source"] == "manual_captions"
        assert result["caption_language"] == "en"
        assert result["word_count"] == 2
        mock_worker.assert_called_once_with({
            "command": "get_transcript",
            "video_url": "https://youtube.com/watch?v=abc123abcde",
            "strategy": "captions",
            "include_text": False,
            "output_dir": None,
        })

    @pytest.mark.asyncio()
    async def test_include_text_returns_inline_text(self) -> None:
        """include_text=True passes through and returns text in result."""
        from yt_transcribe.mcp_server import handle_get_transcript

        worker_result = {
            "title": "Test Video",
            "source": "manual_captions",
            "caption_language": "en",
            "path": "/vault/Transcripts/Test Video [abc123abcde].md",
            "word_count": 2,
            "duration_seconds": 120,
            "text": "Hello world",
        }

        with (
            patch("yt_transcribe.mcp_server.load_config"),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.mcp_server._run_worker",
                new_callable=AsyncMock,
                return_value=worker_result,
            ) as mock_worker,
        ):
            result = await handle_get_transcript(
                "https://youtube.com/watch?v=abc123abcde",
                strategy="captions",
                include_text=True,
            )

        assert result["text"] == "Hello world"
        assert result["path"] == "/vault/Transcripts/Test Video [abc123abcde].md"
        mock_worker.assert_called_once_with({
            "command": "get_transcript",
            "video_url": "https://youtube.com/watch?v=abc123abcde",
            "strategy": "captions",
            "include_text": True,
            "output_dir": None,
        })

    @pytest.mark.asyncio()
    async def test_long_video_transcribes_inline(self) -> None:
        """Long videos transcribe inline with path, not text."""
        from yt_transcribe.mcp_server import handle_get_transcript

        worker_result = {
            "title": "Long Video",
            "source": "auto_captions",
            "caption_language": "en",
            "path": "/vault/Transcripts/Long Video [long1long1l].md",
            "word_count": 3,
            "duration_seconds": 7200,
        }

        with (
            patch("yt_transcribe.mcp_server.load_config"),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.mcp_server._run_worker",
                new_callable=AsyncMock,
                return_value=worker_result,
            ),
        ):
            result = await handle_get_transcript("https://youtube.com/watch?v=long1long1l")

        assert "text" not in result
        assert result["path"] == "/vault/Transcripts/Long Video [long1long1l].md"
        assert result["source"] == "auto_captions"

    @pytest.mark.asyncio()
    async def test_worker_error_is_surfaced(self) -> None:
        """Worker errors are returned as error dicts."""
        from yt_transcribe.mcp_server import handle_get_transcript

        with (
            patch("yt_transcribe.mcp_server.load_config"),
            patch("yt_transcribe.mcp_server.storage.find_existing", return_value=None),
            patch(
                "yt_transcribe.mcp_server._run_worker",
                new_callable=AsyncMock,
                return_value={"error": "Worker timed out"},
            ),
        ):
            result = await handle_get_transcript("https://youtube.com/watch?v=abc123abcde")

        assert "error" in result


# -- get_playlist_transcripts ------------------------------------------------

class TestGetPlaylistTranscripts:
    """Tests for the get_playlist_transcripts MCP tool handler."""

    @pytest.mark.asyncio()
    async def test_short_playlist_sync(self) -> None:
        """Short playlist delegated to worker returns paths, not text."""
        from yt_transcribe.mcp_server import handle_get_playlist_transcripts

        worker_result = {
            "transcripts": [
                {
                    "title": "Video 1",
                    "source": "manual_captions",
                    "caption_language": "en",
                    "path": "/vault/Transcripts/Video 1 [v1].md",
                    "word_count": 1,
                },
            ]
        }

        with patch(
            "yt_transcribe.mcp_server._run_worker",
            new_callable=AsyncMock,
            return_value=worker_result,
        ) as mock_worker:
            result = await handle_get_playlist_transcripts(
                "https://youtube.com/playlist?list=PL123", strategy="captions"
            )

        assert len(result["transcripts"]) == 1
        assert "text" not in result["transcripts"][0]
        assert "path" in result["transcripts"][0]
        assert result["transcripts"][0]["source"] == "manual_captions"
        mock_worker.assert_called_once_with({
            "command": "get_playlist_transcripts",
            "playlist_url": "https://youtube.com/playlist?list=PL123",
            "strategy": "captions",
            "include_text": False,
            "output_dir": None,
        })

    @pytest.mark.asyncio()
    async def test_long_playlist_transcribes_inline(self) -> None:
        """Long playlists transcribe inline with paths, not text."""
        from yt_transcribe.mcp_server import handle_get_playlist_transcripts

        worker_result = {
            "transcripts": [
                {
                    "title": "Video 1",
                    "source": "auto_captions",
                    "caption_language": "en",
                    "path": "/vault/Transcripts/Video 1 [v1].md",
                    "word_count": 2,
                },
                {
                    "title": "Video 2",
                    "source": "auto_captions",
                    "caption_language": "en",
                    "path": "/vault/Transcripts/Video 2 [v2].md",
                    "word_count": 2,
                },
            ]
        }

        with patch(
            "yt_transcribe.mcp_server._run_worker",
            new_callable=AsyncMock,
            return_value=worker_result,
        ):
            result = await handle_get_playlist_transcripts(
                "https://youtube.com/playlist?list=PL999"
            )

        assert len(result["transcripts"]) == 2


# -- list_transcripts --------------------------------------------------------

class TestListTranscripts:
    """Tests for the list_transcripts MCP tool handler."""

    @pytest.mark.asyncio()
    async def test_list_returns_entries(self, sample_config: Config) -> None:
        """List returns metadata for saved transcripts."""
        from yt_transcribe.mcp_server import handle_list_transcripts
        from yt_transcribe.search import TranscriptEntry

        entries = [
            TranscriptEntry(Path("/vault/a.md"), "Video A", "Ch1", "a1"),
            TranscriptEntry(Path("/vault/b.md"), "Video B", "Ch2", "b2"),
        ]
        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch("yt_transcribe.mcp_server.search.list_transcripts", return_value=entries),
        ):
            result = await handle_list_transcripts(folder=None)

        assert len(result["transcripts"]) == 2
        assert result["transcripts"][0]["title"] == "Video A"

    @pytest.mark.asyncio()
    async def test_list_with_folder_filter(self, sample_config: Config) -> None:
        """Folder argument is forwarded to list function."""
        from yt_transcribe.mcp_server import handle_list_transcripts

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch(
                "yt_transcribe.mcp_server.search.list_transcripts", return_value=[]
            ) as mock_list,
        ):
            await handle_list_transcripts(folder="MIT Course")

        mock_list.assert_called_once_with(sample_config, folder="MIT Course")


# -- search_transcripts ------------------------------------------------------

class TestSearchTranscripts:
    """Tests for the search_transcripts MCP tool handler."""

    @pytest.mark.asyncio()
    async def test_search_returns_matches(self, sample_config: Config) -> None:
        """Search returns matching snippets."""
        from yt_transcribe.mcp_server import handle_search_transcripts
        from yt_transcribe.search import SearchResult

        matches = [
            SearchResult(Path("/vault/ml.md"), "ML Intro", "Prof", "...gradient descent..."),
        ]
        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch("yt_transcribe.mcp_server.search.search_transcripts", return_value=matches),
        ):
            result = await handle_search_transcripts("gradient descent")

        assert len(result["matches"]) == 1
        assert "gradient" in result["matches"][0]["snippet"]

    @pytest.mark.asyncio()
    async def test_search_empty_results(self, sample_config: Config) -> None:
        """No matches returns empty list."""
        from yt_transcribe.mcp_server import handle_search_transcripts

        with (
            patch("yt_transcribe.mcp_server.load_config", return_value=sample_config),
            patch("yt_transcribe.mcp_server.search.search_transcripts", return_value=[]),
        ):
            result = await handle_search_transcripts("nonexistent term xyz")

        assert result["matches"] == []
