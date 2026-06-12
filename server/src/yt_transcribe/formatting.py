"""Format caption segments into readable Markdown prose with timestamps.

Shared by storage (the saved file body) and transcribe (the in-memory
transcript text) so both render identically: flowing paragraphs separated by
[timestamp] markers, never a column of one-line caption fragments.
"""

from __future__ import annotations

import re

from yt_transcribe.models import Segment

# Start a new paragraph and emit a marker at each interval boundary (seconds).
TIMESTAMP_INTERVAL = 300  # 5 minutes

# Soft paragraph length (characters). Once a paragraph reaches this, the next
# segment boundary starts a new paragraph, so prose forms readable chunks
# rather than one multi-minute wall of text.
_PARAGRAPH_TARGET_CHARS = 500


def format_timestamp(seconds: float) -> str:
    """Format a timestamp as [MM:SS], or [H:MM:SS] past one hour.

    Args:
        seconds: Timestamp in seconds.

    Returns:
        Bracketed timestamp string, e.g. [05:00] or [1:05:00].
    """
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"[{hours}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def _normalize(text: str) -> str:
    """Collapse internal whitespace (including newlines) to single spaces.

    YouTube caption segments often carry hard line breaks mid-phrase; these
    must become spaces so segments join into flowing prose.

    Args:
        text: Raw segment text.

    Returns:
        Whitespace-normalized text.
    """
    return re.sub(r"\s+", " ", text).strip()


def format_transcript_body(
    segments: tuple[Segment, ...],
    interval: int = TIMESTAMP_INTERVAL,
) -> str:
    """Format caption segments into flowing paragraphs with timestamp markers.

    Consecutive segments are joined into space-separated paragraphs so the
    transcript reads as prose, not a column of fragments. A new paragraph
    starts at each `interval`-second boundary (marked with a [timestamp]) and
    once a paragraph reaches a readable length. No marker at 00:00.

    Args:
        segments: Ordered caption segments.
        interval: Seconds between timestamp markers (default 5 minutes).

    Returns:
        Markdown body string with paragraphs separated by blank lines.
    """
    if not segments:
        return ""

    blocks: list[str] = []      # finished paragraphs and markers, in order
    paragraph: list[str] = []   # current paragraph's normalized fragments
    para_len = 0
    next_marker = interval

    def flush() -> None:
        """Move the current paragraph (if any) into the block list."""
        nonlocal para_len
        if paragraph:
            blocks.append(" ".join(paragraph))
            paragraph.clear()
            para_len = 0

    for segment in segments:
        # Emit any timestamp markers this segment has passed
        while segment.start_seconds >= next_marker:
            flush()
            blocks.append(format_timestamp(next_marker))
            next_marker += interval

        text = _normalize(segment.text)
        if not text:
            continue
        paragraph.append(text)
        para_len += len(text) + 1
        # Break at a natural (segment) boundary once the running paragraph is
        # long enough to read as a chunk rather than a wall.
        if para_len >= _PARAGRAPH_TARGET_CHARS:
            flush()

    flush()
    return "\n\n".join(blocks)
