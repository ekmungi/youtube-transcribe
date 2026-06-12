"""Tests for inactivity-based worker timeout in the worker runner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestInactivityTimeout:
    """Tests for the inactivity-based timeout mechanism."""

    @pytest.mark.asyncio()
    async def test_worker_killed_after_inactivity(self) -> None:
        """Worker is killed when no stderr activity for the inactivity period."""
        from yt_transcribe.worker_runner import run_worker

        progress_line = 'PROGRESS:{"stage":"downloading","status":"started"}\n'

        call_count = 0
        async def slow_readline():
            """First call returns a line, second hangs until cancelled."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return progress_line.encode()
            # Hang until cancelled by watchdog
            await asyncio.sleep(600)
            return b""

        # returncode starts as None (running), set to -9 after kill
        rc_holder = {"rc": None}

        proc = MagicMock()
        type(proc).returncode = property(lambda self: rc_holder["rc"])
        proc.pid = 99999
        def do_kill():
            rc_holder["rc"] = -9
        proc.kill = do_kill
        proc.wait = AsyncMock()
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.close = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = AsyncMock(return_value=b"")
        proc.stderr = MagicMock()
        proc.stderr.readline = slow_readline

        with (
            patch("yt_transcribe.worker_runner.asyncio.create_subprocess_exec",
                  new_callable=AsyncMock, return_value=proc),
            patch("yt_transcribe.worker_runner._INACTIVITY_TIMEOUT_SECONDS", 0.3),
            patch("yt_transcribe.worker_runner._WATCHDOG_CHECK_INTERVAL", 0.1),
            patch("yt_transcribe.worker_runner.log_to_client", new_callable=AsyncMock),
        ):
            result = await run_worker({"command": "test"})

        assert "error" in result
        assert "no activity" in result["error"].lower()

    @pytest.mark.asyncio()
    async def test_worker_survives_with_steady_progress(self) -> None:
        """Worker completes normally when producing periodic stderr output."""
        from yt_transcribe.worker_runner import run_worker

        stderr_lines = [
            'PROGRESS:{"stage":"downloading","status":"started"}\n',
            'PROGRESS:{"stage":"downloading","status":"done","elapsed":1.2}\n',
            'PROGRESS:{"stage":"transcribing","status":"started","strategy":"captions"}\n',
            'PROGRESS:{"stage":"saving","status":"started"}\n',
            'PROGRESS:{"stage":"transcribing","status":"done","elapsed":5.0}\n',
        ]
        line_iter = iter(stderr_lines)

        async def readline():
            try:
                return next(line_iter).encode()
            except StopIteration:
                return b""

        rc_holder = {"rc": None}

        proc = MagicMock()
        type(proc).returncode = property(lambda self: rc_holder["rc"])
        proc.pid = 77777
        proc.kill = MagicMock()
        proc.wait = AsyncMock(side_effect=lambda: setattr(rc_holder, "rc", 0) or None)
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.close = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = AsyncMock(
            return_value=b'{"text":"hello","source":"transcribed","title":"Test"}'
        )
        proc.stderr = MagicMock()
        proc.stderr.readline = readline

        # Set returncode to 0 after work completes (simulate normal exit)
        async def wait_and_set_rc():
            rc_holder["rc"] = 0
        proc.wait = wait_and_set_rc

        with (
            patch("yt_transcribe.worker_runner.asyncio.create_subprocess_exec",
                  new_callable=AsyncMock, return_value=proc),
            patch("yt_transcribe.worker_runner._INACTIVITY_TIMEOUT_SECONDS", 5),
            patch("yt_transcribe.worker_runner._WATCHDOG_CHECK_INTERVAL", 1),
            patch("yt_transcribe.worker_runner.log_to_client", new_callable=AsyncMock),
        ):
            result = await run_worker({"command": "test"})

        assert "error" not in result
        assert result["text"] == "hello"

    @pytest.mark.asyncio()
    async def test_timeout_error_message(self) -> None:
        """Error message says 'no activity' not just 'timed out'."""
        from yt_transcribe.worker_runner import run_worker

        async def hang_readline():
            await asyncio.sleep(600)
            return b""

        rc_holder = {"rc": None}

        proc = MagicMock()
        type(proc).returncode = property(lambda self: rc_holder["rc"])
        proc.pid = 88888
        def do_kill():
            rc_holder["rc"] = -9
        proc.kill = do_kill
        proc.wait = AsyncMock()
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.close = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = AsyncMock(return_value=b"")
        proc.stderr = MagicMock()
        proc.stderr.readline = hang_readline

        with (
            patch("yt_transcribe.worker_runner.asyncio.create_subprocess_exec",
                  new_callable=AsyncMock, return_value=proc),
            patch("yt_transcribe.worker_runner._INACTIVITY_TIMEOUT_SECONDS", 0.3),
            patch("yt_transcribe.worker_runner._WATCHDOG_CHECK_INTERVAL", 0.1),
            patch("yt_transcribe.worker_runner.log_to_client", new_callable=AsyncMock),
        ):
            result = await run_worker({"command": "test"})

        assert "error" in result
        assert "no activity" in result["error"].lower()
