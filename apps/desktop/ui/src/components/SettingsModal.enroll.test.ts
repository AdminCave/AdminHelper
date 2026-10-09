// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Enrolling from the settings (R-0212): in server mode a device without an
// identity gets the token field, one with an identity only the reset. A
// successful enrollment starts the tunnel, because frpc reads the identity only
// when it starts. The reset message used to sit in the branch that disappears
// on success, so nobody ever saw it.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { settingsModalOpen } from '$lib/stores/settings';

const h = vi.hoisted(() => ({
  isDeviceEnrolled: vi.fn(async () => false),
  enrollWithToken: vi.fn(async () => undefined),
  resetDeviceIdentity: vi.fn(async () => undefined),
  startIfServerMode: vi.fn(async () => undefined),
}));

// Everything but the calls under test fails loudly, as in SettingsModal.export.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    isDeviceEnrolled: h.isDeviceEnrolled,
    enrollWithToken: h.enrollWithToken,
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

vi.mock('$lib/stores/tunnel', () => ({ startIfServerMode: h.startIfServerMode }));

vi.mock('@tauri-apps/plugin-dialog', () => ({
  save: vi.fn(async () => null),
  confirm: vi.fn(async () => true),
}));

import SettingsModal from './SettingsModal.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  vi.clearAllMocks();
  h.isDeviceEnrolled.mockImplementation(async () => false);
});

function open(): HTMLElement {
  settingsModalOpen.set(true);
  return render(SettingsModal).container;
}

function el(container: HTMLElement, selector: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(selector);
}

async function enroll(container: HTMLElement, token: string): Promise<void> {
  const input = await waitFor(() => {
    const found = el(container, '[data-action="enroll-token"]');
    expect(found).not.toBeNull();
    return found!;
  });
  await fireEvent.input(input, { target: { value: token } });
  await fireEvent.click(el(container, '[data-action="enroll-submit"]')!);
}

describe('SettingsModal — enroll from the settings (R-0212)', () => {
  it('shows the token field and no reset when the device has no identity', async () => {
    const container = open();

    await waitFor(() => expect(el(container, '[data-action="enroll-token"]')).not.toBeNull());
    expect(el(container, '[data-action="device-reset"]')).toBeNull();
  });

  it('enrolls with the session server, the token and the self-signed setting', async () => {
    const container = open();
    await enroll(container, '  tok-1  ');

    await waitFor(() =>
      expect(h.enrollWithToken).toHaveBeenCalledWith('https://srv.example', 'tok-1', false),
    );
  });

  it('after success shows the reset and the message, and starts the tunnel', async () => {
    const container = open();
    await enroll(container, 'tok-1');

    await waitFor(() => expect(el(container, '[data-action="device-reset"]')).not.toBeNull());
    expect(el(container, '[data-action="enroll-token"]')).toBeNull();
    expect(el(container, '[data-msg="enroll"]')?.textContent).toContain('Gerät registriert');
    await waitFor(() => expect(h.startIfServerMode).toHaveBeenCalledTimes(1));
  });

  it('shows a failure inline, keeps the field and leaves the tunnel alone', async () => {
    h.enrollWithToken.mockRejectedValueOnce(new Error('token already used'));
    const container = open();
    await enroll(container, 'tok-1');

    await waitFor(() =>
      expect(el(container, '[data-msg="enroll"]')?.textContent).toContain('token already used'),
    );
    expect(el(container, '[data-action="enroll-token"]')).not.toBeNull();
    expect(el(container, '[data-action="device-reset"]')).toBeNull();
    expect(h.startIfServerMode).not.toHaveBeenCalled();
  });

  it('offers only the reset when the device has an identity', async () => {
    h.isDeviceEnrolled.mockImplementation(async () => true);
    const container = open();

    await waitFor(() => expect(el(container, '[data-action="device-reset"]')).not.toBeNull());
    expect(el(container, '[data-action="enroll-token"]')).toBeNull();
  });

  it('after a reset shows its message and the token field', async () => {
    h.isDeviceEnrolled.mockImplementation(async () => true);
    const container = open();
    const reset = await waitFor(() => {
      const found = el(container, '[data-action="device-reset"]');
      expect(found).not.toBeNull();
      return found!;
    });
    await fireEvent.click(reset);

    await waitFor(() => expect(el(container, '[data-action="enroll-token"]')).not.toBeNull());
    expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example');
    expect(el(container, '[data-msg="device-reset"]')?.textContent).toContain(
      'Geräte-Identität zurückgesetzt',
    );
  });
});
