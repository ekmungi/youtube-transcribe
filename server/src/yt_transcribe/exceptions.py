"""Custom exceptions for the yt-transcribe system."""


class YtTranscribeError(Exception):
    """Base exception for all yt-transcribe errors."""


class VideoNotFoundError(YtTranscribeError):
    """URL is invalid, video deleted, or does not exist."""


class VideoUnavailableError(YtTranscribeError):
    """Video is private, age-restricted, or region-blocked."""


class PlaylistNotFoundError(YtTranscribeError):
    """Playlist URL is invalid or playlist is empty."""


class NoCaptionsError(YtTranscribeError):
    """No captions exist for the video.

    Captions are the only source of text, so a video without a caption track
    cannot be transcribed.
    """


class CaptionFetchError(YtTranscribeError):
    """Caption tracks exist but none could be fetched.

    Transient condition (YouTube rate limiting or network failure), distinct
    from NoCaptionsError: the right advice is to retry in a few minutes.
    """
