"""Caption track selection and json3 subtitle fetching for YouTube videos.

Builds an ordered candidate list (manual before auto, original language before
translations) and fetches caption bodies through the active yt-dlp opener.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, cast

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from yt_transcribe.exceptions import CaptionFetchError
from yt_transcribe.models import Segment

logger = logging.getLogger(__name__)

# Shared 429 budget per fetch_captions call: YouTube rate limits per IP, so
# once this many candidates have exhausted their retries with 429s, further
# candidates would just 429 too and are skipped.
_MAX_RATE_LIMITED_CANDIDATES = 2


class SubtitleFetcher(Protocol):
    """Minimal interface required from a YoutubeDL instance: its urlopen opener."""

    def urlopen(self, url: str) -> Any:
        """Open a URL with yt-dlp's client headers; returns a response with read()."""
        ...


@dataclass(frozen=True)
class CaptionCandidate:
    """One caption track to try: provenance, json3 URL, and retry policy."""

    kind: str  # "manual" or "auto"
    language: str
    url: str
    allow_retry: bool  # translated tracks get one attempt: they 429 persistently


@dataclass(frozen=True)
class CaptionResult:
    """Fetched caption segments plus the provenance of the winning track."""

    segments: tuple[Segment, ...]
    kind: str
    language: str


def _json3_url(entries: list[dict[str, Any]]) -> str | None:
    """Return the URL of the json3 format entry for one caption track.

    Args:
        entries: Format entry dicts for one track (ext/url/name keys).

    Returns:
        The json3 URL string, or None when the track has no json3 format.
    """
    for entry in entries:
        if entry.get("ext") == "json3" and entry.get("url"):
            return cast(str, entry["url"])
    return None


def _is_http_429(exc: BaseException) -> bool:
    """Check whether an exception is an HTTP 429 (rate limit) error.

    Duck-typed on the status attribute so it matches yt-dlp's HTTPError
    without importing untyped yt_dlp internals.

    Args:
        exc: The exception raised by a fetch attempt.

    Returns:
        True if the exception carries HTTP status 429.
    """
    return getattr(exc, "status", None) == 429


def build_caption_candidates(info: dict[str, Any]) -> tuple[CaptionCandidate, ...]:
    """Build the ordered list of caption tracks to try for a video.

    Priority: manual English, auto English (only when the video's original
    language is English or unknown), manual original-language, auto
    original-language, any other manual track, then the auto-translated
    English track as a single-attempt last resort.

    Args:
        info: yt-dlp info dict with subtitles/automatic_captions/language keys.

    Returns:
        Candidates in fetch order; tracks without a json3 format are omitted.
    """
    manual: dict[str, list[dict[str, Any]]] = info.get("subtitles") or {}
    auto: dict[str, list[dict[str, Any]]] = info.get("automatic_captions") or {}
    language: str | None = info.get("language")

    # language None gives no evidence of a non-English original, so the auto
    # "en" track is treated as original audio rather than a flaky translation.
    english_original = language is None or language.startswith("en")

    candidates: list[CaptionCandidate] = []
    seen: set[tuple[str, str]] = set()

    def _add(
        kind: str,
        key: str,
        tracks: dict[str, list[dict[str, Any]]],
        allow_retry: bool = True,
    ) -> bool:
        """Append one candidate if unseen and a json3 URL exists.

        Args:
            kind: "manual" or "auto".
            key: Language key in the track map.
            tracks: The subtitles or automatic_captions map.
            allow_retry: Whether 429s on this track should be retried.

        Returns:
            True if a candidate was appended.
        """
        if (kind, key) in seen or key not in tracks:
            return False
        url = _json3_url(tracks[key])
        if url is None:
            return False
        seen.add((kind, key))
        candidates.append(
            CaptionCandidate(kind=kind, language=key, url=url, allow_retry=allow_retry)
        )
        return True

    # a. Manual English: exact "en" first, then regional variants (en-GB, ...)
    _add("manual", "en", manual)
    for key in sorted(k for k in manual if k.startswith("en-")):
        _add("manual", key, manual)

    # b. Auto English only when the original audio is English (or unknown).
    # For non-English videos the auto "en" track is a machine TRANSLATION and
    # is deferred to the last resort below. "en-orig" marks the untranslated
    # auto track, so it outranks the plain "en" key.
    if english_original:
        _add("auto", "en-orig", auto)
        _add("auto", "en", auto)

    # c + d. Original-language tracks, manual before auto. The "<lang>-orig"
    # auto key marks the untranslated track, so it outranks the plain key.
    if language is not None:
        manual_variants = sorted(k for k in manual if k.startswith(f"{language}-"))
        for key in (language, *manual_variants):
            _add("manual", key, manual)
        auto_variants = sorted(k for k in auto if k.startswith(f"{language}-"))
        for key in (f"{language}-orig", language, *auto_variants):
            _add("auto", key, auto)

    # e. Any other manual track: human-made captions in another language beat
    # the machine-translated English track for accuracy. First map entry wins.
    for key in manual:
        if _add("manual", key, manual):
            break

    # f. Last resort: the auto-translated English track. Known to 429
    # persistently, so it gets a single attempt without retries. Deduped when
    # it was already added as an original-English candidate above.
    _add("auto", "en", auto, allow_retry=False)

    return tuple(candidates)


def _read_url(ydl: SubtitleFetcher, url: str) -> str:
    """Fetch a URL through the ydl opener and decode the body as UTF-8.

    ydl.urlopen reuses yt-dlp's client headers and impersonation, which the
    timedtext endpoint requires; a plain HTTP client gets rejected.

    Args:
        ydl: Active YoutubeDL instance (or anything exposing urlopen).
        url: URL to fetch.

    Returns:
        Decoded response body.
    """
    return cast(str, ydl.urlopen(url).read().decode("utf-8"))


@retry(
    retry=retry_if_exception(_is_http_429),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _fetch_json3_with_retry(ydl: SubtitleFetcher, url: str) -> str:
    """Fetch a caption URL, retrying HTTP 429 up to 4 attempts (1s/2s/4s backoff).

    Args:
        ydl: Active YoutubeDL instance.
        url: json3 caption URL.

    Returns:
        Decoded response body.

    Raises:
        Exception: The last error once retries are exhausted, or immediately
            for non-429 errors.
    """
    return _read_url(ydl, url)


def _parse_json3(body: str) -> tuple[Segment, ...]:
    """Parse a json3 timedtext body into Segments.

    Args:
        body: JSON string with an events list; each caption event carries
            tStartMs, dDurationMs, and segs (utf8 text pieces).

    Returns:
        Tuple of Segments; events without segs or with empty text are skipped.

    Raises:
        ValueError: Body is not valid JSON.
    """
    data = json.loads(body)
    segments: list[Segment] = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            # Metadata-only events (window definitions etc.) carry no text
            continue
        text = "".join(seg.get("utf8", "") for seg in segs).strip()
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        segments.append(Segment(start_seconds=start, end_seconds=start + duration, text=text))
    return tuple(segments)


def fetch_captions(ydl: SubtitleFetcher, info: dict[str, Any]) -> CaptionResult | None:
    """Fetch the best available caption track for a video.

    Tries candidates in priority order; per-candidate failures fall through
    to the next candidate. Three outcomes: a CaptionResult on success, None
    when the video has no caption candidates at all (truly caption-less or
    only empty tracks), and CaptionFetchError when candidates existed but
    none could be fetched (retryable: rate limit, network, parse failure).

    A shared 429 budget caps the request storm: once
    _MAX_RATE_LIMITED_CANDIDATES candidates have exhausted their retries with
    429s, remaining candidates are skipped (the IP is throttled anyway).

    Args:
        ydl: Active YoutubeDL instance whose opener carries the right headers.
        info: yt-dlp info dict from extract_info.

    Returns:
        CaptionResult with segments and provenance, or None when no caption
        candidates exist.

    Raises:
        CaptionFetchError: Candidates existed but every fetch attempt failed.
    """
    candidates = build_caption_candidates(info)
    if not candidates:
        return None

    rate_limited_candidates = 0
    failed_candidates = 0
    for candidate in candidates:
        try:
            if candidate.allow_retry:
                body = _fetch_json3_with_retry(ydl, candidate.url)
            else:
                body = _read_url(ydl, candidate.url)
            segments = _parse_json3(body)
        except Exception as exc:
            failed_candidates += 1
            logger.warning(
                "Caption fetch failed (%s %s): %s", candidate.kind, candidate.language, exc
            )
            if _is_http_429(exc):
                rate_limited_candidates += 1
                if rate_limited_candidates >= _MAX_RATE_LIMITED_CANDIDATES:
                    logger.warning(
                        "Stopping caption fetch: %d candidates rate-limited (HTTP 429)",
                        rate_limited_candidates,
                    )
                    raise CaptionFetchError(
                        "Caption fetch aborted: YouTube rate-limited "
                        f"{rate_limited_candidates} caption tracks"
                    ) from exc
            continue
        if segments:
            return CaptionResult(
                segments=segments, kind=candidate.kind, language=candidate.language
            )
        logger.debug("Caption track empty (%s %s)", candidate.kind, candidate.language)

    # Every candidate raised: retryable fetch failure, not a caption-less
    # video. Candidates that fetched fine but were empty count as success
    # (the video effectively has no usable captions).
    if failed_candidates == len(candidates):
        raise CaptionFetchError(
            f"All {failed_candidates} caption track(s) failed to fetch"
        )
    return None
