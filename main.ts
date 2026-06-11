/*
 * YouTube Transcribe Obsidian plugin entry point.
 * Thin UI over the local `yt-transcribe` CLI: takes a YouTube URL, runs the
 * CLI (which writes a transcript note into the vault), then opens that note.
 */

import { FileSystemAdapter, Notice, Plugin, TFile } from "obsidian";
import {
  CliSpawnError,
  CliSuccess,
  OutputTarget,
  runTranscribe,
  Strategy,
} from "./cli";
import { ConfirmModal, UrlPromptModal } from "./ui";
import { DEFAULT_SETTINGS, YttSettings, YttSettingTab } from "./settings";

// Matches youtube.com/watch?v=... and youtu.be/... links (with optional params).
const YOUTUBE_URL_RE =
  /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/watch\?[^ ]*v=|youtu\.be\/)[\w-]{6,}/i;

/**
 * Test whether a string looks like a YouTube video URL.
 * Used to validate clipboard contents before running the flow.
 *
 * @param text Candidate text (e.g. clipboard contents).
 * @returns True if the text contains a YouTube watch/short URL.
 */
function looksLikeYoutubeUrl(text: string): boolean {
  return YOUTUBE_URL_RE.test(text.trim());
}

/** Main plugin class. Registers commands, ribbon, and settings. */
export default class YouTubeTranscribePlugin extends Plugin {
  // Live settings; populated in onload from persisted data.
  settings: YttSettings = DEFAULT_SETTINGS;

  /**
   * Plugin lifecycle hook. Loads settings and registers commands, the ribbon
   * icon, and the settings tab.
   * @returns A promise that resolves once setup is complete.
   */
  async onload(): Promise<void> {
    await this.loadSettings();

    // Command 1: prompt for a URL (pre-filled from clipboard if it looks valid).
    this.addCommand({
      id: "transcribe-youtube-video",
      name: "Transcribe YouTube video",
      callback: () => this.promptAndTranscribe(),
    });

    // Command 2: transcribe directly from the clipboard, no modal.
    this.addCommand({
      id: "transcribe-youtube-video-from-clipboard",
      name: "Transcribe YouTube video from clipboard",
      callback: () => this.transcribeFromClipboard(),
    });

    // Ribbon icon triggers the prompt flow (command 1).
    this.addRibbonIcon("youtube", "Transcribe YouTube video", () => {
      void this.promptAndTranscribe();
    });

    this.addSettingTab(new YttSettingTab(this.app, this));
  }

  /**
   * Load persisted settings, merging over defaults.
   * @returns A promise that resolves once settings are loaded.
   */
  async loadSettings(): Promise<void> {
    const data = (await this.loadData()) as Partial<YttSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(data ?? {}) };
  }

  /**
   * Persist the current settings to disk.
   * @returns A promise that resolves once settings are saved.
   */
  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  /**
   * Open the URL-prompt modal, pre-filling from the clipboard when it looks
   * like a YouTube URL, then run the flow on submit.
   * @returns A promise that resolves once the modal has been shown.
   */
  private async promptAndTranscribe(): Promise<void> {
    let prefill = "";
    try {
      const clip = await navigator.clipboard.readText();
      if (looksLikeYoutubeUrl(clip)) {
        prefill = clip.trim();
      }
    } catch {
      // Clipboard access can fail (permissions); proceed with an empty field.
    }

    new UrlPromptModal(this.app, prefill, (url) => {
      void this.runFlow(url, this.settings.defaultStrategy);
    }).open();
  }

  /**
   * Read the clipboard, validate it as a YouTube URL, and run the flow.
   * Shows a Notice and aborts when the clipboard is not a YouTube URL.
   * @returns A promise that resolves once the flow has been kicked off.
   */
  private async transcribeFromClipboard(): Promise<void> {
    let clip = "";
    try {
      clip = await navigator.clipboard.readText();
    } catch {
      new Notice("Could not read the clipboard.");
      return;
    }

    if (!looksLikeYoutubeUrl(clip)) {
      new Notice("Clipboard does not contain a YouTube URL.");
      return;
    }

    await this.runFlow(clip.trim(), this.settings.defaultStrategy);
  }

  /**
   * Core transcription flow: run the CLI, then open or report the result.
   * Handles success, known CLI errors (with an optional cloud retry), and
   * spawn failures (e.g. missing executable).
   *
   * @param url The YouTube URL to transcribe.
   * @param strategy Strategy for this attempt ("captions" or "cloud").
   * @returns A promise that resolves once the attempt is fully handled.
   */
  private async runFlow(url: string, strategy: Strategy): Promise<void> {
    // Persistent "Transcribing..." Notice (0 = stays until we hide it).
    const progress = new Notice("Transcribing...", 0);
    try {
      const result = await runTranscribe(
        this.settings.executablePath,
        url,
        strategy,
        this.outputTarget()
      );

      if (result.ok) {
        await this.handleSuccess(result.data);
        return;
      }

      // Known CLI error. Offer a cloud retry only when this attempt used
      // captions, to avoid loops and pointless re-runs on other failures.
      if (
        result.error.error_type === "NoCaptionsError" &&
        strategy === "captions"
      ) {
        this.offerCloudRetry(url);
        return;
      }

      new Notice(`Transcription failed: ${result.error.error}`);
    } catch (err) {
      // Spawn-level failure (executable missing or no parseable output).
      if (err instanceof CliSpawnError && err.notFound) {
        new Notice(
          "yt-transcribe not found. Set the executable path in plugin settings."
        );
      } else {
        const message =
          err instanceof Error ? err.message : "Unknown error.";
        new Notice(`yt-transcribe failed to run: ${message}`);
      }
    } finally {
      // Always dismiss the persistent progress Notice.
      progress.hide();
    }
  }

  /**
   * Show a confirmation modal offering a cloud-STT retry, and re-run the flow
   * with the "cloud" strategy if the user agrees.
   * @param url The YouTube URL to retry.
   * @returns void
   */
  private offerCloudRetry(url: string): void {
    new ConfirmModal(
      this.app,
      "No captions found",
      "No captions for this video. Transcribe audio with cloud STT (AssemblyAI)?",
      (confirmed) => {
        if (confirmed) {
          void this.runFlow(url, "cloud");
        }
      }
    ).open();
  }

  /**
   * Handle a successful CLI result: notify the user and optionally open the
   * created note inside the vault.
   * @param data The parsed CLI success payload.
   * @returns A promise that resolves once the note is opened/reported.
   */
  private async handleSuccess(data: CliSuccess): Promise<void> {
    // Compose a status message describing what happened.
    const label = data.cached
      ? `Already in vault: ${data.title}`
      : `Saved: ${data.title} (${data.source})`;
    new Notice(label);

    if (!this.settings.openAfterTranscribe) {
      return;
    }

    const relPath = this.toVaultRelativePath(data.path);
    if (relPath === null) {
      // File exists but is outside this vault's base path; report the location.
      new Notice(`Note saved outside this vault: ${data.path}`);
      return;
    }

    // Resolve the TFile and open it in the active leaf; fall back to a link open.
    const file = this.app.vault.getAbstractFileByPath(relPath);
    if (file instanceof TFile) {
      await this.app.workspace.getLeaf().openFile(file);
    } else {
      // The adapter may not have indexed the new file yet; openLinkText resolves
      // by path and is tolerant of a freshly written note.
      await this.app.workspace.openLinkText(relPath, "", false);
    }
  }

  /**
   * Convert an absolute filesystem path to a vault-relative path with forward
   * slashes. Returns null when the path is not inside this vault's base path.
   *
   * @param absPath Absolute path to the note as reported by the CLI.
   * @returns A vault-relative path, or null if outside the vault.
   */
  private toVaultRelativePath(absPath: string): string | null {
    const adapter = this.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) {
      return null;
    }

    // Normalize both sides to forward slashes for a robust prefix comparison.
    const base = adapter.getBasePath().replace(/\\/g, "/");
    const normalized = absPath.replace(/\\/g, "/");

    // Case-insensitive prefix check: Windows paths differ only in casing/sep.
    if (!normalized.toLowerCase().startsWith(base.toLowerCase())) {
      return null;
    }

    // Strip the base and any leading separator left behind.
    return normalized.slice(base.length).replace(/^\/+/, "");
  }

  /**
   * Build the per-run output target from settings. Returns undefined to leave
   * the location to the CLI's own config -- when no folder is configured, or
   * the vault has no filesystem base path (e.g. a non-filesystem adapter).
   *
   * @returns An OutputTarget for this vault, or undefined to use CLI config.
   */
  private outputTarget(): OutputTarget | undefined {
    const folder = this.settings.transcriptFolder.trim();
    if (!folder) {
      return undefined;
    }
    const adapter = this.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) {
      return undefined;
    }
    return { vault: adapter.getBasePath(), folder };
  }
}
