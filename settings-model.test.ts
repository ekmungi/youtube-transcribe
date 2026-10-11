/*
 * Tests for reading saved plugin settings. Older versions also saved a default
 * strategy; it must be dropped, and missing values must fall back to defaults.
 */

import { describe, it, expect } from "vitest";
import { DEFAULT_SETTINGS, mergeSettings } from "./settings-model";

describe("mergeSettings", () => {
  it("returns the defaults when nothing was saved", () => {
    expect(mergeSettings(null)).toEqual(DEFAULT_SETTINGS);
  });

  it("keeps the values that were saved", () => {
    const merged = mergeSettings({
      executablePath: "C:/tools/yt-transcribe.exe",
      openAfterTranscribe: false,
      transcriptFolder: "03 RESOURCES/Youtube Transcriptions",
    });
    expect(merged.executablePath).toBe("C:/tools/yt-transcribe.exe");
    expect(merged.openAfterTranscribe).toBe(false);
    expect(merged.transcriptFolder).toBe("03 RESOURCES/Youtube Transcriptions");
  });

  it("fills in whatever is missing from the defaults", () => {
    const merged = mergeSettings({ transcriptFolder: "YT" });
    expect(merged.executablePath).toBe(DEFAULT_SETTINGS.executablePath);
    expect(merged.openAfterTranscribe).toBe(DEFAULT_SETTINGS.openAfterTranscribe);
    expect(merged.transcriptFolder).toBe("YT");
  });

  it("drops the default strategy that older versions saved", () => {
    const merged = mergeSettings({
      executablePath: "yt-transcribe",
      defaultStrategy: "captions",
    } as Record<string, unknown>);
    expect(Object.keys(merged).sort()).toEqual(
      ["executablePath", "openAfterTranscribe", "transcriptFolder"]
    );
  });

  it("ignores values of the wrong type instead of trusting them", () => {
    const merged = mergeSettings({
      executablePath: 42,
      openAfterTranscribe: "yes",
    } as Record<string, unknown>);
    expect(merged.executablePath).toBe(DEFAULT_SETTINGS.executablePath);
    expect(merged.openAfterTranscribe).toBe(DEFAULT_SETTINGS.openAfterTranscribe);
  });
});
