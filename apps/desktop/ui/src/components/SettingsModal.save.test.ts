// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Saving the settings keeps every field the dialog does not edit (R-0429). Rust
// writes settings.json whole, so a field missing from the object is gone: every
// save dropped lastUsername, and the login screen no longer pre-filled the name.

import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from 'vitest';
import { get } from 'svelte/store';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { language, setLanguage, tNow } from '$lib/i18n';
import { settingsModalOpen } from '$lib/stores/settings';
import type { Settings } from '$lib/bridge/types';

// Values the dialog loads and writes back unchanged, so the saved object is the
// stored one with only the edited field different.
const h = vi.hoisted(() => ({
  stored: {
    mode: 'server',
    url: '',
    intervalMinutes: 5,
    language: 'de',
    storePasswords: false,
    rdpScalingMode: 'auto',
    rdpWindowMode: 'fit',
    rdpCustomSize: '1920x1080',
    rdpPerformanceProfile: 'auto',
    allowSelfSignedCerts: false,
    serverUrl: 'https://srv.example',
    lastUsername: 'kevin',
    osNotifications: false,
  } satisfies Settings,
  saveSettings: vi.fn(async (_settings: Settings) => undefined),
  // The notification prefs inside the dialog load through the proxy and render their own
  // save button once they have.
  apiProxy: vi.fn(async (method: string, path: string) => {
    if (method === 'GET' && path === '/api/users/me/notification-prefs') {
      return { email: null, subscriptions: [] };
    }
    if (method === 'GET' && path === '/api/servers') return [];
    return null;
  }),
  // Set by the session mock below.
  setStored: (_settings: Settings): void => {},
}));

// Everything but the calls under test fails loudly, as in SettingsModal.enroll.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    isDeviceEnrolled: async () => false,
    deviceIdentity: async () => null,
    saveSettings: h.saveSettings,
    apiProxy: h.apiProxy,
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
  const session = { username: 'kevin', serverUrl: 'https://srv.example' };
  const settings = writable<Settings>(h.stored);
  h.setStored = (next) => settings.set(next);
  return {
    sessionStore: derived(settings, (s) => ({ settings: s, session, ready: true })),
    settings: { subscribe: settings.subscribe },
    session: readable(session),
    currentSession: () => session,
    refreshSettings: vi.fn(async () => undefined),
  };
});

vi.mock('$lib/stores/tunnel', () => ({
  startIfServerMode: vi.fn(async () => undefined),
  stop: vi.fn(async () => undefined),
}));

vi.mock('@tauri-apps/plugin-dialog', () => ({ save: vi.fn(async () => null) }));
vi.mock('./ui/ConfirmDialog.svelte', () => ({ confirmDialog: vi.fn(async () => true) }));

import SettingsModal from './SettingsModal.svelte';

beforeEach(() => {
  // Saving applies the chosen language app-wide.
  setLanguage('de');
});

afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  vi.clearAllMocks();
});

function languageSelect(container: HTMLElement): HTMLSelectElement {
  const found = [...container.querySelectorAll('select')].find((s) =>
    [...s.options].some((o) => o.value === 'en'),
  );
  expect(found).toBeDefined();
  return found!;
}

function saveButton(container: HTMLElement): HTMLButtonElement {
  const found = [...container.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === tNow('action.save'),
  );
  expect(found).toBeDefined();
  return found!;
}

describe('SettingsModal — saving keeps the fields it does not edit (R-0429)', () => {
  it('keeps the remembered username when the language changes', async () => {
    settingsModalOpen.set(true);
    const { container } = render(SettingsModal);

    await fireEvent.change(languageSelect(container), { target: { value: 'en' } });
    await fireEvent.click(saveButton(container));

    // The save went all the way through: the dialog closes on success only.
    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledTimes(1);
    expect(h.saveSettings).toHaveBeenCalledWith({ ...h.stored, language: 'en' });
  });
});

// A fresh install stores no language (R-0660). The UI then runs in the system language, but the
// dialog showed "Deutsch" for it, and saving any setting wrote that along: an English system
// switched to German.
describe('SettingsModal — no stored language shows the language the UI runs in (R-0660)', () => {
  let systemLanguageSpy: MockInstance<() => string> | null = null;

  function startWithSystemLanguage(value: string): void {
    systemLanguageSpy = vi.spyOn(navigator, 'language', 'get').mockReturnValue(value);
    h.setStored({ ...h.stored, language: null });
    // What the load of the settings does with them (session.ts hydrate).
    setLanguage(null);
  }

  afterEach(() => {
    systemLanguageSpy?.mockRestore();
    systemLanguageSpy = null;
    h.setStored(h.stored);
  });

  it('shows English on an English system and saves it unchanged', async () => {
    startWithSystemLanguage('en-US');
    settingsModalOpen.set(true);
    const { container } = render(SettingsModal);

    expect(get(language)).toBe('en');
    expect(languageSelect(container).value).toBe('en');
    await fireEvent.click(saveButton(container));

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledExactlyOnceWith({ ...h.stored, language: 'en' });
    expect(get(language)).toBe('en');
  });

  it('shows German on a German system and saves it unchanged', async () => {
    startWithSystemLanguage('de-DE');
    settingsModalOpen.set(true);
    const { container } = render(SettingsModal);

    expect(get(language)).toBe('de');
    expect(languageSelect(container).value).toBe('de');
    await fireEvent.click(saveButton(container));

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledExactlyOnceWith({ ...h.stored, language: 'de' });
    expect(get(language)).toBe('de');
  });
});

// A live spec saved through the first `.sm-panel .btn.primary`. With a session the
// notification prefs in the dialog have a primary button of their own, ahead of the dialog's
// in the DOM; once they had loaded before the spec looked, the spec saved the notification
// prefs, and the change it waited for never happened.
describe('SettingsModal — the dialog save has a hook of its own', () => {
  it('saves through data-action="settings-save" next to the notification prefs', async () => {
    settingsModalOpen.set(true);
    const { container } = render(SettingsModal);
    await waitFor(() =>
      expect(
        [...container.querySelectorAll('.sm-panel .btn.primary')].map((b) => b.textContent?.trim()),
      ).toContain(tNow('notifPrefs.save')),
    );

    await fireEvent.change(languageSelect(container), { target: { value: 'en' } });
    const save = container.querySelector<HTMLButtonElement>(
      '.sm-panel [data-action="settings-save"]',
    );
    expect(save?.textContent?.trim()).toBe(tNow('action.save'));
    await fireEvent.click(save!);

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledWith({ ...h.stored, language: 'en' });
    expect(h.apiProxy).not.toHaveBeenCalledWith('PUT', expect.anything(), expect.anything());
  });
});
