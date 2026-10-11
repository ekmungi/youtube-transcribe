"""Immutable data models for the yt-transcribe system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TranscriptSource(StrEnum):
    """Provenance of a transcript: where the text actually came from."""
    CACHE = "cache"
    MANUAL_CAPTIONS = "manual_captions"
    AUTO_CAPTIONS = "auto_captions"


@dataclass(frozen=True)
class Config:
    """Application configuration. Loaded from ~/.yt-transcribe/config.yaml."""
    obsidian_vault_path: str
    transcript_folder: str


@dataclass(frozen=True)
class VideoInfo:
    """Metadata about a single YouTube video."""
    video_id: str
    title: str
    channel: str
    url: str
    duration_seconds: int
    playlist_title: str | None


@dataclass(frozen=True)
class Segment:
    """A single timed transcript segment."""
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class Transcript:
    """Complete transcript for a video, with source provenance.

    caption_language is the BCP-47-ish language code of the caption track
    used; None when the track's language is not known.
    """
    video: VideoInfo
    text: str
    segments: tuple[Segment, ...]
    source: TranscriptSource
    caption_language: str | None = None
