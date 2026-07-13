// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Trust dialog for ERR_TLS_UNKNOWN_ISSUER: the standard install serves an
// own-PKI gateway leaf, so the very first login/enrollment fails public-CA
// validation by design. Instead of a dead-end error the login screen must ask
// whether to trust the server (TOFU), persist the opt-in BEFORE retrying, and
// on decline show the human-readable message without the machine code.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

const UNKNOWN_ISSUER =
  'ERR_TLS_UNKNOWN_ISSUER: AdminHelper: Das Server-Zertifikat stammt nicht von einer öffentlich vertrauenswürdigen CA.';

const h = vi.hoisted(() => ({
  login: vi.fn(),
  setMode: vi.fn(async () => {}),
  setAllowSelfSignedCerts: vi.fn(),
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: vi.fn(),
}));

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  const settings = writable({
    mode: 'server',
    serverUrl: '',
    lastUsername: '',
    allowSelfSignedCerts: false,
  });
  // Mirror the real store contract: persisting flips the store value, which is
  // what the retry reads — the test proves the persist-before-retry ordering.
  h.setAllowSelfSignedCerts.mockImplementation(async (allow: boolean) => {
    settings.update((s) => ({ ...s, allowSelfSignedCerts: allow }));
  });
  return {
    login: h.login,
    setMode: h.setMode,
    setAllowSelfSignedCerts: h.setAllowSelfSignedCerts,
    settings,
  };
});
vi.mock('$lib/bridge', () => ({
  enrollWithToken: h.enrollWithToken,
  resetServerCertPin: h.resetServerCertPin,
  resetDeviceIdentity: h.resetDeviceIdentity,
}));
vi.mock('@tauri-apps/plugin-dialog', () => ({ confirm: vi.fn(async () => true) }));

import Login from './Login.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function submitEnroll(container: HTMLElement): Promise<void> {
  await fireEvent.click(container.querySelector('[data-action="enroll-switch"]')!);
  const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
  const token = container.querySelector<HTMLInputElement>('input[type="text"]')!;
  await fireEvent.input(url, { target: { value: 'https://srv.example' } });
  await fireEvent.input(token, { target: { value: 'tok-1' } });
  await fireEvent.submit(container.querySelector('form')!);
}

describe('Login — trust dialog (ERR_TLS_UNKNOWN_ISSUER)', () => {
  it('opens the dialog instead of a dead-end error when enrollment hits an unknown issuer', async () => {
    h.enrollWithToken.mockRejectedValueOnce(UNKNOWN_ISSUER);
    const { container, queryByTestId } = render(Login);

    await submitEnroll(container);

    await waitFor(() => expect(queryByTestId('trust-dialog')).not.toBeNull());
    // The first attempt honoured the (off) setting.
    expect(h.enrollWithToken).toHaveBeenCalledWith('https://srv.example', 'tok-1', false);
    // No inline error while the dialog is open.
    expect(container.querySelector('.login-error')).toBeNull();
  });

  it('persists the opt-in, then retries the enrollment with self-signed allowed', async () => {
    h.enrollWithToken.mockRejectedValueOnce(UNKNOWN_ISSUER).mockResolvedValueOnce(undefined);
    const { container, queryByTestId } = render(Login);

    await submitEnroll(container);
    await waitFor(() => expect(queryByTestId('trust-dialog')).not.toBeNull());

    await fireEvent.click(container.querySelector('[data-action="trust-accept"]')!);

    await waitFor(() => expect(h.enrollWithToken).toHaveBeenCalledTimes(2));
    expect(h.setAllowSelfSignedCerts).toHaveBeenCalledWith(true);
    // The retry ran AFTER the persisted opt-in flipped the store.
    expect(h.enrollWithToken).toHaveBeenLastCalledWith('https://srv.example', 'tok-1', true);
    expect(queryByTestId('trust-dialog')).toBeNull();
  });

  it('shows the message without the machine code when the user declines', async () => {
    h.enrollWithToken.mockRejectedValueOnce(UNKNOWN_ISSUER);
    const { container, queryByTestId } = render(Login);

    await submitEnroll(container);
    await waitFor(() => expect(queryByTestId('trust-dialog')).not.toBeNull());

    await fireEvent.click(container.querySelector('[data-action="trust-cancel"]')!);

    await waitFor(() => expect(queryByTestId('trust-dialog')).toBeNull());
    const inline = container.querySelector('.login-error');
    expect(inline?.textContent).toContain('nicht von einer öffentlich vertrauenswürdigen CA');
    expect(inline?.textContent).not.toContain('ERR_TLS_UNKNOWN_ISSUER');
    expect(h.setAllowSelfSignedCerts).not.toHaveBeenCalled();
  });

  it('also guards the login path and retries it after consent', async () => {
    h.login.mockRejectedValueOnce(UNKNOWN_ISSUER).mockResolvedValueOnce(undefined);
    const { container, queryByTestId } = render(Login);

    const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
    const user = container.querySelector<HTMLInputElement>('input[type="text"]')!;
    const pass = container.querySelector<HTMLInputElement>('input[type="password"]')!;
    await fireEvent.input(url, { target: { value: 'https://srv.example' } });
    await fireEvent.input(user, { target: { value: 'admin' } });
    await fireEvent.input(pass, { target: { value: 'pw' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(queryByTestId('trust-dialog')).not.toBeNull());
    await fireEvent.click(container.querySelector('[data-action="trust-accept"]')!);

    await waitFor(() => expect(h.login).toHaveBeenCalledTimes(2));
    expect(h.setAllowSelfSignedCerts).toHaveBeenCalledWith(true);
  });

  it('leaves other errors on the inline path — no dialog', async () => {
    h.enrollWithToken.mockRejectedValueOnce('Enrollment am ca-issuer fehlgeschlagen (401)');
    const { container, queryByTestId } = render(Login);

    await submitEnroll(container);

    await waitFor(() =>
      expect(container.querySelector('.login-error')?.textContent).toContain('401'),
    );
    expect(queryByTestId('trust-dialog')).toBeNull();
  });
});
