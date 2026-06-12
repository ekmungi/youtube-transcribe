"""CLI entry point built with click + rich. Thin wrapper over core library."""

from __future__ import annotations

import json as json_mod
from dataclasses import replace

import click
from rich.console import Console
from rich.table import Table

from yt_transcribe import config as config_mod
from yt_transcribe import download, search, storage, transcribe
from yt_transcribe.config import load_config
from yt_transcribe.download import extract_video_data
from yt_transcribe.exceptions import YtTranscribeError
from yt_transcribe.models import Config, TranscriptionStrategy

console = Console()

# Valid config keys and their types for `config set`
_CONFIG_KEYS: dict[str, type] = {
    "obsidian_vault_path": str,
    "transcript_folder": str,
    "transcription_strategy": str,
}


@click.group()
def cli() -> None:
    """YouTube transcript extractor -- yt-transcribe."""


@cli.command()
@click.argument("url")
@click.option(
    "--strategy", type=click.Choice(["captions", "cloud"]), default=None,
    help="Override the configured strategy for this run.",
)
@click.option(
    "--vault", default=None,
    help="Override the Obsidian vault root for this run.",
)
@click.option(
    "--folder", default=None,
    help="Override the transcript subfolder (relative to the vault) for this run.",
)
@click.option(
    "--json", "as_json", is_flag=True,
    help="Emit a single JSON line with the result (for tooling/plugins).",
)
def video(
    url: str, strategy: str | None, vault: str | None,
    folder: str | None, as_json: bool,
) -> None:
    """Transcribe a single YouTube video."""
    if as_json:
        _video_json(url, strategy, vault, folder)
        return

    cfg = _config_with_overrides(strategy, vault, folder)
    video_data = extract_video_data(url)
    video_info = video_data.video_info

    existing = storage.find_existing(cfg, video_info.video_id)
    if existing is not None:
        console.print(f"[green]Already exists (cached):[/green] {video_info.title}")
        return

    console.print(f"Transcribing: {video_info.title}...")
    result = transcribe.transcribe_video_fast(video_data, cfg)
    storage.save_transcript(cfg, result)
    console.print(f"[green]Saved:[/green] {video_info.title}")


def _config_with_overrides(
    strategy: str | None,
    vault: str | None = None,
    folder: str | None = None,
) -> Config:
    """Load config, applying optional per-run overrides.

    Each override is applied only when provided (not None), so the persisted
    config is the default for anything left unset.

    Args:
        strategy: 'captions'/'cloud', or None to keep the configured strategy.
        vault: Vault root path override, or None to keep the configured vault.
        folder: Transcript subfolder override, or None to keep the configured one.

    Returns:
        A Config with the requested overrides applied.
    """
    cfg = load_config()
    if strategy is not None:
        cfg = replace(cfg, transcription_strategy=TranscriptionStrategy(strategy))
    if vault is not None:
        cfg = replace(cfg, obsidian_vault_path=vault)
    if folder is not None:
        cfg = replace(cfg, transcript_folder=folder)
    return cfg


def _video_json(
    url: str,
    strategy: str | None = None,
    vault: str | None = None,
    folder: str | None = None,
) -> None:
    """Transcribe a video and print one machine-readable JSON line to stdout.

    The stable contract for tooling (e.g. the Obsidian plugin): on success a
    JSON object with path/title/source/caption_language/cached; on a known
    error a JSON object with error/error_type and a non-zero exit code. All
    human-facing chrome is suppressed so stdout carries only the JSON.

    Args:
        url: YouTube video URL to transcribe.
        strategy: Optional per-run strategy override ('captions' or 'cloud').
        vault: Optional vault root override.
        folder: Optional transcript subfolder override.
    """
    try:
        cfg = _config_with_overrides(strategy, vault, folder)
        video_data = extract_video_data(url)
        video_info = video_data.video_info

        existing = storage.find_existing(cfg, video_info.video_id)
        if existing is not None:
            stored = storage.read_stored_transcript(existing)
            _emit_json({
                "path": str(existing),
                "title": video_info.title,
                "video_id": video_info.video_id,
                "source": "cache",
                "original_source": stored.source,
                "caption_language": stored.caption_language,
                "cached": True,
            })
            return

        result = transcribe.transcribe_video_fast(video_data, cfg)
        saved_path = storage.save_transcript(cfg, result)
        _emit_json({
            "path": str(saved_path),
            "title": video_info.title,
            "video_id": video_info.video_id,
            "source": result.source.value,
            "original_source": result.source.value,
            "caption_language": result.caption_language,
            "cached": False,
        })
    except YtTranscribeError as exc:
        # Known, user-actionable failures (no captions, rate limit, etc.):
        # surface the message and type so callers can react precisely.
        _emit_json({"error": str(exc), "error_type": type(exc).__name__})
        raise SystemExit(1) from None


def _emit_json(payload: dict[str, object]) -> None:
    """Write a single compact JSON line to stdout.

    Uses click.echo (not rich) so the output is never wrapped or styled when
    stdout is piped -- the single-line JSON contract must survive a non-TTY.

    Args:
        payload: JSON-serializable result or error object.
    """
    click.echo(json_mod.dumps(payload))


@cli.command()
@click.argument("url")
def playlist(url: str) -> None:
    """Transcribe all videos in a YouTube playlist."""
    cfg = load_config()
    videos = download.get_playlist_info(url)
    console.print(f"Found {len(videos)} videos in playlist")

    for i, vid in enumerate(videos, 1):
        existing = storage.find_existing(cfg, vid.video_id)
        if existing is not None:
            console.print(f"  [{i}/{len(videos)}] {vid.title} (cached)")
            continue

        console.print(f"  [{i}/{len(videos)}] Transcribing: {vid.title}...")
        # Use optimized single-call pipeline per video
        video_data = extract_video_data(vid.url)
        result = transcribe.transcribe_video_fast(video_data, cfg)
        storage.save_transcript(cfg, result)
        console.print(f"  [{i}/{len(videos)}] [green]Saved:[/green] {vid.title}")


@cli.command("setup-ffmpeg")
@click.option("--url", default=None, help="Override the ffmpeg download URL.")
@click.option(
    "--json", "as_json", is_flag=True,
    help="Emit a single JSON line with the result (for tooling/plugins).",
)
def setup_ffmpeg_cmd(url: str | None, as_json: bool) -> None:
    """Download ffmpeg into ~/.yt-transcribe/bin for the cloud strategy."""
    from yt_transcribe import ffmpeg_setup

    if as_json:
        try:
            path = ffmpeg_setup.setup_ffmpeg(url=url)
            _emit_json({"path": str(path), "configured": True})
        except YtTranscribeError as exc:
            _emit_json({"error": str(exc), "error_type": type(exc).__name__})
            raise SystemExit(1) from None
        return

    def _show(done: int, total: int) -> None:
        """Print a coarse download progress line."""
        if total:
            console.print(f"  downloading ffmpeg... {done * 100 // total}%", end="\r")

    console.print("Setting up ffmpeg...")
    try:
        path = ffmpeg_setup.setup_ffmpeg(url=url, on_progress=_show)
    except YtTranscribeError as exc:
        console.print(f"[red]ffmpeg setup failed:[/red] {exc}")
        raise SystemExit(1) from None
    console.print(f"[green]ffmpeg ready:[/green] {path} (saved to config)")


@cli.command("list")
@click.option("--folder", default=None, help="Filter by subfolder name")
def list_cmd(folder: str | None) -> None:
    """List saved transcripts in the Obsidian vault."""
    cfg = load_config()
    entries = search.list_transcripts(cfg, folder=folder)

    if not entries:
        console.print("No transcripts found.")
        return

    table = Table(title="Saved Transcripts")
    table.add_column("Title", style="cyan")
    table.add_column("Channel")
    table.add_column("ID", style="dim")
    for entry in entries:
        table.add_row(entry.title, entry.channel, entry.video_id)
    console.print(table)


@cli.command("search")
@click.argument("query")
def search_cmd(query: str) -> None:
    """Search across saved transcripts."""
    cfg = load_config()
    matches = search.search_transcripts(cfg, query)

    if not matches:
        console.print("No matches found.")
        return

    for match in matches:
        console.print(f"[cyan]{match.title}[/cyan]")
        console.print(f"  {match.snippet}")
        console.print()


@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show or update configuration."""
    if ctx.invoked_subcommand is not None:
        return

    cfg = load_config()
    table = Table(title="Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("obsidian_vault_path", cfg.obsidian_vault_path)
    table.add_row("transcript_folder", cfg.transcript_folder)
    table.add_row("transcription_strategy", cfg.transcription_strategy.value)
    console.print(table)


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value. Usage: config set <key> <value>."""
    if key not in _CONFIG_KEYS:
        console.print(f"[red]Unknown config key:[/red] {key}")
        raise SystemExit(1)

    cfg = load_config()

    # Convert value to the correct type for the given key
    new_val: str | TranscriptionStrategy
    if key == "transcription_strategy":
        try:
            new_val = TranscriptionStrategy(value)
        except ValueError:
            valid = ", ".join(s.value for s in TranscriptionStrategy)
            console.print(f"[red]Invalid strategy:[/red] {value} (valid: {valid})")
            raise SystemExit(1) from None
    else:
        new_val = value

    updated = replace(cfg, **{key: new_val})  # type: ignore[arg-type]
    config_mod.save_config(updated)
    console.print(f"[green]Set {key} = {value}[/green]")


def main() -> None:
    """Entry point for yt-transcribe CLI."""
    cli()


if __name__ == "__main__":
    main()
