/*
 * Classify a YouTube URL as a single video or a playlist.
 * Mirrors the engine's url_classify.py so the plugin can route a URL to the
 * right CLI command before running it.
 */

export type UrlKind = "video" | "playlist";

// A specific-video selector: any of these means the URL targets one video,
// even if a list= parameter is also present (the playlist is just context).
const VIDEO_SELECTOR = /(?:v=|youtu\.be\/|\/embed\/|\/v\/|\/shorts\/)[a-zA-Z0-9_-]{11}/;

/**
 * Decide whether a YouTube URL points to a single video or a playlist.
 *
 * A URL is a playlist only when it carries a `list=` parameter and has no
 * specific-video selector. A watch URL that also carries `&list=...` is
 * treated as a single video, because the user pointed at one specific video.
 *
 * @param url A YouTube URL in any common format.
 * @returns "playlist" when the URL targets a playlist with no specific video,
 *   otherwise "video".
 */
export function classifyYoutubeUrl(url: string): UrlKind {
  if (VIDEO_SELECTOR.test(url)) {
    return "video";
  }
  if (url.includes("list=")) {
    return "playlist";
  }
  return "video";
}
