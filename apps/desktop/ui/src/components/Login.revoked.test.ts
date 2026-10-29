// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A device certificate the server no longer admits is refused with ERR_CERT_REVOKED
// (R-0224). The login screen names that and offers the reset, without the raw code.
// A reset tells whether the server revoked the device or it was deleted here only.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import { IpcError, withoutErrorCodes } from '$lib/utils/errors';
import type { ResetOutcome } from '$lib/bridge';

// What auth.rs makes of the server's 403.
const REVOKED = new IpcError(
  'This device certificate is no longer valid. Reset the device identity and register the device again.',
  'ERR_CERT_REVOKED',
  403,
);
const MISMATCH = new IpcError(
  'The client certificate belongs to another user. Sign in as that user, or register this device for yourself.',
  'ERR_CERT_USER_MISMATCH',
  403,
);
// The text of the 403 with the code in it, as a client without `code` showed it.
const REVOKED_TEXT =
  'Login fehlgeschlagen (403 Forbidden): {"detail":"ERR_CERT_REVOKED: This device certificate is no longer valid. Reset the device identity and register the device again."}';

const h = vi.hoisted(() => ({
  login: vi.fn(),
  setAllowSelfSignedCerts: vi.fn(async () => {}),
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: vi.fn(async (_serverUrl: string): Promise<ResetOutcome> => 'revoked'),
  confirmDialog: vi.fn(async () => true),
}));

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    login: h.login,
    setAllowSelfSignedCerts: h.setAllowSelfSignedCerts,
    settings: writable({
      mode: 'server',
      serverUrl: '',
      lastUsername: '',
      allowSelfSignedCerts: false,
    }),
  };
});
vi.mock('$lib/bridge', () => ({
  enrollWithToken: h.enrollWithToken,
  resetServerCertPin: h.resetServerCertPin,
  resetDeviceIdentity: h.resetDeviceIdentity,
}));
vi.mock('./ui/ConfirmDialog.svelte', () => ({ confirmDialog: h.confirmDialog }));

import Login from './Login.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function submitLogin(container: HTMLElement): Promise<void> {
  const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
  const user = container.querySelector<HTMLInputElement>('input[type="text"]')!;
  const pass = container.querySelector<HTMLInputElement>('input[type="password"]')!;
  await fireEvent.input(url, { target: { value: 'https://srv.example' } });
  await fireEvent.input(user, { target: { value: 'alice' } });
  await fireEvent.input(pass, { target: { value: 'secret' } });
  await fireEvent.submit(container.querySelector('form')!);
}

async function button(container: HTMLElement, action: string): Promise<HTMLButtonElement> {
  return waitFor(() => {
    const el = container.querySelector<HTMLButtonElement>(`[data-action="${action}"]`);
    expect(el).not.toBeNull();
    return el!;
  });
}

describe('Login — device certificate no longer valid (ERR_CERT_REVOKED)', () => {
  it('names the cause and offers the reset, without the code', async () => {
    h.login.mockRejectedValueOnce(REVOKED);
    const { container } = render(Login);
    await submitLogin(container);

    await waitFor(() =>
      expect(container.querySelector('[data-msg="cert-revoked"]')?.textContent).toContain(
        'gilt nicht mehr',
      ),
    );
    expect(container.querySelector('[data-action="cert-revoked-reset"]')).not.toBeNull();
    expect(container.textContent).not.toContain('ERR_CERT_REVOKED');
  });

  it('the reset drops the device identity and says to register again', async () => {
    h.login.mockRejectedValueOnce(REVOKED);
    const { container } = render(Login);
    await submitLogin(container);
    await fireEvent.click(await button(container, 'cert-revoked-reset'));

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example'));
    await waitFor(() => expect(container.textContent).toContain('mit einem Einmal-Token neu'));
    expect(container.textContent).not.toContain('Nur auf diesem Gerät');
  });

  it('asks in the app dialog first, the reset on its confirm button', async () => {
    h.login.mockRejectedValueOnce(REVOKED);
    const { container } = render(Login);
    await submitLogin(container);
    await fireEvent.click(await button(container, 'cert-revoked-reset'));

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example'));
    expect(h.confirmDialog).toHaveBeenCalledTimes(1);
    expect(h.confirmDialog).toHaveBeenCalledWith(tNow('login.certRevoked.confirm'), {
      confirmLabel: tNow('login.resetDeviceId'),
    });
  });

  it('a cancelled question resets nothing and keeps the hint', async () => {
    h.login.mockRejectedValueOnce(REVOKED);
    h.confirmDialog.mockResolvedValueOnce(false);
    const { container } = render(Login);
    await submitLogin(container);
    await fireEvent.click(await button(container, 'cert-revoked-reset'));

    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(1));
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
    expect(container.querySelector('[data-msg="cert-revoked"]')).not.toBeNull();
  });
});

describe('Login — a reset the server could not take', () => {
  it('says the old certificate was deleted on this device only', async () => {
    h.login.mockRejectedValueOnce(MISMATCH);
    h.resetDeviceIdentity.mockResolvedValueOnce('localOnly');
    const { container } = render(Login);
    await submitLogin(container);
    await fireEvent.click(await button(container, 'cert-user-reset'));

    await waitFor(() => expect(container.textContent).toContain('Geräte-Identität zurückgesetzt'));
    expect(container.textContent).toContain('Nur auf diesem Gerät');
  });
});

describe('Login — a reset after a pinned-CA mismatch', () => {
  it('adds the hint when the server did not revoke the device', async () => {
    h.login.mockRejectedValueOnce(
      new IpcError(
        'Login fehlgeschlagen: ERR_CA_PIN_MISMATCH: Server-CA passt nicht',
        'ERR_CA_PIN_MISMATCH',
      ),
    );
    h.resetDeviceIdentity.mockResolvedValueOnce('localOnly');
    const { container } = render(Login);
    await submitLogin(container);
    const reset = await waitFor(() => {
      const found = [...container.querySelectorAll<HTMLButtonElement>('button')].find(
        (b) => b.textContent?.trim() === 'Geräte-Identität zurücksetzen',
      );
      expect(found).toBeDefined();
      return found!;
    });
    await fireEvent.click(reset);

    await waitFor(() => expect(container.textContent).toContain('Vertrauen zurückgesetzt'));
    expect(container.textContent).toContain('Nur auf diesem Gerät');
  });
});

it('the code never reaches a message the user reads', () => {
  expect(withoutErrorCodes(REVOKED_TEXT)).not.toContain('ERR_');
});

describe('Login — a text that only names ERR_CERT_REVOKED', () => {
  it('shows the text, without the hint', async () => {
    h.login.mockRejectedValueOnce(
      new IpcError('Login fehlgeschlagen: ERR_CERT_REVOKED: x', 'ERR_HTTP', 403),
    );
    const { container } = render(Login);
    await submitLogin(container);

    await waitFor(() =>
      expect(container.querySelector('.login-error')?.textContent).toContain(
        'Login fehlgeschlagen',
      ),
    );
    expect(container.querySelector('[data-msg="cert-revoked"]')).toBeNull();
    expect(container.querySelector('[data-action="cert-revoked-reset"]')).toBeNull();
  });
});
