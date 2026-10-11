"""Config loading, saving, and validation for ~/.yt-transcribe/config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from yt_transcribe.models import Config

# Default config file location
CONFIG_DIR = Path.home() / ".yt-transcribe"
CONFIG_PATH = CONFIG_DIR / "config.yaml"
CONFIG_VERSION = 1

# Default configuration values
DEFAULT_CONFIG = Config(
    obsidian_vault_path=str(Path.home() / "Obsidian"),
    transcript_folder="Sources/YouTube Transcripts",
)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from YAML file. Creates default config if file missing.

    Unknown or obsolete keys persisted by older versions are ignored without
    error: the transcription strategy and ffmpeg location (removed with the
    cloud strategy), the local STT model size and the async job threshold.

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
    }

    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
