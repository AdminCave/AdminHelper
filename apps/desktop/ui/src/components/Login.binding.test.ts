// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Under mTLS the device certificate belongs to one user (R-0223): signing in as
// another one is refused with ERR_CERT_USER_MISMATCH. The login screen names that
// instead of the raw text and offers to reset the device identity, so the device
// can be registered for the user who signs in.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { withoutErrorCodes } from '$lib/utils/errors';

// What auth.rs makes of the server's 403: the status and the body around the code.
const MISMATCH =
  'Login fehlgeschlagen (403 Forbidden): {"detail":"ERR_CERT_USER_MISMATCH: The client certificate belongs to another user. Sign in as that user, or register this device for yourself."}';

const h = vi.hoisted(() => ({
  login: vi.fn(),
  setMode: vi.fn(async () => {}),
  setAllowSelfSignedCerts: vi.fn(async () => {}),
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: vi.fn(async () => {}),
  confirm: vi.fn(async () => true),
}));

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    login: h.login,
    setMode: h.setMode,
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
vi.mock('@tauri-apps/plugin-dialog', () => ({ confirm: h.confirm }));

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

describe('Login — device certificate of another user (ERR_CERT_USER_MISMATCH)', () => {
  it('names the cause and offers the reset, without the code', async () => {
    h.login.mockRejectedValueOnce(new Error(MISMATCH));
    const { container } = render(Login);
    await submitLogin(container);

    await waitFor(() =>
      expect(container.querySelector('[data-msg="cert-user-mismatch"]')?.textContent).toContain(
        'für einen anderen Benutzer registriert',
      ),
    );
    expect(container.querySelector('[data-action="cert-user-reset"]')).not.toBeNull();
    expect(container.textContent).not.toContain('ERR_CERT_USER_MISMATCH');
  });

  it('the reset drops the device identity of this server after confirming', async () => {
    h.login.mockRejectedValueOnce(new Error(MISMATCH));
    const { container } = render(Login);
    await submitLogin(container);
    const reset = await waitFor(() => {
      const el = container.querySelector<HTMLButtonElement>('[data-action="cert-user-reset"]');
      expect(el).not.toBeNull();
      return el!;
    });

    await fireEvent.click(reset);

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example'));
    expect(h.confirm).toHaveBeenCalledTimes(1);
    expect(h.resetServerCertPin).not.toHaveBeenCalled();
    await waitFor(() => expect(container.textContent).toContain('Geräte-Identität zurückgesetzt'));
  });

  it('shows any other login failure as text, without the hint', async () => {
    h.login.mockRejectedValueOnce(new Error('Login fehlgeschlagen (401 Unauthorized): nope'));
    const { container } = render(Login);
    await submitLogin(container);

    await waitFor(() => expect(container.textContent).toContain('nope'));
    expect(container.querySelector('[data-msg="cert-user-mismatch"]')).toBeNull();
  });

  it('the code never reaches a message the user reads', () => {
    expect(withoutErrorCodes(MISMATCH)).not.toContain('ERR_');
  });
});
