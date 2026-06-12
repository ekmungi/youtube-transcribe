"""AssemblyAI cloud transcription engine using the assemblyai Python SDK.

Supports two modes: URL-based (fast, no download/upload) and file-based (fallback).
"""

from __future__ import annotations

import logging
from pathlib import Path

import assemblyai as aai
from tenacity import retry, stop_after_attempt, wait_exponential

from yt_transcribe.exceptions import TranscriptionError
from yt_transcribe.models import Segment

logger = logging.getLogger(__name__)

# Milliseconds to seconds conversion factor
_MS_TO_SEC = 1000.0


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
def _submit_transcription(
    transcriber: aai.Transcriber,
    audio_source: str,
    config: aai.TranscriptionConfig,
) -> aai.Transcript:
    """Submit audio to AssemblyAI with retry logic.

    Args:
        transcriber: Configured AssemblyAI transcriber instance.
        audio_source: Local file path or remote URL to audio.
        config: Transcription configuration.

    Returns:
        AssemblyAI Transcript result object.
    """
    return transcriber.transcribe(audio_source, config=config)


def _extract_segments(transcript: aai.Transcript) -> tuple[Segment, ...]:
    """Convert AssemblyAI transcript result into immutable Segment tuples.

    Args:
        transcript: Completed AssemblyAI transcript.

    Returns:
        Tuple of Segment dataclasses with timestamps and text.
    """
    sentences = transcript.get_sentences()
    if sentences:
        return tuple(
            Segment(
                start_seconds=s.start / _MS_TO_SEC,
                end_seconds=s.end / _MS_TO_SEC,
                text=s.text.strip(),
            )
            for s in sentences
        )

    # Fallback: single segment from full text
    if transcript.text:
        return (Segment(start_seconds=0.0, end_seconds=0.0, text=transcript.text),)

    return ()


def transcribe_url(
    audio_url: str,
    api_key: str,
) -> tuple[Segment, ...]:
    """Transcribe audio directly from a URL using AssemblyAI.

    Skips local download and upload entirely -- AssemblyAI fetches the audio
    from the URL directly. This is the fastest path for cloud transcription.

    Args:
        audio_url: Direct URL to the audio stream (e.g. from YouTube CDN).
        api_key: AssemblyAI API key for authentication.

    Returns:
        Tuple of Segment dataclasses with timestamps and text.

    Raises:
        TranscriptionError: If AssemblyAI returns an error or the SDK fails.
    """
    aai.settings.api_key = api_key

    logger.info("Submitting audio URL to AssemblyAI: %s", audio_url[:80])

    try:
        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(speech_models=["universal-2"])
        transcript = _submit_transcription(transcriber, audio_url, config)
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"AssemblyAI transcription failed: {exc}") from exc

    if transcript.status == "error" or transcript.error:
        raise TranscriptionError(
            f"AssemblyAI error: {transcript.error or 'Unknown error'}"
        )

    return _extract_segments(transcript)


def transcribe(
    audio_path: Path,
    api_key: str,
) -> tuple[Segment, ...]:
    """Transcribe a local audio file using AssemblyAI cloud service.

    Uploads the audio file to AssemblyAI, waits for completion, and converts
    the result into immutable Segment tuples. Prefer transcribe_url() when
    a direct audio URL is available to skip the upload step.

    Args:
        audio_path: Path to the audio file to transcribe.
        api_key: AssemblyAI API key for authentication.

    Returns:
        Tuple of Segment dataclasses with timestamps and text.

    Raises:
        TranscriptionError: If AssemblyAI returns an error or the SDK fails.
    """
    aai.settings.api_key = api_key

    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    logger.info("Uploading %s to AssemblyAI (%d bytes)", audio_path, audio_path.stat().st_size)

    try:
        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(speech_models=["universal-2"])
        transcript = _submit_transcription(transcriber, str(audio_path), config)
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"AssemblyAI transcription failed: {exc}") from exc

    if transcript.status == "error" or transcript.error:
        raise TranscriptionError(
            f"AssemblyAI error: {transcript.error or 'Unknown error'}"
        )

    return _extract_segments(transcript)
