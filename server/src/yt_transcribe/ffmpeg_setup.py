"""Download a static ffmpeg into ~/.yt-transcribe/bin and record it in config.

ffmpeg is only needed by the cloud (AssemblyAI) strategy to extract audio; the
default captions strategy never uses it. This module makes acquiring it a
one-command step (`yt-transcribe setup-ffmpeg`) instead of a manual install.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from yt_transcribe.config import CONFIG_DIR, load_config, save_config
from yt_transcribe.download import _imageio_ffmpeg_path
from yt_transcribe.exceptions import DownloadError

logger = logging.getLogger(__name__)

# Where the downloaded binaries live (a sibling of config.yaml).
FFMPEG_BIN_DIR = CONFIG_DIR / "bin"

# Default static-build archives per platform. Windows is the primary target;
# the gyan.dev essentials build is a stable, widely used source.
_DEFAULT_URLS = {
    "win32": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "darwin": "https://evermeet.cx/ffmpeg/getrelease/zip",
    "linux": (
        "https://johnvansickle.com/ffmpeg/releases/"
        "ffmpeg-release-amd64-static.tar.xz"
    ),
}

# Binaries to extract from the archive. ffprobe is optional but lets yt-dlp
# inspect formats; both are matched by basename anywhere inside the archive.
_WANTED = ("ffmpeg", "ffprobe")


def default_url() -> str:
    """Return the default ffmpeg download URL for the current platform.

    Returns:
        A platform-appropriate static-build archive URL.

    Raises:
        DownloadError: If the platform has no known default URL.
    """
    import sys

    url = _DEFAULT_URLS.get(sys.platform)
    if url is None:
        raise DownloadError(
            f"No default ffmpeg URL for platform '{sys.platform}'. Pass an "
            "explicit --url to setup-ffmpeg pointing at a static build."
        )
    return url


def _binary_name(stem: str) -> str:
    """Return the platform-specific executable filename for a binary stem."""
    return f"{stem}.exe" if os.name == "nt" else stem


def _download(url: str, dest: Path, on_progress: Callable[[int, int], None] | None) -> None:
    """Stream a URL to a destination file, reporting progress.

    Args:
        url: Source URL (redirects are followed).
        dest: Local file to write.
        on_progress: Optional callback receiving (bytes_done, bytes_total);
            bytes_total is 0 when the server does not send a length.

    Raises:
        DownloadError: On any network or write failure.
    """
    # A User-Agent is required by some mirrors (gyan.dev) to avoid 403s.
    request = urllib.request.Request(url, headers={"User-Agent": "yt-transcribe"})
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 - trusted URL
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            with dest.open("wb") as out:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except Exception as exc:  # urllib raises a variety of error types
        raise DownloadError(f"Failed to download ffmpeg from {url}: {exc}") from exc


def _extract_binaries(archive: Path, dest_dir: Path) -> list[Path]:
    """Extract the wanted ffmpeg binaries from a zip archive, flattened.

    Args:
        archive: Path to a downloaded .zip archive.
        dest_dir: Directory to write the extracted binaries into.

    Returns:
        Paths of the binaries that were extracted.

    Raises:
        DownloadError: If the archive is not a zip or contains no ffmpeg binary.
    """
    if not zipfile.is_zipfile(archive):
        raise DownloadError(
            f"Downloaded file is not a zip archive: {archive.name}. For non-zip "
            "platforms, install ffmpeg via your package manager instead."
        )

    wanted_names = {_binary_name(stem) for stem in _WANTED}
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            base = Path(member.filename).name
            if base in wanted_names:
                target = dest_dir / base
                with zf.open(member) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
                _make_executable(target)
                extracted.append(target)

    if not any(p.name == _binary_name("ffmpeg") for p in extracted):
        raise DownloadError(
            f"No ffmpeg binary found inside {archive.name}. The archive layout "
            "may have changed; pass a different --url."
        )
    return extracted


def _make_executable(path: Path) -> None:
    """Add the owner-execute bit on POSIX so the binary can be run."""
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def setup_ffmpeg(
    url: str | None = None,
    dest_dir: Path = FFMPEG_BIN_DIR,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Acquire ffmpeg and record its location in config.

    Prefers an already-available imageio-ffmpeg binary (from the [cloud]
    extra); otherwise downloads and extracts a static build from `url`.
    The resolved directory is written to config.ffmpeg_location so every
    interface picks it up automatically.

    Args:
        url: Archive URL; defaults to the platform's known static build.
        dest_dir: Directory to install binaries into.
        on_progress: Optional download progress callback (done, total).

    Returns:
        The directory containing the ffmpeg binary.

    Raises:
        DownloadError: If acquisition fails.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Fast path: reuse the static binary the [cloud] extra already provides.
    bundled = _imageio_ffmpeg_path()
    if bundled:
        target = dest_dir / _binary_name("ffmpeg")
        shutil.copy2(bundled, target)
        _make_executable(target)
        logger.info("Installed ffmpeg from imageio-ffmpeg into %s", dest_dir)
    else:
        resolved_url = url or default_url()
        archive = dest_dir / "ffmpeg-download.zip"
        try:
            _download(resolved_url, archive, on_progress)
            _extract_binaries(archive, dest_dir)
        finally:
            archive.unlink(missing_ok=True)
        logger.info("Downloaded and extracted ffmpeg into %s", dest_dir)

    _record_in_config(dest_dir)
    return dest_dir


def _record_in_config(ffmpeg_dir: Path) -> None:
    """Persist the ffmpeg directory to config.ffmpeg_location.

    Args:
        ffmpeg_dir: Directory containing the ffmpeg binary.
    """
    config = load_config()
    save_config(replace(config, ffmpeg_location=str(ffmpeg_dir)))
