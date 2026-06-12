"""Config loading, saving, and validation for ~/.yt-transcribe/config.yaml."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from yt_transcribe.models import Config, TranscriptionStrategy

logger = logging.getLogger(__name__)

# Default config file location
CONFIG_DIR = Path.home() / ".yt-transcribe"
CONFIG_PATH = CONFIG_DIR / "config.yaml"
CONFIG_VERSION = 1

# Default configuration values
DEFAULT_CONFIG = Config(
    obsidian_vault_path=str(Path.home() / "Obsidian"),
    transcript_folder="Sources/YouTube Transcripts",
    transcription_strategy=TranscriptionStrategy.CAPTIONS,
    ffmpeg_location="",
)

# Strategy values written by older versions ("auto" cascade, "local" STT)
# migrate to CAPTIONS, the only free/default path that remains.
_LEGACY_STRATEGY_VALUES = ("auto", "local")


def _parse_strategy(raw_value: object) -> TranscriptionStrategy:
    """Parse a persisted strategy value, migrating legacy names gracefully.

    Known legacy names ('auto', 'local') migrate silently; anything else
    unrecognized falls back to CAPTIONS with a warning so typos like
    'clouds' don't silently change behavior.

    Args:
        raw_value: Value read from YAML (may be a legacy or invalid string).

    Returns:
        TranscriptionStrategy; CAPTIONS for legacy or unrecognized values.
    """
    value = str(raw_value)
    if value in _LEGACY_STRATEGY_VALUES:
        return TranscriptionStrategy.CAPTIONS
    try:
        return TranscriptionStrategy(value)
    except ValueError:
        logger.warning(
            "Unknown transcription_strategy %r in config; falling back to %r",
            value,
            TranscriptionStrategy.CAPTIONS.value,
        )
        return TranscriptionStrategy.CAPTIONS


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from YAML file. Creates default config if file missing.

    Unknown or obsolete keys persisted by pre-0.7 versions (local STT model
    size, async job threshold) are ignored without error.

    Args:
        path: Config file location (defaults to ~/.yt-transcribe/config.yaml).

    Returns:
        Immutable Config with defaults filled in for missing fields.
    """
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
        return DEFAULT_CONFIG

    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}

    return Config(
        obsidian_vault_path=str(
            raw.get("obsidian_vault_path", DEFAULT_CONFIG.obsidian_vault_path)
        ),
        transcript_folder=str(
            raw.get("transcript_folder", DEFAULT_CONFIG.transcript_folder)
        ),
        transcription_strategy=_parse_strategy(
            raw.get("transcription_strategy", DEFAULT_CONFIG.transcription_strategy.value)
        ),
        ffmpeg_location=str(
            raw.get("ffmpeg_location", DEFAULT_CONFIG.ffmpeg_location)
        ),
    )


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    """Save config to YAML file, writing only current fields.

    Obsolete keys present in an older file are dropped on save.

    Args:
        config: Configuration to persist.
        path: Destination file; parent directories are created if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "version": CONFIG_VERSION,
        "obsidian_vault_path": config.obsidian_vault_path,
        "transcript_folder": config.transcript_folder,
        "transcription_strategy": config.transcription_strategy.value,
        "ffmpeg_location": config.ffmpeg_location,
    }

    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _get_keyring_key() -> str | None:
    """Attempt to retrieve AssemblyAI key from OS keyring.

    Returns:
        Stored key string, or None if keyring is unavailable or key unset.
    """
    try:
        import keyring
        return keyring.get_password("yt-transcribe", "assemblyai_api_key")
    except Exception:
        return None


def get_assemblyai_api_key() -> str | None:
    """Resolve AssemblyAI API key: env var first, then OS keyring.

    Returns:
        API key string, or None if not configured anywhere.
    """
    env_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if env_key:
        return env_key
    return _get_keyring_key()


def set_assemblyai_api_key(key: str) -> None:
    """Store AssemblyAI API key in OS keyring.

    Args:
        key: API key string to persist.
    """
    import keyring
    keyring.set_password("yt-transcribe", "assemblyai_api_key", key)
