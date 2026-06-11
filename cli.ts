/*
 * CLI bridge for the YouTube Transcribe plugin.
 * Wraps the local `yt-transcribe` executable: spawns it, parses the single
 * JSON result line from stdout, and exposes typed success/error results.
 */

import { execFile } from "child_process";

// Strategy the CLI uses to obtain a transcript.
// "captions" is instant and free; "cloud" sends audio to AssemblyAI.
export type Strategy = "captions" | "cloud";

/**
 * Successful CLI result. Mirrors the JSON the CLI prints on exit 0.
 * `path` is an absolute filesystem path to the created markdown note.
 */
export interface CliSuccess {
  readonly path: string;
  readonly title: string;
  readonly video_id: string;
  readonly source: string;
  readonly original_source?: string;
  readonly caption_language?: string;
  readonly cached?: boolean;
}

/**
 * Known-error CLI result. Mirrors the JSON the CLI prints on exit 1.
 * `error_type` lets callers branch (e.g. offer a cloud retry on NoCaptionsError).
 */
export interface CliError {
  readonly error: string;
  readonly error_type: string;
}

// Discriminated union returned by runTranscribe: ok === true => success.
export type CliResult =
  | { readonly ok: true; readonly data: CliSuccess }
  | { readonly ok: false; readonly error: CliError };

// Raised when the executable itself cannot be launched (e.g. not found).
export class CliSpawnError extends Error {
  // True when the OS reported ENOENT (executable not on PATH / wrong path).
  readonly notFound: boolean;

  /**
   * @param message Human-readable description of the spawn failure.
   * @param notFound Whether the underlying cause was a missing executable.
   */
  constructor(message: string, notFound: boolean) {
    super(message);
    this.name = "CliSpawnError";
    this.notFound = notFound;
  }
}

// Process limits: transcription (esp. cloud) can be slow and verbose.
const TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
const MAX_BUFFER = 10 * 1024 * 1024; // 10 MB

/**
 * Extract the last non-empty line from a block of text.
 * The CLI prints its JSON result as the final line; stderr/stdout may contain
 * yt-dlp noise before it, so we parse the last meaningful line only.
 *
 * @param text Raw stdout captured from the CLI.
 * @returns The last non-empty, trimmed line, or "" if none exists.
 */
function lastNonEmptyLine(text: string): string {
  const lines = text.split(/\r?\n/);
  for (let i = lines.length - 1; i >= 0; i--) {
    const trimmed = lines[i].trim();
    if (trimmed.length > 0) {
      return trimmed;
    }
  }
  return "";
}

/**
 * Parse a CLI JSON line into a typed CliResult.
 * Treats the presence of an `error` field as a failure regardless of shape.
 *
 * @param line The JSON line emitted by the CLI.
 * @returns A typed CliResult.
 * @throws Error if the line is not valid JSON.
 */
export function parseCliOutput(line: string): CliResult {
  // JSON.parse returns unknown shape; we narrow via field presence below.
  const parsed = JSON.parse(line) as Record<string, unknown>;
  if (typeof parsed.error === "string") {
    return {
      ok: false,
      error: {
        error: parsed.error,
        // error_type may be absent on unexpected errors; default to "Unknown".
        error_type:
          typeof parsed.error_type === "string" ? parsed.error_type : "Unknown",
      },
    };
  }
  return { ok: true, data: parsed as unknown as CliSuccess };
}

// Optional per-run output target: vault root and a subfolder within it.
export interface OutputTarget {
  readonly vault: string;
  readonly folder: string;
}

/**
 * Run `yt-transcribe video <url> --json --strategy <strategy>` and parse it.
 *
 * Resolves with a CliResult (success or known error) whenever the CLI produced
 * a parseable JSON result line, even on exit code 1. Rejects with CliSpawnError
 * only when the process could not be launched or emitted no parseable output.
 *
 * @param execPath Path to the yt-transcribe executable (or "yt-transcribe").
 * @param url The YouTube URL to transcribe.
 * @param strategy Transcription strategy ("captions" or "cloud").
 * @param target Optional vault/folder override for where the note is written.
 * @returns A promise resolving to a typed CliResult.
 */
export function runTranscribe(
  execPath: string,
  url: string,
  strategy: Strategy,
  target?: OutputTarget
): Promise<CliResult> {
  const args = ["video", url, "--json", "--strategy", strategy];
  if (target) {
    // Pass both together: --folder alone would combine with the CLI's
    // configured vault, which may not be this vault.
    args.push("--vault", target.vault, "--folder", target.folder);
  }
  return new Promise((resolve, reject) => {
    execFile(
      execPath,
      args,
      { timeout: TIMEOUT_MS, maxBuffer: MAX_BUFFER, windowsHide: true },
      (err, stdout, stderr) => {
        // Spawn-level failure: executable missing or unlaunchable.
        // Node sets err.code to "ENOENT" on a missing binary.
        const errCode = (err as NodeJS.ErrnoException | null)?.code;
        if (errCode === "ENOENT") {
          reject(
            new CliSpawnError(
              `Executable not found: ${execPath}`,
              true
            )
          );
          return;
        }

        // Prefer the JSON result on stdout; fall back to stderr if stdout empty.
        const line =
          lastNonEmptyLine(stdout) || lastNonEmptyLine(stderr);
        if (line) {
          try {
            resolve(parseCliOutput(line));
            return;
          } catch {
            // Fall through to the spawn-error path below if JSON was invalid.
          }
        }

        // No parseable output: surface a spawn-level error with context.
        const reason =
          err?.message ?? "CLI produced no parseable JSON output.";
        reject(new CliSpawnError(reason, false));
      }
    );
  });
}

// Result of an ffmpeg setup run: the install directory, or an error message.
export type FfmpegSetupResult =
  | { readonly ok: true; readonly path: string }
  | { readonly ok: false; readonly error: string };

// ffmpeg is a ~100 MB download; allow well beyond the transcription timeout.
const SETUP_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

/**
 * Run `yt-transcribe setup-ffmpeg --json` to download ffmpeg via the CLI.
 *
 * Resolves with the install path on success or a message on a known error.
 * Rejects with CliSpawnError only when the executable cannot be launched.
 *
 * @param execPath Path to the yt-transcribe executable (or "yt-transcribe").
 * @returns A promise resolving to the setup result.
 */
export function runSetupFfmpeg(execPath: string): Promise<FfmpegSetupResult> {
  return new Promise((resolve, reject) => {
    execFile(
      execPath,
      ["setup-ffmpeg", "--json"],
      { timeout: SETUP_TIMEOUT_MS, maxBuffer: MAX_BUFFER, windowsHide: true },
      (err, stdout, stderr) => {
        const errCode = (err as NodeJS.ErrnoException | null)?.code;
        if (errCode === "ENOENT") {
          reject(new CliSpawnError(`Executable not found: ${execPath}`, true));
          return;
        }

        const line = lastNonEmptyLine(stdout) || lastNonEmptyLine(stderr);
        if (line) {
          try {
            const parsed = JSON.parse(line) as Record<string, unknown>;
            if (typeof parsed.error === "string") {
              resolve({ ok: false, error: parsed.error });
            } else if (typeof parsed.path === "string") {
              resolve({ ok: true, path: parsed.path });
            } else {
              resolve({ ok: false, error: "Unexpected setup-ffmpeg output." });
            }
            return;
          } catch {
            // Fall through to the spawn-error path below if JSON was invalid.
          }
        }

        const reason = err?.message ?? "setup-ffmpeg produced no JSON output.";
        reject(new CliSpawnError(reason, false));
      }
    );
  });
}
