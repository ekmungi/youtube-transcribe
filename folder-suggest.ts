/*
 * Folder autocomplete for a settings text input. Lets the user pick a vault
 * folder by typing, backed by the vault's loaded folder list.
 */

import { AbstractInputSuggest, App, TFolder } from "obsidian";

/**
 * Suggests vault folders as the user types into a text input. The vault root
 * is offered as an empty value (transcripts written directly under the vault).
 */
export class FolderSuggest extends AbstractInputSuggest<TFolder> {
  // The input element being augmented with suggestions.
  private readonly textInputEl: HTMLInputElement;
  // Called with the chosen folder path (empty string for the vault root).
  private readonly onSelectFolder: (value: string) => void;

  /**
   * @param app The Obsidian app instance.
   * @param textInputEl The settings text input to attach suggestions to.
   * @param onSelectFolder Callback receiving the selected folder path.
   */
  constructor(
    app: App,
    textInputEl: HTMLInputElement,
    onSelectFolder: (value: string) => void
  ) {
    super(app, textInputEl);
    this.textInputEl = textInputEl;
    this.onSelectFolder = onSelectFolder;
  }

  /**
   * Return folders whose path contains the query (case-insensitive).
   * @param query Current text typed by the user.
   * @returns Matching TFolder instances.
   */
  getSuggestions(query: string): TFolder[] {
    const lower = query.toLowerCase();
    return this.app.vault
      .getAllLoadedFiles()
      .filter(
        (f): f is TFolder =>
          f instanceof TFolder && f.path.toLowerCase().includes(lower)
      );
  }

  /**
   * Render a folder suggestion row.
   * @param folder The folder to display.
   * @param el The row element to populate.
   * @returns void
   */
  renderSuggestion(folder: TFolder, el: HTMLElement): void {
    el.setText(folder.path === "/" ? "/ (vault root)" : folder.path);
  }

  /**
   * Apply the chosen folder: the vault root maps to an empty string so the
   * CLI writes directly under the vault.
   * @param folder The selected folder.
   * @returns void
   */
  selectSuggestion(folder: TFolder): void {
    const value = folder.path === "/" ? "" : folder.path;
    this.textInputEl.value = value;
    this.onSelectFolder(value);
    this.close();
  }
}
