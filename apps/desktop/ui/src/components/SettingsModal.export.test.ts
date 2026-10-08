// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Browser-certificate export (R-0219): the settings check the password the way
// the backend does — at least 12 characters, counted as code points like Rust's
// chars(). A shorter one used to pass the old 8-character check, reach
// check_export_password and come back only as the generic export error.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { settingsModalOpen } from '$lib/stores/settings';

const DEST = '/home/user/adminhelper-browser.p12';

const h = vi.hoisted(() => ({
  exportBrowserP12: vi.fn(async () => '/home/user/adminhelper-browser.p12'),
  isDeviceEnrolled: vi.fn(async () => false),
  save: vi.fn(async () => '/home/user/adminhelper-browser.p12'),
}));

// Everything but the two calls under test fails loudly, as in mount.smoke.test.ts:
// NotificationPrefs catches its own failed loads.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    exportBrowserP12: h.exportBrowserP12,
    isDeviceEnrolled: h.isDeviceEnrolled,
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
  const { readable } = await import('svelte/store');
  const settings = {
    mode: 'server',
    url: null,
    intervalMinutes: 5,
    serverUrl: 'https://srv.example',
    allowSelfSignedCerts: false,
  };
  const session = { username: 'admin', serverUrl: 'https://srv.example', token: 'jwt-1' };
  return {
    sessionStore: readable({ settings, session, ready: true }),
    settings: readable(settings),
    session: readable(session),
    currentSession: () => session,
  };
});

vi.mock('@tauri-apps/plugin-dialog', () => ({ save: h.save, confirm: vi.fn(async () => true) }));

import SettingsModal from './SettingsModal.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  vi.clearAllMocks();
});

async function exportWith(password: string): Promise<HTMLElement> {
  settingsModalOpen.set(true);
  const { container } = render(SettingsModal);
  const input = await waitFor(() => {
    const el = container.querySelector<HTMLInputElement>('[data-action="browser-cert-password"]');
    expect(el).not.toBeNull();
    return el!;
  });
  await fireEvent.input(input, { target: { value: password } });
  await fireEvent.click(container.querySelector('[data-action="browser-cert-export"]')!);
  return container;
}

function message(container: HTMLElement): string {
  return container.querySelector('.sm-browser-cert-msg')?.textContent ?? '';
}

describe('SettingsModal — browser-certificate export password (R-0219)', () => {
  it('refuses 11 characters with the 12-character message, before any dialog or export', async () => {
    const container = await exportWith('a'.repeat(11));

    await waitFor(() => expect(message(container)).toContain('12 Zeichen'));
    expect(h.save).not.toHaveBeenCalled();
    expect(h.exportBrowserP12).not.toHaveBeenCalled();
  });

  it('exports with 12 characters', async () => {
    const password = 'b'.repeat(12);
    await exportWith(password);

    await waitFor(() =>
      expect(h.exportBrowserP12).toHaveBeenCalledWith(
        'https://srv.example',
        'jwt-1',
        password,
        DEST,
        false,
      ),
    );
    expect(h.save).toHaveBeenCalledTimes(1);
  });

  it('counts characters like the backend: 6 outside the BMP are 6, not 12', async () => {
    const container = await exportWith('\u{1F512}'.repeat(6));

    await waitFor(() => expect(message(container)).toContain('12 Zeichen'));
    expect(h.save).not.toHaveBeenCalled();
    expect(h.exportBrowserP12).not.toHaveBeenCalled();
  });
});
