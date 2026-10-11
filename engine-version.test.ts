/*
 * Tests for the engine version check: version parsing and ordering, the
 * outdated-engine notice, and the subprocess probe (exercised against node
 * itself so it needs no yt-transcribe install).
 */

import { describe, it, expect } from "vitest";
import {
  compareVersions,
  LAST_UNVERSIONED_ENGINE,
  MIN_ENGINE_VERSION,
  outdatedMessage,
  parseVersion,
  probeEngine,
} from "./engine-version";

describe("parseVersion", () => {
  it("extracts the version from click's --version output", () => {
    expect(parseVersion("yt-transcribe, version 0.12.0\n")).toBe("0.12.0");
  });

  it("extracts a leading-v version and drops a pre-release suffix", () => {
    expect(parseVersion("v22.1.3")).toBe("22.1.3");
    expect(parseVersion("version 1.2.3-rc1")).toBe("1.2.3");
  });

  it("returns null when no version is present", () => {
    expect(parseVersion("no such option: --version")).toBeNull();
  });
});

describe("compareVersions", () => {
  it("orders numerically, not lexically", () => {
    expect(compareVersions("0.9.0", "0.10.0")).toBeLessThan(0);
    expect(compareVersions("0.12.0", "0.11.9")).toBeGreaterThan(0);
  });

  it("treats identical versions as equal", () => {
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
  });
});

describe("outdatedMessage", () => {
  it("names both versions and the upgrade command for an old engine", () => {
    const msg = outdatedMessage({ kind: "versioned", version: "0.9.0" }, "0.10.0");
    expect(msg).toContain("0.9.0");
    expect(msg).toContain("0.10.0");
    expect(msg).toContain("uv tool upgrade yt-transcribe");
  });

  it("is silent when the engine meets or exceeds the requirement", () => {
    expect(outdatedMessage({ kind: "versioned", version: "0.10.0" }, "0.10.0")).toBeNull();
    expect(outdatedMessage({ kind: "versioned", version: "0.12.0" }, "0.10.0")).toBeNull();
  });

  it("assumes an engine without --version is the last unversioned release", () => {
    // Engines before --version existed still work with the current plugin, so
    // a requirement at or below that release must not nag.
    expect(outdatedMessage({ kind: "unversioned" }, LAST_UNVERSIONED_ENGINE)).toBeNull();
    const msg = outdatedMessage({ kind: "unversioned" }, "99.0.0");
    expect(msg).toContain("99.0.0");
  });

  it("is silent when the engine could not be launched", () => {
    // The transcription run reports a missing executable itself.
    expect(outdatedMessage({ kind: "unavailable" }, "99.0.0")).toBeNull();
  });

  it("uses the plugin's declared minimum by default", () => {
    const msg = outdatedMessage({ kind: "versioned", version: "0.0.1" });
    expect(msg).toContain(MIN_ENGINE_VERSION);
  });
});

describe("probeEngine", () => {
  it("reports the version printed by the executable", async () => {
    const status = await probeEngine(process.execPath);
    expect(status).toEqual({ kind: "versioned", version: process.versions.node });
  });

  it("reports unversioned when the executable rejects the flag", async () => {
    const status = await probeEngine(process.execPath, {
      args: ["-e", "process.exit(2)"],
    });
    expect(status).toEqual({ kind: "unversioned" });
  });

  it("reports unversioned when the output holds no version", async () => {
    const status = await probeEngine(process.execPath, {
      args: ["-e", "console.log('hello')"],
    });
    expect(status).toEqual({ kind: "unversioned" });
  });

  it("reports unavailable when the executable does not exist", async () => {
    const status = await probeEngine("definitely-not-a-real-executable-xyz");
    expect(status).toEqual({ kind: "unavailable" });
  });
});
