"""Tests for transcript body formatting (flowing paragraphs + timestamps)."""

from __future__ import annotations

from yt_transcribe.formatting import (
    _PARAGRAPH_TARGET_CHARS,
    format_timestamp,
    format_transcript_body,
)
from yt_transcribe.models import Segment


class TestFormatTimestamp:
    """Timestamp markers render as [MM:SS] or [H:MM:SS]."""

    def test_under_one_hour_is_mmss(self):
        assert format_timestamp(300) == "[05:00]"
        assert format_timestamp(65) == "[01:05]"

    def test_past_one_hour_includes_hours(self):
        assert format_timestamp(3900) == "[1:05:00]"


class TestFlowingParagraphs:
    """Segments join into prose, not a column of one-line fragments."""

    def test_consecutive_segments_join_on_one_line(self):
        """The core regression: short segments must not each get their own
        line (which rendered as a single tall column)."""
        segments = (
            Segment(0.0, 2.0, "First fragment."),
            Segment(2.0, 4.0, "Second fragment."),
            Segment(4.0, 6.0, "Third fragment."),
        )
        body = format_transcript_body(segments)
        # All three flow into one paragraph -- no newlines separating them.
        assert body == "First fragment. Second fragment. Third fragment."
        assert "\n" not in body

    def test_internal_newlines_become_spaces(self):
        """Hard line breaks inside a caption segment are normalized to spaces."""
        segments = (Segment(0.0, 5.0, "in front of the\nelephants"),)
        body = format_transcript_body(segments)
        assert body == "in front of the elephants"

    def test_empty_segments_returns_empty_string(self):
        assert format_transcript_body(()) == ""

    def test_blank_segment_text_is_skipped(self):
        segments = (
            Segment(0.0, 1.0, "Hello"),
            Segment(1.0, 2.0, "   "),
            Segment(2.0, 3.0, "world"),
        )
        assert format_transcript_body(segments) == "Hello world"


class TestTimestampMarkers:
    """Timestamp markers start new paragraphs at interval boundaries."""

    def test_marker_starts_a_new_paragraph(self):
        segments = (
            Segment(0.0, 60.0, "Before the mark."),
            Segment(300.0, 360.0, "After the mark."),
        )
        body = format_transcript_body(segments)
        assert body == "Before the mark.\n\n[05:00]\n\nAfter the mark."

    def test_no_marker_at_zero(self):
        segments = (Segment(0.0, 10.0, "Opening line."),)
        body = format_transcript_body(segments)
        assert "[00:00]" not in body
        assert body == "Opening line."

    def test_multiple_intervals(self):
        segments = (
            Segment(0.0, 60.0, "Section one."),
            Segment(300.0, 360.0, "Section two."),
            Segment(600.0, 660.0, "Section three."),
        )
        body = format_transcript_body(segments)
        assert "[05:00]" in body
        assert "[10:00]" in body
        # Each marker is on its own block, surrounded by blank lines.
        assert "\n\n[05:00]\n\n" in body


class TestParagraphChunking:
    """Long runs break into multiple paragraphs for readability."""

    def test_long_run_splits_into_paragraphs(self):
        """A long sequence of sentences within one timestamp window is broken
        into multiple paragraphs rather than one wall of text."""
        sentence = "This is a reasonably long sentence used for testing. "
        segments = tuple(
            Segment(float(i), float(i) + 1, sentence) for i in range(30)
        )
        body = format_transcript_body(segments)
        paragraphs = body.split("\n\n")
        # 30 * ~53 chars well exceeds the target, so it must split.
        assert len(paragraphs) > 1
        # Each paragraph should be near the soft target, not a single wall.
        assert all(
            len(p) <= _PARAGRAPH_TARGET_CHARS + len(sentence) for p in paragraphs
        )
