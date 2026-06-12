"""Markdown storage for Obsidian vault -- write, read back, and deduplicate
transcripts. Single owner of the saved-file format (frontmatter + body)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yt_transcribe.formatting import format_transcript_body
from yt_transcribe.models import Config, Transcript

# Matches the YAML frontmatter block at the start of a saved transcript file
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class StoredTranscript:
    """Metadata and body parsed back from a saved transcript markdown file.

    Fields are None when absent from the frontmatter (files saved before
    0.7.0 lack source and caption_language) or when stored as YAML null.
    body is everything after the closing frontmatter delimiter.
    """

    title: str | None
    source: str | None
    caption_language: str | None
    body: str


def _frontmatter_value(frontmatter: str, field: str) -> str | None:
    """Extract one scalar frontmatter field by line-based lookup.

    Line-based rather than yaml.safe_load so files with unescaped quotes in
    titles (a known pre-existing issue) still parse.

    Args:
        frontmatter: Raw frontmatter text between the --- delimiters.
        field: Field name (e.g. 'title', 'source', 'caption_language').

    Returns:
        The field value with surrounding quotes stripped, or None when the
        field is absent or stored as YAML null.
    """
    match = re.search(rf"^{field}:\s*(.+)$", frontmatter, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip()
    if value == "null":
        return None
    return value.strip('"')


def read_stored_transcript(path: Path) -> StoredTranscript:
    """Parse a saved transcript file into metadata and body text.

    Used by cache-hit responses to honor the tool contract (title, source,
    caption_language, optional inline text) without re-transcribing.

    Args:
        path: Path to a transcript markdown file written by save_transcript.

    Returns:
        StoredTranscript; metadata fields are None for files without
        frontmatter or saved before 0.7.0 (missing source/caption_language).
    """
    content = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        # No frontmatter at all: treat the whole file as body
        return StoredTranscript(title=None, source=None, caption_language=None, body=content)

    frontmatter = match.group(1)
    body = content[match.end():].lstrip("\n")
    return StoredTranscript(
        title=_frontmatter_value(frontmatter, "title"),
        source=_frontmatter_value(frontmatter, "source"),
        caption_language=_frontmatter_value(frontmatter, "caption_language"),
        body=body,
    )


def sanitize_filename(name: str) -> str:
    """Remove filesystem-unsafe characters and normalize whitespace.

    Args:
        name: Raw video title.

    Returns:
        Cleaned string safe for use as a filename (without extension).
    """
    # Replace backslashes, pipes, and forward slashes with underscores
    cleaned = re.sub(r'[\\|/]', '_', name)
    # Remove other unsafe characters
    cleaned = re.sub(r'[<>:?"*]', '', cleaned)
    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Truncate to 200 characters
    cleaned = cleaned[:200]
    return cleaned if cleaned else "untitled"


def _format_duration(seconds: int) -> str:
    """Format duration in seconds to MM:SS or H:MM:SS string.

    Args:
        seconds: Total duration in seconds.

    Returns:
        Human-readable duration string.
    """
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_markdown(transcript: Transcript) -> str:
    """Format a transcript as a complete markdown document with frontmatter.

    Includes YAML frontmatter (title, channel, url, video_id, date, duration,
    source, caption_language, tags) and body text with timestamps at
    5-minute intervals. caption_language is null for speech-to-text results.

    Args:
        transcript: Complete transcript to format.

    Returns:
        Full markdown string ready to write to disk.
    """
    from datetime import date

    video = transcript.video
    duration_str = _format_duration(video.duration_seconds)
    today = date.today().isoformat()

    # caption_language is None for AssemblyAI results; write YAML null
    language_value = (
        f'"{transcript.caption_language}"'
        if transcript.caption_language is not None
        else "null"
    )

    frontmatter = (
        "---\n"
        f'title: "{video.title}"\n'
        f'channel: "{video.channel}"\n'
        f"url: \"{video.url}\"\n"
        f'video_id: "{video.video_id}"\n'
        f"date: {today}\n"
        f'duration: "{duration_str}"\n'
        f"source: {transcript.source.value}\n"
        f"caption_language: {language_value}\n"
        "tags:\n"
        "  - youtube\n"
        "  - transcript\n"
        "---\n"
    )

    # Fall back to the plain text only when there are no segments to format.
    body = format_transcript_body(transcript.segments) or transcript.text

    return f"{frontmatter}\n# {video.title}\n\n{body}\n"


def _transcript_folder_path(config: Config) -> Path:
    """Resolve the full path to the transcript folder in the vault.

    Args:
        config: Application configuration.

    Returns:
        Absolute path to the transcript output folder.
    """
    return Path(config.obsidian_vault_path) / config.transcript_folder


def find_existing(config: Config, video_id: str) -> Path | None:
    """Search for an existing transcript markdown file by video_id.

    Uses fast glob-based lookup first (matching [video_id] in filename),
    then falls back to frontmatter scan for backward compatibility with
    files saved before the naming convention change.

    Args:
        config: Application configuration.
        video_id: YouTube video ID to search for.

    Returns:
        Path to existing file if found, None otherwise.
    """
    folder = _transcript_folder_path(config)
    if not folder.exists():
        return None

    # Fast path: glob for files with video_id in filename
    # Escape brackets: [[] matches literal '[', []] matches literal ']'
    pattern = f"*[[]{video_id}[]]*.md"
    matches = list(folder.rglob(pattern))
    if matches:
        return matches[0]

    # Slow fallback: scan frontmatter for legacy files without video_id in name
    target = f'video_id: "{video_id}"'
    for md_file in folder.rglob("*.md"):
        # Only read first 512 bytes (frontmatter) instead of full file
        content = md_file.read_text(encoding="utf-8")[:512]
        if target in content:
            return md_file

    return None


def _build_filename(title: str, video_id: str) -> str:
    """Build a filename with video_id embedded for fast lookup.

    Format: {sanitized_title} [{video_id}].md

    Args:
        title: Video title.
        video_id: YouTube video ID.

    Returns:
        Filename string with .md extension.
    """
    safe_title = sanitize_filename(title)
    return f"{safe_title} [{video_id}].md"


def save_transcript(config: Config, transcript: Transcript) -> Path:
    """Save a transcript as a markdown file to the Obsidian vault.

    Filename format: {title} [{video_id}].md for fast deduplication lookup.
    Single videos go to {vault}/{folder}/{title} [{video_id}].md.
    Playlist videos go to {vault}/{folder}/{playlist_name}/{title} [{video_id}].md.
    Deduplicates by video_id -- returns existing path if already saved.

    Args:
        config: Application configuration.
        transcript: Complete transcript to save.

    Returns:
        Path to the saved (or existing) markdown file.
    """
    # Deduplication check
    existing = find_existing(config, transcript.video.video_id)
    if existing is not None:
        return existing

    folder = _transcript_folder_path(config)

    # Playlist videos get a subfolder
    if transcript.video.playlist_title is not None:
        folder = folder / sanitize_filename(transcript.video.playlist_title)

    folder.mkdir(parents=True, exist_ok=True)

    filename = _build_filename(transcript.video.title, transcript.video.video_id)
    file_path = folder / filename

    markdown = format_markdown(transcript)
    file_path.write_text(markdown, encoding="utf-8")

    return file_path
