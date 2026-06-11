/*
 * Settings model and settings tab for the YouTube Transcribe plugin.
 * Kept separate from main.ts so the plugin entry point stays focused on the
 * transcription flow. Depends only on ./cli (one-directional, no import cycle).
 */

import {
  App,
  ButtonComponent,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
} from "obsidian";
import { CliSpawnError, runSetupFfmpeg, Strategy } from "./cli";
import { FolderSuggest } from "./folder-suggest";

// Persisted plugin settings.
export interface YttSettings {
  // Path to the yt-transcribe executable ("yt-transcribe" if on PATH).
  executablePath: string;
  // Default strategy used unless a retry overrides it.
  defaultStrategy: Strategy;
  // Whether to open the created note after a successful transcription.
  openAfterTranscribe: boolean;
  // Vault-relative folder to write transcripts into. Empty = use the CLI's
  // configured location (no override).
  transcriptFolder: string;
}

// Defaults applied on first run and merged with any saved data.
export const DEFAULT_SETTINGS: YttSettings = {
  executablePath: "yt-transcribe",
  defaultStrategy: "captions",
  openAfterTranscribe: true,
  transcriptFolder: "",
};

// Minimal surface the settings tab needs from the owning plugin. Declaring it
// as an interface (rather than importing the concrete class) avoids a circular
// import between main.ts and settings.ts.
export interface SettingsHost {
  settings: YttSettings;
  saveSettings(): Promise<void>;
}

/** Settings tab exposing executable path, default strategy, open toggle, and ffmpeg setup. */
export class YttSettingTab extends PluginSettingTab {
  // Reference to the owning plugin for reading/writing settings.
  private readonly host: SettingsHost;

  /**
   * @param app The Obsidian app instance.
   * @param plugin The owning plugin (also the settings host).
   */
  constructor(app: App, plugin: Plugin & SettingsHost) {
    super(app, plugin);
    this.host = plugin;
  }

  /**
   * Render the settings UI.
   * @returns void
   */
  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Executable path")
      .setDesc(
        "Path to the yt-transcribe CLI. Use the bare name if it is on your PATH."
      )
      .addText((text) =>
        text
          .setPlaceholder("yt-transcribe")
          .setValue(this.host.settings.executablePath)
          .onChange(async (value) => {
            // Fall back to the default name when cleared, never store empty.
            this.host.settings.executablePath =
              value.trim() || DEFAULT_SETTINGS.executablePath;
            await this.host.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Default strategy")
      .setDesc(
        "captions: instant and free. cloud: sends audio to AssemblyAI (needs an API key and ffmpeg)."
      )
      .addDropdown((dropdown) =>
        dropdown
          .addOption("captions", "Captions (free, instant)")
          .addOption("cloud", "Cloud STT (AssemblyAI)")
          .setValue(this.host.settings.defaultStrategy)
          .onChange(async (value) => {
            // value is constrained to the two options above.
            this.host.settings.defaultStrategy = value as Strategy;
            await this.host.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Transcript folder")
      .setDesc(
        "Vault folder to write transcripts into (type to search). Leave empty to use the location configured in the CLI."
      )
      .addText((text) => {
        text
          .setPlaceholder("e.g. Sources/YouTube")
          .setValue(this.host.settings.transcriptFolder)
          .onChange(async (value) => {
            this.host.settings.transcriptFolder = value.trim();
            await this.host.saveSettings();
          });
        // Attach vault-folder autocomplete; persist on selection too.
        new FolderSuggest(this.app, text.inputEl, (value) => {
          this.host.settings.transcriptFolder = value;
          void this.host.saveSettings();
        });
      });

    new Setting(containerEl)
      .setName("Open note after transcribing")
      .setDesc("Open the created transcript note automatically on success.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.host.settings.openAfterTranscribe)
          .onChange(async (value) => {
            this.host.settings.openAfterTranscribe = value;
            await this.host.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("ffmpeg (for cloud strategy)")
      .setDesc(
        "Download a static ffmpeg into ~/.yt-transcribe/bin. Only needed for the cloud strategy; captions never use it."
      )
      .addButton((button) =>
        button
          .setButtonText("Download ffmpeg")
          .onClick(() => void this.downloadFfmpeg(button))
      );

    // Explanatory footnote on the captions-vs-cloud tradeoff.
    containerEl.createEl("p", {
      cls: "ytt-settings-note",
      text:
        'The "cloud" strategy sends video audio to AssemblyAI and requires an API key plus ffmpeg. The "captions" strategy fetches existing captions and is instant and free.',
    });
  }

  /**
   * Run the CLI's setup-ffmpeg command, disabling the button and reporting
   * progress and the outcome via Notices.
   *
   * @param button The clicked button, disabled while the download runs.
   * @returns A promise that resolves once setup completes or fails.
   */
  private async downloadFfmpeg(button: ButtonComponent): Promise<void> {
    button.setDisabled(true);
    button.setButtonText("Downloading...");
    const progress = new Notice("Downloading ffmpeg (about 100 MB)...", 0);
    try {
      const result = await runSetupFfmpeg(this.host.settings.executablePath);
      if (result.ok) {
        new Notice(`ffmpeg ready: ${result.path}`);
      } else {
        new Notice(`ffmpeg setup failed: ${result.error}`);
      }
    } catch (err) {
      if (err instanceof CliSpawnError && err.notFound) {
        new Notice(
          "yt-transcribe not found. Set the executable path above first."
        );
      } else {
        const message = err instanceof Error ? err.message : "Unknown error.";
        new Notice(`ffmpeg setup failed to run: ${message}`);
      }
    } finally {
      progress.hide();
      button.setButtonText("Download ffmpeg");
      button.setDisabled(false);
    }
  }
}
