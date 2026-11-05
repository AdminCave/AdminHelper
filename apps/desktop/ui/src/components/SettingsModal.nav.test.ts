// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The settings show one section at a time (R-1063): the dialog opens on "General", the nav
// switches by click and by arrow keys, and a save takes what was changed in every section.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { settingsModalOpen, stopSyncTimer } from '$lib/stores/settings';
import type { Settings } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  stored: {
    mode: 'sync',
    url: 'https://sync.example/list.json',
    intervalMinutes: 5,
    language: 'de',
    storePasswords: false,
    rdpScalingMode: 'auto',
    rdpWindowMode: 'fit',
    rdpCustomSize: '1920x1080',
    rdpPerformanceProfile: 'auto',
    allowSelfSignedCerts: false,
    osNotifications: false,
    sshConsole: 'external',
    terminal: {
      fontSize: 13,
      theme: 'cave',
      cursor: 'block',
      scrollback: 10000,
      copyOnSelect: true,
      rightClickPaste: true,
      confirmClose: true,
    },
  } satisfies Settings,
  saveSettings: vi.fn(async (_settings: Settings) => undefined),
}));

// Everything but the calls under test fails loudly, as in SettingsModal.save.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    isDeviceEnrolled: async () => false,
    deviceIdentity: async () => null,
    saveSettings: h.saveSettings,
  };
  const passthrough = new Set(['then', '__esModule', 'default']);
  return new Proxy(
    {},
    {
      get: (_target, prop) => {
        if (typeof prop === 'symbol' || passthrough.has(String(prop))) return undefined;
        return (
          known[String(prop)] ??
          (() => {
            throw new Error(`bridge.${String(prop)}() is not part of this test`);
          })
        );
      },
      has: (_target, prop) => !passthrough.has(String(prop)),
    },
  );
});

vi.mock('$lib/stores/session', async () => {
  const { readable, writable, derived } = await import('svelte/store');
  const settings = writable<Settings>(h.stored);
  return {
    sessionStore: derived(settings, (s) => ({ settings: s, session: null, ready: true })),
    settings: { subscribe: settings.subscribe },
    session: readable(null),
    currentSession: () => null,
    refreshSettings: vi.fn(async () => undefined),
  };
});

vi.mock('$lib/stores/tunnel', () => ({
  startIfServerMode: vi.fn(async () => undefined),
  stop: vi.fn(async () => undefined),
}));

vi.mock('@tauri-apps/plugin-dialog', () => ({ save: vi.fn(async () => null) }));

import SettingsModal from './SettingsModal.svelte';

const SECTIONS = ['general', 'workspace', 'rdp', 'notifications', 'device'];

beforeEach(() => {
  setLanguage('de');
});

afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  stopSyncTimer();
  vi.clearAllMocks();
  setLanguage('de');
});

function open(): HTMLElement {
  settingsModalOpen.set(true);
  return render(SettingsModal).container;
}

function tab(container: HTMLElement, id: string): HTMLButtonElement {
  const found = container.querySelector<HTMLButtonElement>(`[role="tab"][data-section="${id}"]`);
  expect(found).not.toBeNull();
  return found!;
}

function pane(container: HTMLElement, id: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`[role="tabpanel"][data-pane="${id}"]`);
  expect(found).not.toBeNull();
  return found!;
}

/** Exactly one section shows, and its tab is the selected one. */
function expectShown(container: HTMLElement, id: string): void {
  for (const other of SECTIONS) {
    expect(pane(container, other).hidden).toBe(other !== id);
    expect(tab(container, other).getAttribute('aria-selected')).toBe(String(other === id));
    expect(tab(container, other).tabIndex).toBe(other === id ? 0 : -1);
  }
}

describe('SettingsModal — sections (R-1063)', () => {
  it('opens on General, with the five sections in the nav', () => {
    const container = open();

    expect(
      [...container.querySelectorAll('[role="tab"]')].map((b) => b.getAttribute('data-section')),
    ).toEqual(SECTIONS);
    expectShown(container, 'general');
    expect(pane(container, 'general').querySelector('select')).not.toBeNull();
  });

  it('switches the section on a click', async () => {
    const container = open();

    await fireEvent.click(tab(container, 'device'));
    expectShown(container, 'device');
    expect(pane(container, 'device').querySelector('[data-action="pin-reset"]')).not.toBeNull();

    await fireEvent.click(tab(container, 'rdp'));
    expectShown(container, 'rdp');
  });

  it('moves along the nav with the arrow keys, wrapping at the ends', async () => {
    const container = open();

    await fireEvent.keyDown(tab(container, 'general'), { key: 'ArrowDown' });
    expectShown(container, 'workspace');
    expect(document.activeElement).toBe(tab(container, 'workspace'));

    await fireEvent.keyDown(tab(container, 'workspace'), { key: 'End' });
    expectShown(container, 'device');
    await fireEvent.keyDown(tab(container, 'device'), { key: 'ArrowDown' });
    expectShown(container, 'general');
    await fireEvent.keyDown(tab(container, 'general'), { key: 'ArrowUp' });
    expectShown(container, 'device');
    expect(document.activeElement).toBe(tab(container, 'device'));
  });

  it('saves what was changed in every section', async () => {
    const container = open();

    const language = [...pane(container, 'general').querySelectorAll('select')].find((s) =>
      [...s.options].some((o) => o.value === 'en'),
    )!;
    await fireEvent.change(language, { target: { value: 'en' } });

    await fireEvent.click(tab(container, 'workspace'));
    const interval = pane(container, 'workspace').querySelector<HTMLInputElement>(
      'input[type="number"]',
    )!;
    await fireEvent.input(interval, { target: { value: '42' } });

    await fireEvent.click(tab(container, 'rdp'));
    const windowMode = [...pane(container, 'rdp').querySelectorAll('select')].find((s) =>
      [...s.options].some((o) => o.value === 'custom'),
    )!;
    await fireEvent.change(windowMode, { target: { value: 'custom' } });
    const size = pane(container, 'rdp').querySelector<HTMLInputElement>('input[type="text"]')!;
    await fireEvent.input(size, { target: { value: ' 1280x720 ' } });

    // Back on General, the change made there is still in its field.
    await fireEvent.click(tab(container, 'general'));
    expect(language.value).toBe('en');

    await fireEvent.click(container.querySelector('[data-action="settings-save"]')!);

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledExactlyOnceWith({
      ...h.stored,
      language: 'en',
      intervalMinutes: 42,
      rdpWindowMode: 'custom',
      rdpCustomSize: '1280x720',
    });
  });
});
