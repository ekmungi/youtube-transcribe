"""Unit tests for search.list_transcripts -- listing saved transcript metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_transcribe.models import Config, TranscriptionStrategy
from yt_transcribe.search import TranscriptEntry, list_transcripts

# -- Fixtures ----------------------------------------------------------------

@pytest.fixture()
def config(tmp_path: Path) -> Config:
    """Return a Config pointing at a temp vault."""
    return Config(
        obsidian_vault_path=str(tmp_path / "vault"),
        transcript_folder="Transcripts",
        transcription_strategy=TranscriptionStrategy.CAPTIONS,    )


def _write_md(folder: Path, filename: str, title: str, channel: str, video_id: str) -> Path:
    """Helper to write a fake transcript markdown file."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(
        f'---\ntitle: "{title}"\nchannel: "{channel}"\nvideo_id: "{video_id}"\n---\n\nBody text.\n',
        encoding="utf-8",
    )
    return path


# -- Tests -------------------------------------------------------------------

class TestListTranscripts:
    """Tests for list_transcripts function."""

    def test_empty_when_folder_missing(self, config: Config) -> None:
        """Returns empty list when transcript folder does not exist."""
        result = list_transcripts(config)
        assert result == []

    def test_lists_all_transcripts(self, config: Config, tmp_path: Path) -> None:
        """Returns entries for all .md files in transcript folder."""
        base = tmp_path / "vault" / "Transcripts"
        _write_md(base, "video_a.md", "Video A", "Channel 1", "aaa111")
        _write_md(base, "video_b.md", "Video B", "Channel 2", "bbb222")

        result = list_transcripts(config)

        assert len(result) == 2
        assert result[0].title == "Video A"
        assert result[0].video_id == "aaa111"
        assert result[1].title == "Video B"

    def test_lists_subfolder_only(self, config: Config, tmp_path: Path) -> None:
        """Folder filter limits results to that subfolder."""
        base = tmp_path / "vault" / "Transcripts"
        _write_md(base, "root.md", "Root Video", "Ch", "r1")
        _write_md(base / "Lectures", "lec1.md", "Lecture 1", "Prof", "l1")

        result = list_transcripts(config, folder="Lectures")

        assert len(result) == 1
        assert result[0].title == "Lecture 1"

    def test_returns_transcript_entry_type(self, config: Config, tmp_path: Path) -> None:
        """Each item is a TranscriptEntry with expected fields."""
        base = tmp_path / "vault" / "Transcripts"
        _write_md(base, "v.md", "My Video", "My Channel", "vid123")

        result = list_transcripts(config)

        assert len(result) == 1
        entry = result[0]
        assert isinstance(entry, TranscriptEntry)
        assert entry.title == "My Video"
        assert entry.channel == "My Channel"
        assert entry.video_id == "vid123"
        assert entry.file_path.name == "v.md"
