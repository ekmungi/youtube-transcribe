"""CLI entry point built with click + rich. Thin wrapper over core library."""

from __future__ import annotations

import json as json_mod
from dataclasses import replace

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from yt_transcribe import __version__, download, search, storage, transcribe
from yt_transcribe import config as config_mod
from yt_transcribe.config import load_config
from yt_transcribe.download import extract_video_data
from yt_transcribe.exceptions import YtTranscribeError
from yt_transcribe.failures import failure_entry
from yt_transcribe.models import Config
from yt_transcribe.url_classify import extract_video_id

console = Console()

# Valid config keys and their types for `config set`
_CONFIG_KEYS: dict[str, type] = {
    "obsidian_vault_path": str,
    "transcript_folder": str,
}


def _accept_captions_only(
    ctx: click.Context, param: click.Parameter, value: str | None,
) -> str | None:
    """Accept the retired --strategy option, but only with its one remaining value.

    Plugin versions before 0.5.0 always pass ``--strategy captions``, so the
    option is kept (hidden) to stay compatible with them. The cloud strategy no
    longer exists, so asking for it is an error that says so.

    Args:
        ctx: Click context (unused).
        param: The option being parsed (unused).
        value: The value given on the command line, or None.

    Returns:
        The value unchanged when it is None or "captions".

    Raises:
        click.BadParameter: For any other value, including "cloud".
    """
    if value is not None and value != "captions":
        raise click.BadParameter(
            f"the '{value}' strategy was removed in 0.13.0; "
            "captions are the only source of text"
        )
    return value


@click.group()
@click.version_option(__version__, prog_name="yt-transcribe")
def cli() -> None:
    """YouTube transcript extractor -- yt-transcribe."""


@cli.command()
@click.argument("url")
@click.option(
    "--strategy", default=None, hidden=True, expose_value=False,
    callback=_accept_captions_only,
    help="Retired: accepted as 'captions' so older plugins keep working.",
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
@click.option(
    "--no-save", "no_save", is_flag=True,
    help="Emit the transcript TEXT as one JSON line to stdout and write NO file "
    "(for backend tooling that stores the transcript itself, e.g. Spyglass).",
)
def video(
    url: str, vault: str | None, folder: str | None, as_json: bool, no_save: bool,
) -> None:
    """Transcribe a single YouTube video."""
    if no_save:
        _video_nosave_json(url, vault, folder)
        return
    if as_json:
        _video_json(url, vault, folder)
        return

    cfg = _config_with_overrides(vault, folder)

    # Look the video up by the ID in the URL first: a repeat request is then
    # answered from the vault without any request to YouTube.
    video_id = extract_video_id(url)
    cached = _cached_payload(cfg, video_id) if video_id else None
    if cached is not None:
        console.print(
            f"[green]Already exists (cached):[/green] {escape(str(cached['title']))}"
        )
        return

    video_data = extract_video_data(url)
    video_info = video_data.video_info

    existing = storage.find_existing(cfg, video_info.video_id)
    if existing is not None:
        console.print(f"[green]Already exists (cached):[/green] {video_info.title}")
        return

    console.print(f"Transcribing: {video_info.title}...")
    result = transcribe.transcribe_video_fast(video_data)
    storage.save_transcript(cfg, result)
    console.print(f"[green]Saved:[/green] {video_info.title}")


def _config_with_overrides(
    vault: str | None = None,
    folder: str | None = None,
) -> Config:
    """Load config, applying optional per-run overrides.

    Each override is applied only when provided (not None), so the persisted
    config is the default for anything left unset.

    Args:
        vault: Vault root path override, or None to keep the configured vault.
        folder: Transcript subfolder override, or None to keep the configured one.

    Returns:
        A Config with the requested overrides applied.
    """
    cfg = load_config()
    if vault is not None:
        cfg = replace(cfg, obsidian_vault_path=vault)
    if folder is not None:
        cfg = replace(cfg, transcript_folder=folder)
    return cfg


def _cached_payload(
    cfg: Config, video_id: str, title: str | None = None,
) -> dict[str, object] | None:
    """Build the JSON result for a video that is already saved, or None.

    Args:
        cfg: Configuration naming the vault folder to search.
        video_id: YouTube video ID to look for.
        title: Title to report; defaults to the one stored in the note, then to
            the note's file name for notes saved before titles were stored.

    Returns:
        The same payload shape as a fresh transcription, with source "cache"
        and cached true, or None when the video is not in the vault.
    """
    existing = storage.find_existing(cfg, video_id)
    if existing is None:
        return None
    stored = storage.read_stored_transcript(existing)
    return {
        "path": str(existing),
        "title": title or stored.title or existing.stem,
        "video_id": video_id,
        "source": "cache",
        "original_source": stored.source,
        "caption_language": stored.caption_language,
        "cached": True,
    }


def _video_json(
    url: str,
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
        vault: Optional vault root override.
        folder: Optional transcript subfolder override.
    """
    try:
        cfg = _config_with_overrides(vault, folder)

        # Look the video up by the ID in the URL first: a repeat request is then
        # answered from the vault without any request to YouTube.
        video_id = extract_video_id(url)
        cached = _cached_payload(cfg, video_id) if video_id else None
        if cached is not None:
            _emit_json(cached)
            return

        video_data = extract_video_data(url)
        video_info = video_data.video_info

        # A link form the ID pattern does not recognise: check the vault again
        # now that YouTube has told us the ID.
        cached = _cached_payload(cfg, video_info.video_id, video_info.title)
        if cached is not None:
            _emit_json(cached)
            return

        result = transcribe.transcribe_video_fast(video_data)
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


def _video_nosave_json(
    url: str,
    vault: str | None = None,
    folder: str | None = None,
) -> None:
    """Transcribe a video and print its transcript TEXT as one JSON line -- writing no file.

    The text-to-stdout contract for backend tooling (e.g. the Spyglass service) that stores the
    transcript itself and does NOT want a vault file: no cache lookup, no save. On success the JSON
    carries title/video_id/source/caption_language/text/saved=false; on a known error it carries
    error/error_type with a non-zero exit code. Human chrome is suppressed so stdout is pure JSON.

    Args:
        url: YouTube video URL to transcribe.
        vault: Accepted for CLI parity; unused here since nothing is written.
        folder: Accepted for CLI parity; unused here since nothing is written.
    """
    try:
        video_data = extract_video_data(url)
        result = transcribe.transcribe_video_fast(video_data)
        _emit_json({
            "title": result.video.title,
            "video_id": result.video.video_id,
            "source": result.source.value,
            "caption_language": result.caption_language,
            "text": result.text,
            "saved": False,
        })
    except YtTranscribeError as exc:
        _emit_json({"error": str(exc), "error_type": type(exc).__name__})
        raise SystemExit(1) from None


def _playlist_json(
    url: str,
    vault: str | None = None,
    folder: str | None = None,
) -> None:
    """Transcribe a playlist and print one machine-readable JSON line.

    The stable contract for tooling (e.g. the Obsidian plugin): on success a
    JSON object with `count`, a `transcripts` list (one entry per saved video,
    each with path/title/video_id/source/original_source/caption_language/
    cached) and a `failed` list (video_id/title/error/error_type for each video
    that could not be transcribed; empty when none). One markdown file is
    written per video. A failing video does not stop the rest, and re-running
    the same playlist retries only the failed ones because saved videos are
    skipped. On a playlist-level error (invalid or empty playlist) a JSON
    object with error/error_type and a non-zero exit code.

    Args:
        url: YouTube playlist URL.
        vault: Optional vault root override.
        folder: Optional transcript subfolder override.
    """
    try:
        cfg = _config_with_overrides(vault, folder)
        videos = download.get_playlist_info(url)
        transcripts: list[dict[str, object]] = []
        failed: list[dict[str, str]] = []
        for vid in videos:
            existing = storage.find_existing(cfg, vid.video_id)
            if existing is not None:
                stored = storage.read_stored_transcript(existing)
                transcripts.append({
                    "path": str(existing),
                    "title": vid.title,
                    "video_id": vid.video_id,
                    "source": "cache",
                    "original_source": stored.source,
                    "caption_language": stored.caption_language,
                    "cached": True,
                })
                continue

            try:
                video_data = extract_video_data(vid.url)
                result = transcribe.transcribe_video_fast(video_data)
                saved_path = storage.save_transcript(cfg, result)
            except YtTranscribeError as exc:
                # One bad video (no captions, rate limit, private) must not
                # discard the rest of the playlist; record it and move on.
                failed.append(failure_entry(vid.video_id, vid.title, exc))
                continue
            transcripts.append({
                "path": str(saved_path),
                "title": vid.title,
                "video_id": vid.video_id,
                "source": result.source.value,
                "original_source": result.source.value,
                "caption_language": result.caption_language,
                "cached": False,
            })
        _emit_json({
            "count": len(transcripts),
            "transcripts": transcripts,
            "failed": failed,
        })
    except YtTranscribeError as exc:
        # Playlist-level failure (invalid or empty playlist): surface the
        # message and type so callers can react precisely.
        _emit_json({"error": str(exc), "error_type": type(exc).__name__})
        raise SystemExit(1) from None


@cli.command()
@click.argument("url")
@click.option(
    "--strategy", default=None, hidden=True, expose_value=False,
    callback=_accept_captions_only,
    help="Retired: accepted as 'captions' so older plugins keep working.",
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
    help="Emit a single JSON line with the per-video results (for tooling/plugins).",
)
def playlist(
    url: str, vault: str | None, folder: str | None, as_json: bool,
) -> None:
    """Transcribe all videos in a YouTube playlist (one file per video)."""
    if as_json:
        _playlist_json(url, vault, folder)
        return

    cfg = _config_with_overrides(vault, folder)
    videos = download.get_playlist_info(url)
    console.print(f"Found {len(videos)} videos in playlist")

    failed_count = 0
    for i, vid in enumerate(videos, 1):
        existing = storage.find_existing(cfg, vid.video_id)
        if existing is not None:
            console.print(f"  [{i}/{len(videos)}] {vid.title} (cached)")
            continue

        console.print(f"  [{i}/{len(videos)}] Transcribing: {vid.title}...")
        try:
            # Use optimized single-call pipeline per video
            video_data = extract_video_data(vid.url)
            result = transcribe.transcribe_video_fast(video_data)
            storage.save_transcript(cfg, result)
        except YtTranscribeError as exc:
            # One bad video must not stop the rest of the playlist.
            failed_count += 1
            console.print(
                f"  [{i}/{len(videos)}] [red]Failed:[/red] {vid.title} -- "
                f"{escape(str(exc))}"
            )
            continue
        console.print(f"  [{i}/{len(videos)}] [green]Saved:[/green] {vid.title}")

    if failed_count:
        console.print(
            f"[yellow]{failed_count} failed.[/yellow] Re-run this command to "
            "retry them; videos already saved are skipped."
        )


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
    updated = replace(cfg, **{key: value})
    config_mod.save_config(updated)
    console.print(f"[green]Set {key} = {value}[/green]")


def main() -> None:
    """Entry point for yt-transcribe CLI."""
    cli()


if __name__ == "__main__":
    main()
