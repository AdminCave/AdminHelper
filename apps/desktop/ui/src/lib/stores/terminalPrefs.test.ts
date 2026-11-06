// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The options of the embedded terminal (R-1069) as a terminal saves them: shown at once, a second
// change before the first is saved builds on it and is saved after it, a failed save goes to the
// status bar and the terminals return to what is saved, and before the settings have loaded
// nothing is saved.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import type { Settings } from '$lib/bridge/types';
import { getSettingsDefaults, getTerminalDefaults, TERMINAL_FONT_SIZE } from '$lib/models/settings';

const h = vi.hoisted(() => ({
  saveSettings: vi.fn<(next: unknown) => Promise<void>>(),
  refreshSettings: vi.fn(async () => {}),
  reportError: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({ saveSettings: h.saveSettings }));
vi.mock('./statusBar', () => ({ reportError: h.reportError }));
vi.mock('./session', async () => {
  const { writable } = await import('svelte/store');
  return { settings: writable(null), refreshSettings: h.refreshSettings };
});

import { settings } from './session';
import { saveTerminalPrefs, terminalPrefs } from './terminalPrefs';

const settingsStore = settings as unknown as ReturnType<typeof writable<Settings | null>>;

function stored(fontSize: number): Settings {
  return { ...getSettingsDefaults(), terminal: { ...getTerminalDefaults(), fontSize } };
}

const fontSizes = () =>
  h.saveSettings.mock.calls.map(([next]) => (next as Settings).terminal.fontSize);

beforeEach(() => {
  vi.clearAllMocks();
  settingsStore.set(stored(13));
  // As the bridge and the refresh after it: the settings then hold what was saved.
  h.saveSettings.mockImplementation(async (next) => settingsStore.set(next as Settings));
});

describe('saveTerminalPrefs', () => {
  it('shows a change at once and saves it into the settings', async () => {
    const done = saveTerminalPrefs({ ...get(terminalPrefs), fontSize: 14 });
    expect(get(terminalPrefs).fontSize).toBe(14);

    await done;
    expect(h.saveSettings).toHaveBeenCalledWith({ ...stored(14) });
    expect(h.refreshSettings).toHaveBeenCalledTimes(1);
    expect(get(terminalPrefs).fontSize).toBe(14);
  });

  it('builds a second change on the first and saves them one after the other', async () => {
    const pending: (() => void)[] = [];
    h.saveSettings.mockImplementation(
      (next) =>
        new Promise<void>((resolve) =>
          pending.push(() => {
            settingsStore.set(next as Settings);
            resolve();
          }),
        ),
    );

    const larger = () =>
      saveTerminalPrefs({ ...get(terminalPrefs), fontSize: get(terminalPrefs).fontSize + 1 });
    void larger();
    const second = larger();
    expect(get(terminalPrefs).fontSize).toBe(15);

    await vi.waitFor(() => expect(h.saveSettings).toHaveBeenCalledTimes(1));
    pending[0]();
    await vi.waitFor(() => expect(h.saveSettings).toHaveBeenCalledTimes(2));
    expect(fontSizes()).toEqual([14, 15]);
    // The settings hold the first save, the terminals still show the second.
    expect(get(settingsStore)?.terminal.fontSize).toBe(14);
    expect(get(terminalPrefs).fontSize).toBe(15);

    pending[1]();
    await second;
    expect(get(terminalPrefs).fontSize).toBe(15);
  });

  it('reports a failed save and returns the terminals to what is saved', async () => {
    h.saveSettings.mockRejectedValueOnce(new Error('settings file is read-only'));

    const done = saveTerminalPrefs({ ...get(terminalPrefs), theme: 'light' });
    expect(get(terminalPrefs).theme).toBe('light');

    await done;
    expect(h.reportError).toHaveBeenCalledWith('settings file is read-only');
    expect(h.refreshSettings).not.toHaveBeenCalled();
    expect(get(terminalPrefs).theme).toBe('cave');
  });

  it('saves nothing before the settings have loaded', async () => {
    settingsStore.set(null);

    const done = saveTerminalPrefs({ ...getTerminalDefaults(), fontSize: 16 });
    expect(get(terminalPrefs).fontSize).toBe(16);

    await done;
    expect(h.saveSettings).not.toHaveBeenCalled();
    expect(h.reportError).not.toHaveBeenCalled();
    expect(get(terminalPrefs)).toEqual(getTerminalDefaults());
  });

  it('keeps a change within what the settings offer', async () => {
    await saveTerminalPrefs({ ...get(terminalPrefs), fontSize: 99 });
    expect(fontSizes()).toEqual([TERMINAL_FONT_SIZE.max]);
  });
});
