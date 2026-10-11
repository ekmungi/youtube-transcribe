/*
 * Settings tab for the YouTube Transcribe plugin.
 * Kept separate from main.ts so the plugin entry point stays focused on the
 * transcription flow. The settings model itself lives in ./settings-model.
 */

import { App, Plugin, PluginSettingTab, Setting } from "obsidian";
import { FolderSuggest } from "./folder-suggest";
import { DEFAULT_SETTINGS, YttSettings } from "./settings-model";

// Minimal surface the settings tab needs from the owning plugin. Declaring it
// as an interface (rather than importing the concrete class) avoids a circular
// import between main.ts and settings.ts.
export interface SettingsHost {
  settings: YttSettings;
  saveSettings(): Promise<void>;
}

/** Settings tab exposing the executable path, transcript folder and open toggle. */
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

    // Where the text comes from, so nobody looks for a speech-to-text option.
    containerEl.createEl("p", {
      cls: "ytt-settings-note",
      text: "Transcripts are built from YouTube's own captions, so a video without captions cannot be transcribed.",
    });
  }
}
