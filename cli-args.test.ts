/*
 * Tests for the command lines the plugin builds. The cloud strategy is gone, so
 * no argument list may carry --strategy any more.
 */

import { describe, it, expect } from "vitest";
import { playlistArgs, videoArgs } from "./cli";

const URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
const PLAYLIST = "https://www.youtube.com/playlist?list=PLabc";

describe("videoArgs", () => {
  it("asks for the video as JSON and nothing else", () => {
    expect(videoArgs(URL)).toEqual(["video", URL, "--json"]);
  });

  it("adds the vault and folder together when a target is given", () => {
    expect(videoArgs(URL, { vault: "D:/Vault", folder: "Media/YT" })).toEqual([
      "video", URL, "--json", "--vault", "D:/Vault", "--folder", "Media/YT",
    ]);
  });

  it("never passes the retired --strategy option", () => {
    expect(videoArgs(URL)).not.toContain("--strategy");
  });
});

describe("playlistArgs", () => {
  it("asks for the playlist as JSON and nothing else", () => {
    expect(playlistArgs(PLAYLIST)).toEqual(["playlist", PLAYLIST, "--json"]);
  });

  it("adds the vault and folder together when a target is given", () => {
    expect(playlistArgs(PLAYLIST, { vault: "D:/Vault", folder: "Media/YT" })).toEqual([
      "playlist", PLAYLIST, "--json", "--vault", "D:/Vault", "--folder", "Media/YT",
    ]);
  });

  it("never passes the retired --strategy option", () => {
    expect(playlistArgs(PLAYLIST)).not.toContain("--strategy");
  });
});
