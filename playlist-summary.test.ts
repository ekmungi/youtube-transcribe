/*
 * Tests for the playlist result notice: the unchanged all-saved message and
 * the added failure report with its retry hint.
 */

import { describe, it, expect } from "vitest";
import { parsePlaylistOutput, PlaylistSuccess } from "./cli";
import { summarizePlaylist } from "./playlist-summary";

/** Build a playlist payload with the given saved entries and failures. */
function payload(
  entries: { cached: boolean }[],
  failed?: { title: string; error_type: string }[]
): PlaylistSuccess {
  return {
    count: entries.length,
    transcripts: entries.map((e, i) => ({
      path: `/v/${i}.md`,
      title: `T${i}`,
      video_id: `id${i}`,
      source: "manual_captions",
      cached: e.cached,
    })),
    failed: failed?.map((f, i) => ({
      video_id: `bad${i}`,
      title: f.title,
      error: "boom",
      error_type: f.error_type,
    })),
  };
}

describe("summarizePlaylist", () => {
  it("keeps the original message when nothing failed", () => {
    const text = summarizePlaylist(payload([{ cached: false }, { cached: true }]));
    expect(text).toBe("Playlist: 2 transcript(s) -- 1 new, 1 already in vault");
  });

  it("treats an engine that sends no failed list as no failures", () => {
    const data = payload([{ cached: false }]);
    const older: PlaylistSuccess = { count: data.count, transcripts: data.transcripts };
    expect(summarizePlaylist(older)).not.toContain("failed");
  });

  it("names failed videos with their error type and says how to retry", () => {
    const text = summarizePlaylist(
      payload([{ cached: false }], [{ title: "Bad one", error_type: "NoCaptionsError" }])
    );
    expect(text).toContain("1 failed");
    expect(text).toContain("Bad one (NoCaptionsError)");
    expect(text).toContain("Run it again to retry");
  });

  it("lists at most three failures and counts the rest", () => {
    const failures = [1, 2, 3, 4, 5].map((n) => ({
      title: `V${n}`,
      error_type: "CaptionFetchError",
    }));
    const text = summarizePlaylist(payload([], failures));
    expect(text).toContain("5 failed");
    expect(text).toContain("V3 (CaptionFetchError)");
    expect(text).not.toContain("V4 (CaptionFetchError)");
    expect(text).toContain("and 2 more");
  });
});

describe("parsePlaylistOutput with failures", () => {
  it("passes the failed list through", () => {
    const line = JSON.stringify({
      count: 0,
      transcripts: [],
      failed: [
        { video_id: "x", title: "X", error: "no captions", error_type: "NoCaptionsError" },
      ],
    });
    const result = parsePlaylistOutput(line);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.failed?.[0].error_type).toBe("NoCaptionsError");
    }
  });
});
