"""Tests for config loading, saving, and tolerance of obsolete keys."""

from pathlib import Path

import pytest
import yaml

from yt_transcribe import config as config_module
from yt_transcribe.config import DEFAULT_CONFIG, load_config, save_config
from yt_transcribe.models import Config

# Keys written by older versions that the current Config no longer has.
OBSOLETE_KEYS = {
    "transcription_strategy": "cloud",
    "ffmpeg_location": "C:/Users/someone/.yt-transcribe/bin",
    "whisper_model": "base",
    "async_threshold_seconds": 180,
    "parallel_enabled": False,
}


class TestLoadConfig:
    def test_load_from_file(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/my/vault",
            "transcript_folder": "YT",
        }))
        config = load_config(config_file)
        assert config.obsidian_vault_path == "/my/vault"
        assert config.transcript_folder == "YT"

    @pytest.mark.parametrize("key", sorted(OBSOLETE_KEYS))
    def test_load_ignores_each_obsolete_key(self, tmp_path: Path, key: str):
        """Live configs written by older versions still contain these keys
        (including the strategy and ffmpeg location removed with the cloud
        strategy); loading must ignore them without crashing or warning."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/my/vault",
            key: OBSOLETE_KEYS[key],
        }))
        config = load_config(config_file)
        assert config.obsidian_vault_path == "/my/vault"
        assert not hasattr(config, key)

    def test_load_missing_file_returns_defaults(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config == DEFAULT_CONFIG

    def test_load_partial_file_fills_defaults(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/custom",
        }))
        config = load_config(config_file)
        assert config.obsidian_vault_path == "/custom"
        assert config.transcript_folder == DEFAULT_CONFIG.transcript_folder

    def test_load_fixture(self):
        """The fixture carries several obsolete keys; all are ignored."""
        fixture = Path(__file__).parent.parent / "fixtures" / "sample_config.yaml"
        config = load_config(fixture)
        assert config.obsidian_vault_path == "C:/TestVault"
        assert config.transcript_folder == "Transcripts"


class TestSaveConfig:
    def test_save_and_reload(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config = Config(obsidian_vault_path="/vault", transcript_folder="T")
        save_config(config, config_file)
        reloaded = load_config(config_file)
        assert reloaded == config

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        config_file = tmp_path / "subdir" / "config.yaml"
        save_config(DEFAULT_CONFIG, config_file)
        assert config_file.exists()

    def test_save_includes_version(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        save_config(DEFAULT_CONFIG, config_file)
        raw = yaml.safe_load(config_file.read_text())
        assert raw["version"] == 1

    def test_save_writes_only_the_current_fields(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        save_config(DEFAULT_CONFIG, config_file)
        raw = yaml.safe_load(config_file.read_text())
        assert set(raw) == {"version", "obsidian_vault_path", "transcript_folder"}

    def test_save_after_loading_an_old_file_drops_obsolete_keys(self, tmp_path: Path):
        """Round-tripping an old config removes the keys that no longer exist."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/vault",
            "transcript_folder": "T",
            **OBSOLETE_KEYS,
        }))
        save_config(load_config(config_file), config_file)
        raw = yaml.safe_load(config_file.read_text())
        assert set(raw) == {"version", "obsidian_vault_path", "transcript_folder"}
        assert raw["obsidian_vault_path"] == "/vault"


class TestRemovedApiKeyHelpers:
    def test_no_assemblyai_key_lookup(self):
        """The key lookup and the keyring dependency went with the cloud strategy."""
        assert not hasattr(config_module, "get_assemblyai_api_key")
        assert not hasattr(config_module, "set_assemblyai_api_key")
