"""Full-text search across transcript markdown files in the Obsidian vault."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yt_transcribe.models import Config


@dataclass(frozen=True)
class SearchResult:
    """A single search match with file metadata and context snippet.

    Attributes:
        file_path: Absolute path to the matching markdown file.
        title: Video title extracted from frontmatter.
        channel: Channel name extracted from frontmatter.
        snippet: Context snippet containing the matched query text.
    """
    file_path: Path
    title: str
    channel: str
    snippet: str


def _extract_frontmatter_field(content: str, field: str) -> str:
    """Extract a quoted field value from YAML frontmatter.

    Args:
        content: Full markdown file content.
        field: Frontmatter field name (e.g., 'title', 'channel').

    Returns:
        Field value with quotes stripped, or empty string if not found.
    """
    pattern = rf'^{field}:\s*"(.+)"'
    match = re.search(pattern, content, re.MULTILINE)
    return match.group(1) if match else ""


def _extract_snippet(content: str, query: str, context_chars: int = 80) -> str:
    """Extract a context snippet around the first occurrence of query.

    Args:
        content: Full file content to search.
        query: Search query (case-insensitive).
        context_chars: Number of characters of context on each side.

    Returns:
        Snippet with surrounding context, or empty string if not found.
    """
    lower_content = content.lower()
    lower_query = query.lower()
    idx = lower_content.find(lower_query)
    if idx == -1:
        return ""

    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    snippet = content[start:end].strip()

    # Clean up newlines for display
    snippet = re.sub(r'\s+', ' ', snippet)

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{snippet}{suffix}"


@dataclass(frozen=True)
class TranscriptEntry:
    """Metadata for a saved transcript file.

    Attributes:
        file_path: Absolute path to the markdown file.
        title: Video title extracted from frontmatter.
        channel: Channel name extracted from frontmatter.
        video_id: YouTube video ID extracted from frontmatter.
    """
    file_path: Path
    title: str
    channel: str
    video_id: str


def list_transcripts(config: Config, folder: str | None = None) -> list[TranscriptEntry]:
    """List all saved transcript files with metadata from frontmatter.

    Scans .md files in the transcript folder (or a subfolder if specified)
    and extracts title, channel, and video_id from YAML frontmatter.

    Args:
        config: Application configuration with vault path.
        folder: Optional subfolder name to filter results.

    Returns:
        List of TranscriptEntry sorted alphabetically by title.
    """
    base = Path(config.obsidian_vault_path) / config.transcript_folder
    if folder:
        base = base / folder
    if not base.exists():
        return []

    entries: list[TranscriptEntry] = []
    for md_file in sorted(base.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        title = _extract_frontmatter_field(content, "title")
        channel = _extract_frontmatter_field(content, "channel")
        video_id = _extract_frontmatter_field(content, "video_id")
        entries.append(TranscriptEntry(
            file_path=md_file,
            title=title,
            channel=channel,
            video_id=video_id,
        ))

    return entries


def search_transcripts(config: Config, query: str) -> list[SearchResult]:
    """Search all transcript markdown files for a query string.

    Performs case-insensitive search across both frontmatter and body text
    of all .md files in the transcript folder (including subfolders).

    Args:
        config: Application configuration with vault path.
        query: Search string (case-insensitive).

    Returns:
        List of SearchResult for each matching file.
    """
    folder = Path(config.obsidian_vault_path) / config.transcript_folder
    if not folder.exists():
        return []

    results: list[SearchResult] = []
    lower_query = query.lower()

    for md_file in sorted(folder.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        if lower_query not in content.lower():
            continue

        title = _extract_frontmatter_field(content, "title")
        channel = _extract_frontmatter_field(content, "channel")
        snippet = _extract_snippet(content, query)

        results.append(SearchResult(
            file_path=md_file,
            title=title,
            channel=channel,
            snippet=snippet,
        ))

    return results
