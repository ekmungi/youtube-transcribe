"""Tests for full-text search across transcript markdown files."""

from pathlib import Path

import pytest

from yt_transcribe.models import Config, TranscriptionStrategy
from yt_transcribe.search import SearchResult, search_transcripts


def _make_config(tmp_path: Path) -> Config:
    """Build a Config pointing at a temporary vault directory."""
    return Config(
        obsidian_vault_path=str(tmp_path / "vault"),
        transcript_folder="Sources/YouTube Transcripts",
        transcription_strategy=TranscriptionStrategy.CAPTIONS,    )


def _write_md(folder: Path, name: str, content: str) -> Path:
    """Write a markdown file with given content to the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / name
    file_path.write_text(content, encoding="utf-8")
    return file_path


SAMPLE_MD_1 = """\
---
title: "Introduction to Machine Learning"
channel: "MIT OpenCourseWare"
url: "https://youtube.com/watch?v=abc123"
video_id: "abc123"
date: 2026-03-12
duration: "45:32"
tags:
  - youtube
  - transcript
---

# Introduction to Machine Learning

Welcome to today's lecture on machine learning fundamentals.
We will cover gradient descent and neural networks.
"""

SAMPLE_MD_2 = """\
---
title: "Advanced Python Decorators"
channel: "Tech With Tim"
url: "https://youtube.com/watch?v=def456"
video_id: "def456"
date: 2026-03-12
duration: "22:10"
tags:
  - youtube
  - transcript
---

# Advanced Python Decorators

Today we explore decorators and metaclasses in Python.
Functional programming concepts are also discussed.
"""

SAMPLE_MD_3 = """\
---
title: "Cooking with Gradient Spices"
channel: "Chef AI"
url: "https://youtube.com/watch?v=ghi789"
video_id: "ghi789"
date: 2026-03-12
duration: "15:00"
tags:
  - youtube
  - transcript
---

# Cooking with Gradient Spices

A fun cooking show that has nothing to do with math.
"""


class TestSearchResult:
    def test_is_frozen(self):
        result = SearchResult(
            file_path=Path("/test.md"),
            title="Test",
            channel="Ch",
            snippet="...",
        )
        with pytest.raises(AttributeError):
            result.title = "Other"  # type: ignore[misc]


class TestSearchTranscripts:
    def test_finds_matching_body_text(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)
        _write_md(folder, "python.md", SAMPLE_MD_2)

        results = search_transcripts(config, "gradient descent")
        assert len(results) == 1
        assert results[0].title == "Introduction to Machine Learning"

    def test_finds_matching_title(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)
        _write_md(folder, "python.md", SAMPLE_MD_2)

        results = search_transcripts(config, "Python Decorators")
        assert len(results) == 1
        assert results[0].title == "Advanced Python Decorators"

    def test_finds_matching_channel(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)
        _write_md(folder, "python.md", SAMPLE_MD_2)

        results = search_transcripts(config, "MIT OpenCourseWare")
        assert len(results) == 1

    def test_case_insensitive(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)

        results = search_transcripts(config, "GRADIENT DESCENT")
        assert len(results) == 1

    def test_multiple_matches(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)
        _write_md(folder, "cooking.md", SAMPLE_MD_3)

        results = search_transcripts(config, "gradient")
        assert len(results) == 2

    def test_no_matches_returns_empty(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)

        results = search_transcripts(config, "quantum physics")
        assert results == []

    def test_empty_folder_returns_empty(self, tmp_path: Path):
        config = _make_config(tmp_path)
        results = search_transcripts(config, "anything")
        assert results == []

    def test_snippet_contains_query_context(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        _write_md(folder, "ml.md", SAMPLE_MD_1)

        results = search_transcripts(config, "neural networks")
        assert len(results) == 1
        assert "neural networks" in results[0].snippet.lower()

    def test_searches_in_subfolders(self, tmp_path: Path):
        config = _make_config(tmp_path)
        folder = Path(config.obsidian_vault_path) / config.transcript_folder
        subfolder = folder / "MIT Playlist"
        _write_md(subfolder, "ml.md", SAMPLE_MD_1)

        results = search_transcripts(config, "machine learning")
        assert len(results) == 1
