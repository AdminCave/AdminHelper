// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The options of the embedded terminal (R-1069), one set for the device in the settings. A change
// made in a terminal is saved at once and every open terminal takes it; the settings dialog saves
// them with the rest of its form.

import { derived, get, writable } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { TerminalPrefs } from '$lib/bridge/types';
import { clampTerminalPrefs, getTerminalDefaults } from '$lib/models/settings';
import { errMsg } from '$lib/utils/errors';
import { refreshSettings, settings } from './session';
import { reportError } from './statusBar';

// What a terminal changed last while its saves are still going: a second click on "larger"
// builds on the first, not on settings that have not loaded again yet.
const latest = writable<TerminalPrefs | null>(null);
let saves: Promise<void> = Promise.resolve();
let unsettled = 0;

/** The options the terminals show: the last change made in one, else those of the settings. */
export const terminalPrefs = derived([settings, latest], ([$settings, $latest]) =>
  clampTerminalPrefs($latest ?? $settings?.terminal ?? getTerminalDefaults()),
);

/**
 * Saves `prefs` as the options of the terminal, one save after the other; the terminals show them
 * at once. A failed save goes to the status bar, and the terminals return to what is saved.
 */
export function saveTerminalPrefs(prefs: TerminalPrefs): Promise<void> {
  const next = clampTerminalPrefs(prefs);
  latest.set(next);
  unsettled += 1;
  saves = saves.then(async () => {
    try {
      // Taken when this save starts, so it keeps what another save changed meanwhile.
      // Before the settings have loaded there is nothing to save the options into.
      const current = get(settings);
      if (current) {
        await bridge.saveSettings({ ...current, terminal: next });
        await refreshSettings();
      }
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      unsettled -= 1;
      if (unsettled === 0) latest.set(null);
    }
  });
  return saves;
}
