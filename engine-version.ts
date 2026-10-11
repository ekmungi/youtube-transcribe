/*
 * Engine version check for the YouTube Transcribe plugin.
 * The plugin and the yt-transcribe engine are installed separately (BRAT and
 * uv), so this probes `yt-transcribe --version` and tells the user when the
 * engine is older than the plugin needs.
 */

import { execFile } from "child_process";

// Oldest engine this plugin works with. Raise it when the plugin starts to
// depend on a newer CLI feature or JSON field.
export const MIN_ENGINE_VERSION = "0.10.0";

// Last engine release that had no --version flag. An engine that rejects the
// flag is assumed to be this release: it works with the current plugin, so
// it must not trigger a warning unless MIN_ENGINE_VERSION rises above it.
export const LAST_UNVERSIONED_ENGINE = "0.11.0";

// How long to wait for the probe; a cold Python start can take a few seconds.
const PROBE_TIMEOUT_MS = 10_000;

// First dotted numeric triple in a string, e.g. "0.12.0" in "version 0.12.0".
const VERSION_RE = /(\d+)\.(\d+)\.(\d+)/;

/**
 * Result of probing the engine.
 * "versioned": it printed a version. "unversioned": it ran but did not
 * understand --version (an engine from before the flag existed).
 * "unavailable": it could not be launched at all.
 */
export type EngineStatus =
  | { readonly kind: "versioned"; readonly version: string }
  | { readonly kind: "unversioned" }
  | { readonly kind: "unavailable" };

/** Optional overrides for probeEngine; tests use them to avoid a real engine. */
export interface ProbeOptions {
  readonly args?: readonly string[];
  readonly timeoutMs?: number;
}

/**
 * Pull the first x.y.z version out of a block of text.
 *
 * @param text Output from `yt-transcribe --version`, e.g.
 *   "yt-transcribe, version 0.12.0".
 * @returns The version string, or null when none is present.
 */
export function parseVersion(text: string): string | null {
  const match = VERSION_RE.exec(text);
  return match ? `${match[1]}.${match[2]}.${match[3]}` : null;
}

/**
 * Compare two x.y.z versions numerically ("0.9.0" is older than "0.10.0").
 *
 * @param a First version.
 * @param b Second version.
 * @returns Negative if a is older than b, positive if newer, 0 if equal.
 */
export function compareVersions(a: string, b: string): number {
  const left = a.split(".").map(Number);
  const right = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) {
      return diff;
    }
  }
  return 0;
}

/**
 * Build the notice shown when the engine is older than the plugin needs.
 *
 * @param status Result of probeEngine.
 * @param required Minimum engine version; defaults to MIN_ENGINE_VERSION.
 * @returns The notice text, or null when the engine is fine or cannot be
 *   judged (a missing executable is reported by the transcription run itself).
 */
export function outdatedMessage(
  status: EngineStatus,
  required: string = MIN_ENGINE_VERSION
): string | null {
  if (status.kind === "unavailable") {
    return null;
  }
  const effective =
    status.kind === "versioned" ? status.version : LAST_UNVERSIONED_ENGINE;
  if (compareVersions(effective, required) >= 0) {
    return null;
  }
  const found =
    status.kind === "versioned"
      ? `engine ${status.version}`
      : "an engine too old to report its version";
  return (
    `This plugin needs yt-transcribe ${required} or newer, but found ${found}. ` +
    "Update it with: uv tool upgrade yt-transcribe"
  );
}

/**
 * Run `<execPath> --version` and classify the result. Never rejects: every
 * failure maps to a status so callers can ignore a failed probe.
 *
 * @param execPath Path to the yt-transcribe executable (or "yt-transcribe").
 * @param options Optional argument and timeout overrides (used by tests).
 * @returns A promise resolving to the engine status.
 */
export function probeEngine(
  execPath: string,
  options: ProbeOptions = {}
): Promise<EngineStatus> {
  const args = [...(options.args ?? ["--version"])];
  const timeout = options.timeoutMs ?? PROBE_TIMEOUT_MS;
  return new Promise((resolve) => {
    execFile(execPath, args, { timeout, windowsHide: true }, (err, stdout) => {
      if (err) {
        // A string code (ENOENT, EACCES) or a kill means the process never
        // ran to completion; a numeric code is a normal non-zero exit, which
        // is how an engine without --version rejects the flag.
        const code = (err as NodeJS.ErrnoException).code;
        const neverRan = typeof code === "string" || err.killed === true;
        resolve(neverRan ? { kind: "unavailable" } : { kind: "unversioned" });
        return;
      }
      const version = parseVersion(stdout);
      resolve(version ? { kind: "versioned", version } : { kind: "unversioned" });
    });
  });
}
