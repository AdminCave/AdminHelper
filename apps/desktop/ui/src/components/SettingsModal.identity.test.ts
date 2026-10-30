// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The identity line in the settings (R-0240): name and expiry of the device
// certificate. A failed renewal at sign-in only reaches the log, so the line is
// where a leaf close to its end, or past it, becomes visible. An unreadable
// certificate gets a fixed line, never the text of the command's error.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { tick } from 'svelte';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { settingsModalOpen } from '$lib/stores/settings';
import { status } from '$lib/stores/statusBar';
import { get } from 'svelte/store';
import type { ResetOutcome } from '$lib/bridge';
import type { DeviceIdentity } from '$lib/bridge/types';

// The line shows the date in local time, so every instant here is built from a
// local time: the expected dates then hold in whatever zone the test runs in.
const MINUTE = 60 * 1000;
const DAY = 24 * 60 * MINUTE;
const NOW = new Date(2027, 0, 1, 12).getTime();

function at(ms: number): string {
  return new Date(ms).toISOString();
}

function localNoon(year: number, month: number, day: number): string {
  return at(new Date(year, month - 1, day, 12).getTime());
}

const h = vi.hoisted(() => ({
  isDeviceEnrolled: vi.fn(async () => true),
  deviceIdentity: vi.fn(async (): Promise<DeviceIdentity | null> => null),
  enrollWithToken: vi.fn(async () => undefined),
  resetDeviceIdentity: vi.fn(async (_serverUrl: string): Promise<ResetOutcome> => 'revoked'),
}));

// Everything but the calls under test fails loudly, as in SettingsModal.enroll.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    isDeviceEnrolled: h.isDeviceEnrolled,
    deviceIdentity: h.deviceIdentity,
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
  const session = { username: 'admin', serverUrl: 'https://srv.example' };
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
vi.mock('./ui/ConfirmDialog.svelte', () => ({ confirmDialog: vi.fn(async () => true) }));

import SettingsModal from './SettingsModal.svelte';

beforeEach(() => {
  setLanguage('de');
  vi.setSystemTime(NOW);
});

afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  vi.clearAllMocks();
  vi.useRealTimers();
  h.isDeviceEnrolled.mockImplementation(async () => true);
  h.deviceIdentity.mockImplementation(async () => null);
  h.enrollWithToken.mockImplementation(async () => undefined);
  h.resetDeviceIdentity.mockImplementation(async () => 'revoked');
});

function identity(name: string, notAfter: string): void {
  h.deviceIdentity.mockImplementation(async () => ({ name, notAfter }));
}

function open(): HTMLElement {
  settingsModalOpen.set(true);
  return render(SettingsModal).container;
}

function el(container: HTMLElement, selector: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(selector);
}

async function line(container: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const found = el(container, '[data-msg="device-identity"]');
    expect(found).not.toBeNull();
    return found!;
  });
}

// Collapses the template's line breaks, keeps everything else: a space before the
// comma would still show.
function text(node: HTMLElement): string {
  return (node.textContent ?? '').replace(/\s+/g, ' ').trim();
}

// Both lookups have answered and the answers have reached the DOM.
async function settled(): Promise<void> {
  await waitFor(() => expect(h.deviceIdentity).toHaveBeenCalled());
  await h.isDeviceEnrolled.mock.results.at(-1)?.value;
  await h.deviceIdentity.mock.results.at(-1)?.value?.catch(() => undefined);
  await tick();
}

describe('SettingsModal — device identity line (R-0240)', () => {
  it.each([
    ['valid', localNoon(2027, 4, 13), 'Registriert als admin bis 13.04.2027'],
    // One minute more than 14 days left: not yet a warning.
    ['valid', at(NOW + 14 * DAY + MINUTE), 'Registriert als admin bis 15.01.2027'],
    [
      'soon',
      at(NOW + 14 * DAY),
      'Registriert als admin bis 15.01.2027, läuft bald ab — die automatische Erneuerung beim Anmelden ist bisher nicht gelungen',
    ],
    [
      'soon',
      at(NOW + MINUTE),
      'Registriert als admin bis 01.01.2027, läuft bald ab — die automatische Erneuerung beim Anmelden ist bisher nicht gelungen',
    ],
    [
      'expired',
      at(NOW - MINUTE),
      'Registriert als admin, abgelaufen am 01.01.2027 — zurücksetzen und mit neuem Token registrieren',
    ],
  ])('%s for a certificate valid until %s', async (state, notAfter, expected) => {
    identity('admin', notAfter);
    const row = await line(open());

    expect(row.dataset.state).toBe(state);
    expect(text(row)).toBe(expected);
    expect(row.querySelector('strong')?.textContent).toBe('admin');
    expect(el(row, '.sm-identity-soon') !== null).toBe(state === 'soon');
  });

  it('says the certificate is unreadable, never what the command said', async () => {
    h.deviceIdentity.mockImplementation(async () => {
      throw new Error('x509 parse error in keyring entry enroll|cert');
    });
    const row = await line(open());

    expect(row.dataset.state).toBe('unreadable');
    expect(text(row)).toBe('Geräte-Zertifikat nicht lesbar — zurücksetzen und neu registrieren');
    expect(row.textContent).not.toContain('x509');
    expect(row.querySelector('strong')).toBeNull();
  });

  it('speaks English with the day-month-year date of en-GB', async () => {
    setLanguage('en');
    identity('admin', localNoon(2027, 4, 13));
    const valid = await line(open());
    expect(text(valid)).toBe('Enrolled as admin until 13/04/2027');
    cleanup();
    settingsModalOpen.set(false);

    identity('admin', at(NOW + 14 * DAY));
    expect(text(await line(open()))).toBe(
      'Enrolled as admin until 15/01/2027, expires soon — the automatic renewal at sign-in has not succeeded yet',
    );
    cleanup();
    settingsModalOpen.set(false);

    identity('admin', localNoon(2026, 12, 31));
    expect(text(await line(open()))).toBe(
      'Enrolled as admin, expired on 31/12/2026 — reset and enroll with a new token',
    );
    cleanup();
    settingsModalOpen.set(false);

    h.deviceIdentity.mockImplementation(async () => {
      throw new Error('no CN');
    });
    expect(text(await line(open()))).toBe('Device certificate unreadable — reset and enroll again');
  });

  it('renders the name as text, not as markup', async () => {
    const name = '<img src="x" onerror="alert(1)">';
    identity(name, localNoon(2027, 4, 13));
    const container = open();
    const row = await line(container);

    expect(row.querySelector('strong')?.textContent).toBe(name);
    expect(container.querySelector('img')).toBeNull();
  });

  it('shows no line without an identity', async () => {
    const container = open();
    await settled();

    expect(el(container, '[data-action="device-reset"]')).not.toBeNull();
    expect(el(container, '[data-msg="device-identity"]')).toBeNull();
  });

  it('shows no line on a device that is not enrolled', async () => {
    // Even with an identity on offer: the line belongs to the enrolled branch only.
    h.isDeviceEnrolled.mockImplementation(async () => false);
    identity('admin', localNoon(2027, 4, 13));
    const container = open();
    await settled();

    expect(el(container, '[data-action="enroll-token"]')).not.toBeNull();
    expect(el(container, '[data-msg="device-identity"]')).toBeNull();
  });

  it('reloads when the settings open again', async () => {
    // The same instance throughout: the app keeps SettingsModal mounted
    // (AppShell.svelte) and only toggles settingsModalOpen.
    identity('admin', localNoon(2027, 4, 13));
    const container = open();
    expect(text(await line(container))).toBe('Registriert als admin bis 13.04.2027');
    settingsModalOpen.set(false);
    await tick();
    expect(el(container, '[data-msg="device-identity"]')).toBeNull();

    identity('admin', localNoon(2027, 7, 12));
    settingsModalOpen.set(true);

    await waitFor(() =>
      expect(text(el(container, '[data-msg="device-identity"]') ?? container)).toBe(
        'Registriert als admin bis 12.07.2027',
      ),
    );
    expect(h.deviceIdentity).toHaveBeenCalledTimes(2);
  });

  it('appears after enrolling from the settings', async () => {
    h.isDeviceEnrolled.mockImplementation(async () => false);
    h.enrollWithToken.mockImplementation(async () => {
      identity('alice', localNoon(2027, 4, 1));
    });
    const container = open();
    const input = await waitFor(() => {
      const found = el(container, '[data-action="enroll-token"]');
      expect(found).not.toBeNull();
      return found!;
    });
    await settled();
    expect(el(container, '[data-msg="device-identity"]')).toBeNull();

    await fireEvent.input(input, { target: { value: 'tok-1' } });
    await fireEvent.click(el(container, '[data-action="enroll-submit"]')!);

    expect(text(await line(container))).toBe('Registriert als alice bis 01.04.2027');
  });

  it('is gone after a reset, and the reset reloads it', async () => {
    identity('admin', localNoon(2027, 4, 13));
    h.resetDeviceIdentity.mockImplementation(async () => {
      h.deviceIdentity.mockImplementation(async () => null);
      return 'revoked';
    });
    const container = open();
    await line(container);
    expect(h.deviceIdentity).toHaveBeenCalledTimes(1);

    await fireEvent.click(el(container, '[data-action="device-reset"]')!);

    await waitFor(() => expect(el(container, '[data-action="enroll-token"]')).not.toBeNull());
    expect(el(container, '[data-msg="device-identity"]')).toBeNull();
    await waitFor(() => expect(h.deviceIdentity).toHaveBeenCalledTimes(2));
  });

  // The identity is deleted before the pin; a reset that fails at the pin leaves none.
  it('shows the device as not enrolled after a failed reset that deleted the identity', async () => {
    identity('admin', localNoon(2027, 4, 13));
    h.resetDeviceIdentity.mockImplementation(async () => {
      h.isDeviceEnrolled.mockImplementation(async () => false);
      h.deviceIdentity.mockImplementation(async () => null);
      throw new Error('the pinned certificate could not be removed from the keyring');
    });
    const container = open();
    await line(container);

    await fireEvent.click(el(container, '[data-action="device-reset"]')!);

    await waitFor(() => expect(el(container, '[data-action="enroll-token"]')).not.toBeNull());
    expect(el(container, '[data-msg="device-identity"]')).toBeNull();
    expect(get(status)).toMatchObject({
      isError: true,
      text: expect.stringContaining('could not be removed from the keyring'),
    });
  });
});
