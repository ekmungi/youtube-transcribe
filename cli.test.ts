import { describe, it, expect } from "vitest";
import { parsePlaylistOutput } from "./cli";

describe("parsePlaylistOutput", () => {
  it("parses a success payload into a typed playlist result", () => {
    const line = JSON.stringify({
      count: 2,
      transcripts: [
        { path: "/v/a.md", title: "A", video_id: "a", source: "manual_captions", cached: false },
        { path: "/v/b.md", title: "B", video_id: "b", source: "auto_captions", cached: true },
      ],
    });

    const result = parsePlaylistOutput(line);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.count).toBe(2);
      expect(result.data.transcripts).toHaveLength(2);
      expect(result.data.transcripts[0].path).toBe("/v/a.md");
      expect(result.data.transcripts[1].cached).toBe(true);
    }
  });

  it("parses an error payload into a typed error", () => {
    const line = JSON.stringify({
      error: "no such playlist",
      error_type: "PlaylistNotFoundError",
    });

    const result = parsePlaylistOutput(line);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.error_type).toBe("PlaylistNotFoundError");
      expect(result.error.error).toBe("no such playlist");
    }
  });
});
