/*
 * Settings model for the YouTube Transcribe plugin: the saved shape, its
 * defaults, and how previously saved data is read back. Kept free of any
 * Obsidian import so it can be unit-tested.
 */

// Persisted plugin settings.
export interface YttSettings {
  // Path to the yt-transcribe executable ("yt-transcribe" if on PATH).
  executablePath: string;
  // Whether to open the created note after a successful transcription.
  openAfterTranscribe: boolean;
  // Vault-relative folder to write transcripts into. Empty = use the CLI's
  // configured location (no override).
  transcriptFolder: string;
}

// Defaults applied on first run and for any value that was never saved.
export const DEFAULT_SETTINGS: YttSettings = {
  executablePath: "yt-transcribe",
  openAfterTranscribe: true,
  transcriptFolder: "",
};

/**
 * Build the settings from whatever was saved on disk.
 *
 * Only the current keys are read, so keys written by older versions (such as
 * the default strategy removed with the cloud strategy) are dropped the next
 * time the settings are saved. A value of the wrong type falls back to its
 * default instead of being trusted.
 *
 * @param saved The data returned by Obsidian's loadData(), or null on first run.
 * @returns A complete settings object.
 */
export function mergeSettings(
  saved: Record<string, unknown> | null | undefined
): YttSettings {
  const data = saved ?? {};
  return {
    executablePath:
      typeof data.executablePath === "string"
        ? data.executablePath
        : DEFAULT_SETTINGS.executablePath,
    openAfterTranscribe:
      typeof data.openAfterTranscribe === "boolean"
        ? data.openAfterTranscribe
        : DEFAULT_SETTINGS.openAfterTranscribe,
    transcriptFolder:
      typeof data.transcriptFolder === "string"
        ? data.transcriptFolder
        : DEFAULT_SETTINGS.transcriptFolder,
  };
}
