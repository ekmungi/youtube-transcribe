"""Custom exceptions for the yt-transcribe system."""


class YtTranscribeError(Exception):
    """Base exception for all yt-transcribe errors."""


class VideoNotFoundError(YtTranscribeError):
    """URL is invalid, video deleted, or does not exist."""


class VideoUnavailableError(YtTranscribeError):
    """Video is private, age-restricted, or region-blocked."""


class PlaylistNotFoundError(YtTranscribeError):
    """Playlist URL is invalid or playlist is empty."""


class DownloadError(YtTranscribeError):
    """Network failure during audio download."""


class NoCaptionsError(YtTranscribeError):
    """No captions exist for the video.

    Raised by the default captions strategy. The message tells the user
    they can retry with strategy='cloud' (AssemblyAI, requires an API key)
    if they want speech-to-text instead.
    """


class CaptionFetchError(YtTranscribeError):
    """Caption tracks exist but none could be fetched.

    Transient condition (YouTube rate limiting or network failure), distinct
    from NoCaptionsError: the right advice is to retry in a few minutes,
    never to pay for the cloud strategy.
    """


class TranscriptionError(YtTranscribeError):
    """AssemblyAI transcription failed."""
