"""Tests for caption candidate selection and json3 fetching. No network access."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from yt_transcribe import captions as captions_mod
from yt_transcribe.captions import (
    CaptionResult,
    _is_http_429,
    _json3_url,
    _parse_json3,
    build_caption_candidates,
    fetch_captions,
)
from yt_transcribe.exceptions import CaptionFetchError
from yt_transcribe.models import Segment


class FakeHTTP429Error(Exception):
    """Stand-in for yt-dlp's HTTPError carrying a 429 status."""
    status = 429


class FakeHTTP404Error(Exception):
    """Stand-in for yt-dlp's HTTPError carrying a 404 status."""
    status = 404


def _fmt(url: str) -> list[dict[str, str]]:
    """Build a realistic yt-dlp subtitle format list: json3 plus a vtt sibling."""
    return [
        {"ext": "json3", "url": url, "name": "track"},
        {"ext": "vtt", "url": url + "&fmt=vtt", "name": "track"},
    ]


def _event(start_ms: int, dur_ms: int, text: str) -> dict[str, Any]:
    """Build a single json3 event dict with one utf8 segment."""
    return {"tStartMs": start_ms, "dDurationMs": dur_ms, "segs": [{"utf8": text}]}


def _json3_body(events: list[dict[str, Any]]) -> str:
    """Serialize events into a json3 response body."""
    return json.dumps({"events": events})


def _response(body: str) -> MagicMock:
    """Build a mock urlopen response whose read() returns the body bytes."""
    resp = MagicMock()
    resp.read.return_value = body.encode("utf-8")
    return resp


def _mock_ydl(side_effect: list[Any] | None = None, body: str | None = None) -> MagicMock:
    """Build a mock YoutubeDL exposing only urlopen, as fetch_captions requires."""
    ydl = MagicMock()
    if side_effect is not None:
        ydl.urlopen.side_effect = side_effect
    elif body is not None:
        ydl.urlopen.return_value = _response(body)
    return ydl


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable tenacity backoff sleeps so retry tests run instantly."""
    monkeypatch.setattr(captions_mod._fetch_json3_with_retry.retry, "sleep", lambda _: None)


# -- _json3_url --

class TestJson3Url:
    def test_returns_json3_url_from_mixed_formats(self) -> None:
        """Picks the json3 entry's url out of a mixed-format list."""
        assert _json3_url(_fmt("https://yt.test/t?lang=en")) == "https://yt.test/t?lang=en"

    def test_returns_none_when_no_json3(self) -> None:
        """Returns None when only non-json3 formats exist."""
        assert _json3_url([{"ext": "vtt", "url": "https://yt.test/v"}]) is None

    def test_returns_none_for_empty_list(self) -> None:
        """Returns None for an empty format list."""
        assert _json3_url([]) is None


# -- _is_http_429 --

class TestIsHttp429:
    def test_true_for_status_429(self) -> None:
        """Exceptions carrying status 429 are retryable."""
        assert _is_http_429(FakeHTTP429Error()) is True

    def test_false_for_other_status(self) -> None:
        """Other HTTP statuses are not retryable."""
        assert _is_http_429(FakeHTTP404Error()) is False

    def test_false_for_plain_exception(self) -> None:
        """Exceptions without a status attribute are not retryable."""
        assert _is_http_429(ValueError("boom")) is False


# -- _parse_json3 --

class TestParseJson3:
    def test_maps_timestamps_and_text(self) -> None:
        """tStartMs/dDurationMs map to start/end seconds, utf8 segs to text."""
        body = _json3_body([_event(1000, 2000, "Hello"), _event(3000, 1500, "World")])
        result = _parse_json3(body)
        assert result == (
            Segment(start_seconds=1.0, end_seconds=3.0, text="Hello"),
            Segment(start_seconds=3.0, end_seconds=4.5, text="World"),
        )

    def test_skips_events_without_segs(self) -> None:
        """Events lacking a segs key (metadata events) are skipped."""
        body = _json3_body([
            {"tStartMs": 0, "dDurationMs": 1000},
            _event(1000, 1000, "Kept"),
        ])
        result = _parse_json3(body)
        assert len(result) == 1
        assert result[0].text == "Kept"

    def test_joins_multiple_segs(self) -> None:
        """Multiple utf8 segments within one event are concatenated."""
        body = json.dumps({
            "events": [
                {
                    "tStartMs": 0,
                    "dDurationMs": 1000,
                    "segs": [{"utf8": "Hello "}, {"utf8": "world"}],
                }
            ]
        })
        result = _parse_json3(body)
        assert result[0].text == "Hello world"

    def test_skips_whitespace_only_events(self) -> None:
        """Events whose joined text is whitespace (e.g. newline fillers) are skipped."""
        body = _json3_body([_event(0, 1000, "\n"), _event(1000, 1000, "Real")])
        result = _parse_json3(body)
        assert len(result) == 1
        assert result[0].text == "Real"


# -- build_caption_candidates --

class TestBuildCaptionCandidates:
    def test_empty_maps_yield_no_candidates(self) -> None:
        """No subtitles and no automatic captions produce an empty tuple."""
        info = {"subtitles": {}, "automatic_captions": {}, "language": "en"}
        assert build_caption_candidates(info) == ()

    def test_manual_en_preferred_over_auto_en(self) -> None:
        """For an English video, manual en outranks the auto en track."""
        info = {
            "language": "en",
            "subtitles": {"en": _fmt("https://yt.test/manual-en")},
            "automatic_captions": {"en": _fmt("https://yt.test/auto-en")},
        }
        candidates = build_caption_candidates(info)
        assert [(c.kind, c.language) for c in candidates] == [("manual", "en"), ("auto", "en")]

    def test_auto_en_orig_preferred_when_language_none(self) -> None:
        """When language is unknown, the en-orig auto key outranks plain auto en."""
        info = {
            "language": None,
            "subtitles": {},
            "automatic_captions": {
                "en": _fmt("https://yt.test/auto-en"),
                "en-orig": _fmt("https://yt.test/auto-en-orig"),
            },
        }
        candidates = build_caption_candidates(info)
        assert candidates[0].language == "en-orig"
        assert candidates[0].kind == "auto"
        # Unknown language: auto en is treated as original, so retries are allowed
        assert all(c.allow_retry for c in candidates)

    def test_foreign_video_prefers_original_language(self) -> None:
        """Korean video: manual ko, then auto ko, then translated en as no-retry last resort."""
        info = {
            "language": "ko",
            "subtitles": {"ko": _fmt("https://yt.test/manual-ko")},
            "automatic_captions": {
                "ko": _fmt("https://yt.test/auto-ko"),
                "en": _fmt("https://yt.test/auto-en-translated"),
                "fr": _fmt("https://yt.test/auto-fr-translated"),
            },
        }
        candidates = build_caption_candidates(info)
        assert [(c.kind, c.language) for c in candidates] == [
            ("manual", "ko"),
            ("auto", "ko"),
            ("auto", "en"),
        ]
        # Translated en tracks 429 persistently: one attempt only, no retries
        assert candidates[-1].allow_retry is False
        assert candidates[0].allow_retry is True

    def test_skips_tracks_without_json3(self) -> None:
        """A candidate with no json3 format entry is dropped entirely."""
        info = {
            "language": "en",
            "subtitles": {"en": [{"ext": "vtt", "url": "https://yt.test/vtt-only"}]},
            "automatic_captions": {"en": _fmt("https://yt.test/auto-en")},
        }
        candidates = build_caption_candidates(info)
        assert [(c.kind, c.language) for c in candidates] == [("auto", "en")]

    def test_other_manual_track_used_before_translated_en(self) -> None:
        """With no en or original-language tracks, the first other manual track ranks
        ahead of the translated auto en."""
        info = {
            "language": "ko",
            "subtitles": {"fr": _fmt("https://yt.test/manual-fr")},
            "automatic_captions": {"en": _fmt("https://yt.test/auto-en-translated")},
        }
        candidates = build_caption_candidates(info)
        assert [(c.kind, c.language) for c in candidates] == [("manual", "fr"), ("auto", "en")]

    def test_auto_orig_variant_preferred_for_original_language(self) -> None:
        """An auto '<lang>-orig' key outranks the plain '<lang>' auto key."""
        info = {
            "language": "ko",
            "subtitles": {},
            "automatic_captions": {
                "ko": _fmt("https://yt.test/auto-ko"),
                "ko-orig": _fmt("https://yt.test/auto-ko-orig"),
            },
        }
        candidates = build_caption_candidates(info)
        assert candidates[0].language == "ko-orig"

    def test_manual_en_variant_matches(self) -> None:
        """A manual en-GB track qualifies for the top manual-English slot."""
        info = {
            "language": "ko",
            "subtitles": {"en-GB": _fmt("https://yt.test/manual-en-gb")},
            "automatic_captions": {},
        }
        candidates = build_caption_candidates(info)
        assert [(c.kind, c.language) for c in candidates] == [("manual", "en-GB")]


# -- fetch_captions --

INFO_EN_MANUAL = {
    "language": "en",
    "subtitles": {"en": _fmt("https://yt.test/manual-en")},
    "automatic_captions": {},
}


class TestFetchCaptions:
    def test_regression_url_only_entries_fetched(self) -> None:
        """Regression: real yt-dlp entries carry url but never data; captions must be
        fetched from the url via the ydl opener. This is the bug that made the captions
        tier dead code."""
        body = _json3_body([_event(0, 5000, "Hello world"), _event(5000, 3000, "Second line")])
        ydl = _mock_ydl(body=body)

        result = fetch_captions(ydl, INFO_EN_MANUAL)

        assert isinstance(result, CaptionResult)
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world"
        ydl.urlopen.assert_called_once_with("https://yt.test/manual-en")

    def test_returns_provenance(self) -> None:
        """The result reports which kind and language produced the captions."""
        body = _json3_body([_event(0, 1000, "Hi")])
        result = fetch_captions(_mock_ydl(body=body), INFO_EN_MANUAL)
        assert result is not None
        assert result.kind == "manual"
        assert result.language == "en"

    def test_retries_on_429_then_succeeds(self) -> None:
        """A transient 429 is retried with backoff and the second attempt succeeds."""
        body = _json3_body([_event(0, 1000, "Recovered")])
        ydl = _mock_ydl(side_effect=[FakeHTTP429Error(), _response(body)])

        result = fetch_captions(ydl, INFO_EN_MANUAL)

        assert result is not None
        assert result.segments[0].text == "Recovered"
        assert ydl.urlopen.call_count == 2

    def test_non_429_falls_through_to_next_candidate(self) -> None:
        """A non-429 failure is not retried; the next candidate is fetched instead."""
        info = {
            "language": "ko",
            "subtitles": {"en": _fmt("https://yt.test/manual-en")},
            "automatic_captions": {"ko": _fmt("https://yt.test/auto-ko")},
        }
        body = _json3_body([_event(0, 1000, "Korean track")])
        ydl = _mock_ydl(side_effect=[FakeHTTP404Error(), _response(body)])

        result = fetch_captions(ydl, info)

        assert result is not None
        assert result.kind == "auto"
        assert result.language == "ko"
        assert ydl.urlopen.call_count == 2

    def test_429_exhausts_retries_then_falls_through(self) -> None:
        """Persistent 429s on one candidate exhaust 4 attempts, then the next
        candidate is used rather than raising."""
        info = {
            "language": "ko",
            "subtitles": {"en": _fmt("https://yt.test/manual-en")},
            "automatic_captions": {"ko": _fmt("https://yt.test/auto-ko")},
        }
        body = _json3_body([_event(0, 1000, "Fallback")])
        ydl = _mock_ydl(
            side_effect=[*(FakeHTTP429Error() for _ in range(4)), _response(body)]
        )

        result = fetch_captions(ydl, info)

        assert result is not None
        assert result.language == "ko"
        # 4 attempts for the manual en candidate, 1 for the auto ko fallback
        assert ydl.urlopen.call_count == 5

    def test_translated_en_single_attempt_only(self) -> None:
        """The translated auto en last resort gets exactly one fetch attempt: it is
        known to 429 persistently, so retrying just burns time and quota. With the
        only candidate failed, the outcome is a fetch error, not caption-less."""
        info = {
            "language": "ko",
            "subtitles": {},
            "automatic_captions": {"en": _fmt("https://yt.test/auto-en-translated")},
        }
        ydl = _mock_ydl(side_effect=[FakeHTTP429Error()])

        with pytest.raises(CaptionFetchError):
            fetch_captions(ydl, info)

        assert ydl.urlopen.call_count == 1

    def test_raises_fetch_error_when_all_candidates_fail(self) -> None:
        """Candidates existed but every fetch failed: that is a retryable fetch
        error, distinct from a truly caption-less video."""
        ydl = _mock_ydl(side_effect=FakeHTTP404Error())
        with pytest.raises(CaptionFetchError):
            fetch_captions(ydl, INFO_EN_MANUAL)

    def test_returns_none_for_empty_caption_maps(self) -> None:
        """No caption tracks at all yields None without any fetch."""
        ydl = _mock_ydl()
        info = {"language": "en", "subtitles": {}, "automatic_captions": {}}
        assert fetch_captions(ydl, info) is None
        ydl.urlopen.assert_not_called()

    def test_returns_none_when_all_tracks_fetch_but_are_empty(self) -> None:
        """Tracks that fetch fine but contain no text mean the video is
        effectively caption-less: None, not a fetch error."""
        empty_body = _json3_body([])
        ydl = _mock_ydl(side_effect=[_response(empty_body), _response(empty_body)])
        info = {
            "language": "en",
            "subtitles": {"en": _fmt("https://yt.test/manual-en")},
            "automatic_captions": {"en": _fmt("https://yt.test/auto-en")},
        }
        assert fetch_captions(ydl, info) is None

    def test_unparseable_body_falls_through(self) -> None:
        """A candidate returning garbage JSON is skipped in favor of the next one."""
        info = {
            "language": "en",
            "subtitles": {"en": _fmt("https://yt.test/manual-en")},
            "automatic_captions": {"en": _fmt("https://yt.test/auto-en")},
        }
        body = _json3_body([_event(0, 1000, "Good track")])
        ydl = _mock_ydl(side_effect=[_response("not json"), _response(body)])

        result = fetch_captions(ydl, info)

        assert result is not None
        assert result.kind == "auto"


class TestRateLimitBudget:
    """A shared 429 budget across candidates caps the per-call request storm."""

    # Three retryable candidates: manual en, manual ko, auto ko (no auto en key,
    # so no translated last resort gets appended).
    INFO_THREE_CANDIDATES = {
        "language": "ko",
        "subtitles": {
            "en": _fmt("https://yt.test/manual-en"),
            "ko": _fmt("https://yt.test/manual-ko"),
        },
        "automatic_captions": {"ko": _fmt("https://yt.test/auto-ko")},
    }

    def test_two_rate_limited_candidates_stop_the_run(self) -> None:
        """After two candidates exhaust their retries with 429s, further
        candidates are skipped: a throttled IP will 429 them too."""
        ydl = _mock_ydl(
            side_effect=[FakeHTTP429Error() for _ in range(8)]
        )

        with pytest.raises(CaptionFetchError):
            fetch_captions(ydl, self.INFO_THREE_CANDIDATES)

        # 4 attempts each for the first two candidates; the third is never tried
        assert ydl.urlopen.call_count == 8

    def test_non_429_failures_do_not_trigger_budget(self) -> None:
        """Non-rate-limit failures keep falling through to every candidate."""
        ydl = _mock_ydl(side_effect=FakeHTTP404Error())

        with pytest.raises(CaptionFetchError):
            fetch_captions(ydl, self.INFO_THREE_CANDIDATES)

        # One (unretried) attempt per candidate; all three are tried
        assert ydl.urlopen.call_count == 3

    def test_one_rate_limited_candidate_still_falls_through(self) -> None:
        """A single 429-exhausted candidate is under budget; the next candidate
        is still tried and can succeed."""
        body = _json3_body([_event(0, 1000, "Recovered on ko")])
        ydl = _mock_ydl(
            side_effect=[*(FakeHTTP429Error() for _ in range(4)), _response(body)]
        )

        result = fetch_captions(ydl, self.INFO_THREE_CANDIDATES)

        assert result is not None
        assert result.language == "ko"
        assert ydl.urlopen.call_count == 5
