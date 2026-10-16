// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The settings ask before a reset in the app's own dialog (R-0395); the native one
// was refused by the capabilities and the button did nothing. The dialog sits in
// App's layer, outside the settings overlay, but the focus stays on the reset
// button inside it: an Escape there closes the question, not the settings under
// it. The other SettingsModal tests mock confirmDialog; this one renders the real
// dialog beside the settings.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import { settingsModalOpen } from '$lib/stores/settings';
import type { ResetOutcome } from '$lib/bridge';

const h = vi.hoisted(() => ({
  isDeviceEnrolled: vi.fn(async () => true),
  deviceIdentity: vi.fn(async () => null),
  resetDeviceIdentity: vi.fn(async (_serverUrl: string): Promise<ResetOutcome> => 'revoked'),
}));

// Everything but the calls under test fails loudly, as in SettingsModal.enroll.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    isDeviceEnrolled: h.isDeviceEnrolled,
    deviceIdentity: h.deviceIdentity,
    resetDeviceIdentity: h.resetDeviceIdentity,
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

vi.mock('$lib/stores/tunnel', () => ({
  startIfServerMode: vi.fn(async () => undefined),
  stop: vi.fn(async () => undefined),
}));

vi.mock('@tauri-apps/plugin-dialog', () => ({ save: vi.fn(async () => null) }));

import SettingsModal from './SettingsModal.svelte';
import ConfirmDialog from './ui/ConfirmDialog.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  vi.clearAllMocks();
});

// The settings and, in its own container as in App's layer, the dialog.
function open(): { settings: HTMLElement; layer: HTMLElement } {
  settingsModalOpen.set(true);
  const settings = render(SettingsModal).container;
  const layer = render(ConfirmDialog).container;
  return { settings, layer };
}

async function resetButton(settings: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const found = settings.querySelector<HTMLElement>('[data-action="device-reset"]');
    expect(found).not.toBeNull();
    return found!;
  });
}

function question(layer: HTMLElement): HTMLElement | null {
  return layer.querySelector<HTMLElement>('[role="dialog"]');
}

// Clicks the reset and returns the question it raises.
async function ask(settings: HTMLElement, layer: HTMLElement): Promise<HTMLElement> {
  await fireEvent.click(await resetButton(settings));
  return waitFor(() => {
    const found = question(layer);
    expect(found).not.toBeNull();
    return found!;
  });
}

function buttonIn(dialog: HTMLElement, label: string): HTMLButtonElement {
  const found = [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === label,
  );
  expect(found).toBeDefined();
  return found!;
}

describe('SettingsModal — the reset question in the app dialog (R-0395)', () => {
  it('asks first, and its confirm button resets', async () => {
    const { settings, layer } = open();
    const dialog = await ask(settings, layer);
    expect(dialog.textContent).toContain(tNow('settings.resetDeviceId.confirm'));
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();

    await fireEvent.click(buttonIn(dialog, tNow('settings.resetDeviceId')));

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example'));
    await waitFor(() =>
      expect(settings.querySelector('[data-msg="device-reset"]')?.textContent).toContain(
        tNow('settings.resetDeviceId.done'),
      ),
    );
    expect(question(layer)).toBeNull();
  });

  it('cancelling closes the question and resets nothing', async () => {
    const { settings, layer } = open();
    const dialog = await ask(settings, layer);

    await fireEvent.click(buttonIn(dialog, tNow('action.cancel')));

    await waitFor(() => expect(question(layer)).toBeNull());
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
    expect(get(settingsModalOpen)).toBe(true);
    expect(settings.querySelector('[data-action="device-reset"]')).not.toBeNull();
  });

  it('Escape closes the question only, the settings stay open', async () => {
    const { settings, layer } = open();
    await ask(settings, layer);

    // Where the focus stays after the click: the reset button inside the overlay.
    await fireEvent.keyDown(await resetButton(settings), { key: 'Escape' });

    await waitFor(() => expect(question(layer)).toBeNull());
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
    expect(get(settingsModalOpen)).toBe(true);
    expect(settings.querySelector('.sm-overlay')).not.toBeNull();
  });

  it('Escape without a question still closes the settings', async () => {
    const { settings } = open();

    await fireEvent.keyDown(await resetButton(settings), { key: 'Escape' });

    expect(get(settingsModalOpen)).toBe(false);
    await waitFor(() => expect(settings.querySelector('.sm-overlay')).toBeNull());
  });
});
