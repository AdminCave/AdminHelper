// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The form takes the stored settings once per opening (R-0715): a store change while it is
// open does not reset what is being typed, and opening it again starts from the store anew.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { settingsModalOpen } from '$lib/stores/settings';
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
      confirmMultilinePaste: false,
    },
  } satisfies Settings,
  // Set by the session mock below.
  setStored: (_settings: Settings): void => {},
}));

// Everything but the reads on opening fails loudly, as in SettingsModal.save.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    isDeviceEnrolled: async () => false,
    deviceIdentity: async () => null,
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
  h.setStored = (next) => settings.set(next);
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

afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  h.setStored(h.stored);
});

function interval(container: HTMLElement): HTMLInputElement {
  const found = container.querySelector<HTMLInputElement>('input[type="number"]');
  expect(found).not.toBeNull();
  return found!;
}

function storePasswords(container: HTMLElement): HTMLInputElement {
  // The one checkbox of the passwords section.
  const found = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].find(
    (c) => c.closest('.sm-section')?.textContent?.includes('Passw'),
  );
  expect(found).toBeDefined();
  return found!;
}

describe('SettingsModal — the form seeds once per opening (R-0715)', () => {
  it('keeps what is typed when the stored settings change', async () => {
    settingsModalOpen.set(true);
    const { container } = render(SettingsModal);
    expect(interval(container).value).toBe('5');

    await fireEvent.input(interval(container), { target: { value: '42' } });
    await fireEvent.click(storePasswords(container));
    h.setStored({ ...h.stored, intervalMinutes: 7, storePasswords: false, language: 'en' });
    await tick();

    expect(interval(container).value).toBe('42');
    expect(storePasswords(container).checked).toBe(true);
  });

  it('starts from the stored settings again on the next opening', async () => {
    settingsModalOpen.set(true);
    const { container } = render(SettingsModal);
    await fireEvent.input(interval(container), { target: { value: '42' } });

    // Closed without saving, the store changed meanwhile.
    settingsModalOpen.set(false);
    await tick();
    expect(container.querySelector('.sm-panel')).toBeNull();
    h.setStored({ ...h.stored, intervalMinutes: 9 });
    settingsModalOpen.set(true);
    await tick();

    expect(interval(container).value).toBe('9');
    expect(storePasswords(container).checked).toBe(false);
  });
});
