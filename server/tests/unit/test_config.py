"""Tests for config loading, saving, validation, and legacy migration."""

from pathlib import Path

import pytest
import yaml

from yt_transcribe.config import (
    DEFAULT_CONFIG,
    get_assemblyai_api_key,
    load_config,
    save_config,
)
from yt_transcribe.models import Config, TranscriptionStrategy


class TestLoadConfig:
    def test_load_from_file(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/my/vault",
            "transcript_folder": "YT",
            "transcription_strategy": "cloud",
        }))
        config = load_config(config_file)
        assert config.obsidian_vault_path == "/my/vault"
        assert config.transcription_strategy == TranscriptionStrategy.CLOUD

    def test_load_ignores_obsolete_parallel_enabled_key(self, tmp_path: Path):
        """Live configs written by older versions still contain
        parallel_enabled; loading must ignore it without crashing."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/my/vault",
            "parallel_enabled": False,
        }))
        config = load_config(config_file)
        assert config.obsidian_vault_path == "/my/vault"
        assert not hasattr(config, "parallel_enabled")

    def test_load_missing_file_returns_defaults(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config == DEFAULT_CONFIG

    def test_default_strategy_is_captions(self):
        """Captions are the only default path; cloud is explicit opt-in."""
        assert DEFAULT_CONFIG.transcription_strategy == TranscriptionStrategy.CAPTIONS

    def test_load_partial_file_fills_defaults(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "obsidian_vault_path": "/custom",
        }))
        config = load_config(config_file)
        assert config.obsidian_vault_path == "/custom"
        assert config.transcription_strategy == TranscriptionStrategy.CAPTIONS

    def test_load_fixture(self):
        """Fixture has legacy keys (whisper_model, auto strategy); both handled."""
        fixture = Path(__file__).parent.parent / "fixtures" / "sample_config.yaml"
        config = load_config(fixture)
        assert config.obsidian_vault_path == "C:/TestVault"
        assert config.transcription_strategy == TranscriptionStrategy.CAPTIONS


class TestLegacyStrategyMigration:
    """Stored 'auto'/'local' values migrate to CAPTIONS at the config boundary."""

    @pytest.mark.parametrize("legacy_value", ["auto", "local"])
    def test_legacy_value_maps_to_captions(self, tmp_path: Path, legacy_value: str):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "transcription_strategy": legacy_value,
        }))
        config = load_config(config_file)
        assert config.transcription_strategy == TranscriptionStrategy.CAPTIONS

    @pytest.mark.parametrize("legacy_value", ["auto", "local"])
    def test_legacy_migration_emits_no_warning(
        self, tmp_path: Path, legacy_value: str, caplog: pytest.LogCaptureFixture,
    ):
        """Known legacy names are an expected migration, not a typo."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "transcription_strategy": legacy_value,
        }))
        with caplog.at_level("WARNING", logger="yt_transcribe.config"):
            load_config(config_file)
        assert caplog.records == []

    def test_invalid_strategy_falls_back_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        """An unrecognized strategy string (e.g. a typo like 'clouds') falls
        back to captions and logs a warning naming both the bad value and
        the fallback."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "version": 1,
            "transcription_strategy": "clouds",
        }))
        with caplog.at_level("WARNING", logger="yt_transcribe.config"):
            config = load_config(config_file)

        assert config.transcription_strategy == TranscriptionStrategy.CAPTIONS
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "clouds" in message
        assert "captions" in message

    def test_save_after_legacy_load_writes_new_value(self, tmp_path: Path):
        """Round-tripping a legacy config persists the migrated strategy."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"transcription_strategy": "local"}))
        config = load_config(config_file)
        save_config(config, config_file)
        raw = yaml.safe_load(config_file.read_text())
        assert raw["transcription_strategy"] == "captions"


class TestSaveConfig:
    def test_save_and_reload(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config = Config(
            obsidian_vault_path="/vault",
            transcript_folder="T",
            transcription_strategy=TranscriptionStrategy.CLOUD,
        )
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

    def test_save_omits_removed_fields(self, tmp_path: Path):
        """Whisper, job-queue, and parallel settings are gone; saved YAML must
        not have them."""
        config_file = tmp_path / "config.yaml"
        save_config(DEFAULT_CONFIG, config_file)
        raw = yaml.safe_load(config_file.read_text())
        assert "whisper_model" not in raw
        assert "async_threshold_seconds" not in raw
        assert "parallel_enabled" not in raw


class TestGetAssemblyaiApiKey:
    def test_from_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key-123")
        assert get_assemblyai_api_key() == "test-key-123"

    def test_returns_none_when_not_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
        # Also mock keyring to return None
        import unittest.mock
        with unittest.mock.patch("yt_transcribe.config._get_keyring_key", return_value=None):
            assert get_assemblyai_api_key() is None
