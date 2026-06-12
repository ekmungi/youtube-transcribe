"""Tests for worker_runner progress-event formatting.

Covers the distinction between 'total' (seconds, single-video saving-done
event) and 'total' (playlist video count, per-video events) so the two are
never conflated in the displayed message.
"""

from __future__ import annotations

from yt_transcribe.worker_runner import _format_done_message


class TestFormatDoneMessage:
    """Formatting of 'done' progress events relayed to the MCP client."""

    def test_single_video_saving_done_shows_total_seconds(self) -> None:
        """The saving-done event carries 'total' (seconds, no 'index'); the
        message displays it as the total elapsed time."""
        event = {"stage": "saving", "status": "done", "elapsed": 0.1, "total": 12.5}

        message = _format_done_message(event)

        assert "Saving to vault" in message
        assert "(0.1s)" in message
        assert "[total: 12.5s]" in message
        assert message.endswith("done")

    def test_playlist_complete_shows_total_elapsed(self) -> None:
        """The playlist_complete event carries 'total_elapsed' seconds."""
        event = {
            "stage": "playlist_complete",
            "status": "done",
            "count": 3,
            "total_elapsed": 45.2,
        }

        message = _format_done_message(event)

        assert "Playlist complete" in message
        assert "[total: 45.2s]" in message

    def test_per_video_event_total_is_a_count_not_seconds(self) -> None:
        """Per-video playlist events carry 'total' as the video COUNT (paired
        with 'index'); it must render as [index/total], never as a duration."""
        event = {
            "stage": "video",
            "status": "done",
            "index": 2,
            "total": 5,
            "title": "Lecture 2",
            "elapsed": 3.0,
        }

        message = _format_done_message(event)

        assert "[2/5]" in message
        assert "Lecture 2" in message
        assert "(3.0s)" in message
        assert "[total:" not in message

    def test_cached_video_event_is_marked(self) -> None:
        """Cache-sourced per-video events get a [cached] marker."""
        event = {
            "stage": "video",
            "status": "done",
            "index": 1,
            "total": 2,
            "title": "Old Video",
            "source": "cache",
        }

        message = _format_done_message(event)

        assert "[cached]" in message
        assert "[total:" not in message
