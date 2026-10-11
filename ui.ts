/*
 * Modal UI components for the YouTube Transcribe plugin.
 * Contains the URL-prompt modal.
 */

import { App, Modal, Setting } from "obsidian";

/**
 * Modal that prompts the user for a YouTube URL.
 * Pre-fills the input when a likely URL is supplied (e.g. from the clipboard).
 */
export class UrlPromptModal extends Modal {
  // Initial value placed in the input field (may be empty).
  private readonly initialUrl: string;
  // Callback invoked with the trimmed URL when the user submits.
  private readonly onSubmit: (url: string) => void;
  // Backing value for the URL text field.
  private value: string;

  /**
   * @param app The Obsidian app instance.
   * @param initialUrl Value to pre-fill the input with (use "" for none).
   * @param onSubmit Called with the trimmed URL on submit; not called on cancel.
   */
  constructor(
    app: App,
    initialUrl: string,
    onSubmit: (url: string) => void
  ) {
    super(app);
    this.initialUrl = initialUrl;
    this.value = initialUrl;
    this.onSubmit = onSubmit;
  }

  /**
   * Build the modal contents when it opens.
   * Renders a labelled text input plus a primary "Transcribe" button.
   * @returns void
   */
  onOpen(): void {
    const { contentEl } = this;
    contentEl.createEl("h2", { text: "Transcribe YouTube video" });

    new Setting(contentEl)
      .setName("YouTube URL")
      .setDesc("Paste a youtube.com/watch or youtu.be link.")
      .addText((text) => {
        text
          .setPlaceholder("https://www.youtube.com/watch?v=...")
          .setValue(this.initialUrl)
          .onChange((v) => {
            this.value = v;
          });
        // Widen the input and submit on Enter for convenience.
        text.inputEl.addClass("ytt-url-input");
        text.inputEl.addEventListener("keydown", (evt: KeyboardEvent) => {
          if (evt.key === "Enter") {
            evt.preventDefault();
            this.submit();
          }
        });
        // Focus the field so the user can type or just press Enter immediately.
        window.setTimeout(() => text.inputEl.focus(), 0);
      });

    new Setting(contentEl).addButton((btn) =>
      btn
        .setButtonText("Transcribe")
        .setCta()
        .onClick(() => this.submit())
    );
  }

  /**
   * Validate and forward the current input value, then close the modal.
   * No-op when the trimmed value is empty.
   * @returns void
   */
  private submit(): void {
    const trimmed = this.value.trim();
    if (trimmed.length === 0) {
      return;
    }
    this.close();
    this.onSubmit(trimmed);
  }

  /**
   * Clean up the modal DOM when it closes.
   * @returns void
   */
  onClose(): void {
    this.contentEl.empty();
  }
}
