"""yt-transcribe: captions-first YouTube transcript extractor (CLI + MCP server)."""

from importlib.metadata import PackageNotFoundError, version

# Reported when the package metadata is missing (e.g. running from a bare
# source tree); keeps imports working instead of crashing on a lookup.
_UNKNOWN_VERSION = "0.0.0+unknown"


def _resolve_version() -> str:
    """Read the installed package version from its metadata.

    pyproject.toml is the single place the version is edited; installers write
    it into the package metadata, so reading it back here cannot drift.

    Returns:
        The installed version string, or a placeholder if not installed.
    """
    try:
        return version("yt-transcribe")
    except PackageNotFoundError:
        return _UNKNOWN_VERSION


__version__ = _resolve_version()
