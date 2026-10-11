/*
 * CLI bridge for the YouTube Transcribe plugin.
 * Wraps the local `yt-transcribe` executable: spawns it, parses the single
 * JSON result line from stdout, and exposes typed success/error results.
 */

import { execFile } from "child_process";

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
 * `error_type` lets callers branch (e.g. NoCaptionsError, CaptionFetchError).
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

// Process limits: a transcription can be slow and verbose.
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
 * Build the argument list for `yt-transcribe video`.
 *
 * @param url The YouTube URL to transcribe.
 * @param target Optional vault/folder override for where the note is written.
 * @returns The arguments, always asking for the single-line JSON result.
 */
export function videoArgs(url: string, target?: OutputTarget): string[] {
  const args = ["video", url, "--json"];
  if (target) {
    // Pass both together: --folder alone would combine with the CLI's
    // configured vault, which may not be this vault.
    args.push("--vault", target.vault, "--folder", target.folder);
  }
  return args;
}

/**
 * Build the argument list for `yt-transcribe playlist`.
 *
 * @param url The YouTube playlist URL to transcribe.
 * @param target Optional vault/folder override for where the notes are written.
 * @returns The arguments, always asking for the single-line JSON result.
 */
export function playlistArgs(url: string, target?: OutputTarget): string[] {
  const args = ["playlist", url, "--json"];
  if (target) {
    args.push("--vault", target.vault, "--folder", target.folder);
  }
  return args;
}

/**
 * Run `yt-transcribe video <url> --json` and parse it.
 *
 * Resolves with a CliResult (success or known error) whenever the CLI produced
 * a parseable JSON result line, even on exit code 1. Rejects with CliSpawnError
 * only when the process could not be launched or emitted no parseable output.
 *
 * @param execPath Path to the yt-transcribe executable (or "yt-transcribe").
 * @param url The YouTube URL to transcribe.
 * @param target Optional vault/folder override for where the note is written.
 * @returns A promise resolving to a typed CliResult.
 */
export function runTranscribe(
  execPath: string,
  url: string,
  target?: OutputTarget
): Promise<CliResult> {
  const args = videoArgs(url, target);
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

// One transcript within a playlist result. Mirrors a single video's success
// fields; `cached` marks entries that were already in the vault.
export interface PlaylistEntry {
  readonly path: string;
  readonly title: string;
  readonly video_id: string;
  readonly source: string;
  readonly caption_language?: string;
  readonly cached?: boolean;
}

// One playlist video the engine could not transcribe. `error_type` is the
// engine's exception name (e.g. NoCaptionsError, CaptionFetchError).
export interface PlaylistFailure {
  readonly video_id: string;
  readonly title: string;
  readonly error: string;
  readonly error_type: string;
}

// Successful playlist result: a count and one entry per saved video. The CLI
// writes one markdown file per video; `transcripts[i].path` is each note's
// location. `failed` lists videos that could not be transcribed; engines
// before 0.12.0 do not send it, so it is optional.
export interface PlaylistSuccess {
  readonly count: number;
  readonly transcripts: readonly PlaylistEntry[];
  readonly failed?: readonly PlaylistFailure[];
}

// Discriminated union returned by runPlaylist: ok === true => success.
export type PlaylistResult =
  | { readonly ok: true; readonly data: PlaylistSuccess }
  | { readonly ok: false; readonly error: CliError };

// Playlists can hold many videos; allow far longer than a single transcription.
const PLAYLIST_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

/**
 * Parse a playlist CLI JSON line into a typed PlaylistResult.
 * Treats the presence of an `error` field as a failure regardless of shape.
 *
 * @param line The JSON line emitted by `yt-transcribe playlist --json`.
 * @returns A typed PlaylistResult.
 * @throws Error if the line is not valid JSON.
 */
export function parsePlaylistOutput(line: string): PlaylistResult {
  const parsed = JSON.parse(line) as Record<string, unknown>;
  if (typeof parsed.error === "string") {
    return {
      ok: false,
      error: {
        error: parsed.error,
        error_type:
          typeof parsed.error_type === "string" ? parsed.error_type : "Unknown",
      },
    };
  }
  return { ok: true, data: parsed as unknown as PlaylistSuccess };
}

/**
 * Run `yt-transcribe playlist <url> --json` and parse it.
 *
 * Resolves with a PlaylistResult (success or known error) whenever the CLI
 * produced a parseable JSON line, even on exit code 1. Rejects with
 * CliSpawnError only when the process could not be launched or emitted no
 * parseable output.
 *
 * @param execPath Path to the yt-transcribe executable (or "yt-transcribe").
 * @param url The YouTube playlist URL to transcribe.
 * @param target Optional vault/folder override for where notes are written.
 * @returns A promise resolving to a typed PlaylistResult.
 */
export function runPlaylist(
  execPath: string,
  url: string,
  target?: OutputTarget
): Promise<PlaylistResult> {
  const args = playlistArgs(url, target);
  return new Promise((resolve, reject) => {
    execFile(
      execPath,
      args,
      { timeout: PLAYLIST_TIMEOUT_MS, maxBuffer: MAX_BUFFER, windowsHide: true },
      (err, stdout, stderr) => {
        const errCode = (err as NodeJS.ErrnoException | null)?.code;
        if (errCode === "ENOENT") {
          reject(new CliSpawnError(`Executable not found: ${execPath}`, true));
          return;
        }

        const line = lastNonEmptyLine(stdout) || lastNonEmptyLine(stderr);
        if (line) {
          try {
            resolve(parsePlaylistOutput(line));
            return;
          } catch {
            // Fall through to the spawn-error path below if JSON was invalid.
          }
        }

        const reason =
          err?.message ?? "CLI produced no parseable JSON output.";
        reject(new CliSpawnError(reason, false));
      }
    );
  });
}
