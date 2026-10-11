/*
 * Builds the notice text shown after a playlist run: how many notes were saved
 * and, when some videos failed, which ones and how to retry them.
 */

import type { PlaylistSuccess } from "./cli";

// How many failed videos to name before collapsing the rest into a count.
const MAX_FAILURES_LISTED = 3;

/**
 * Describe a playlist result for the user.
 *
 * @param data The parsed playlist success payload.
 * @returns A one-line summary; when videos failed it names the first few
 *   with their error type and says that running the playlist again retries
 *   only those, because videos already saved are skipped.
 */
export function summarizePlaylist(data: PlaylistSuccess): string {
  const fresh = data.transcripts.filter((t) => !t.cached).length;
  const cached = data.count - fresh;
  const base = `Playlist: ${data.count} transcript(s) -- ${fresh} new, ${cached} already in vault`;

  const failed = data.failed ?? [];
  if (failed.length === 0) {
    return base;
  }
  const named = failed
    .slice(0, MAX_FAILURES_LISTED)
    .map((f) => `${f.title} (${f.error_type})`)
    .join(", ");
  const rest = failed.length - MAX_FAILURES_LISTED;
  const more = rest > 0 ? ` and ${rest} more` : "";
  return `${base}. ${failed.length} failed: ${named}${more}. Run it again to retry them.`;
}
