// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Login under enforced mTLS without a device certificate (R-0222): the gateway
// answers 400, which the backend reports as ERR_MTLS_CERT_REQUIRED (auth.rs).
// Instead of the raw text the login screen names the cause and offers the way
// out, the one-time token form.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

const UNKNOWN_ISSUER =
  'ERR_TLS_UNKNOWN_ISSUER: AdminHelper: Das Server-Zertifikat stammt nicht von einer öffentlich vertrauenswürdigen CA.';
const MTLS_REQUIRED =
  'ERR_MTLS_CERT_REQUIRED: The server requires a device certificate (mTLS is enforced). Enroll this device with a one-time enrollment token from your administrator.';

const h = vi.hoisted(() => ({
  login: vi.fn(),
  setMode: vi.fn(async () => {}),
  setAllowSelfSignedCerts: vi.fn(async () => {}),
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: vi.fn(),
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
vi.mock('@tauri-apps/plugin-dialog', () => ({ confirm: vi.fn(async () => true) }));

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

describe('Login — device certificate required (ERR_MTLS_CERT_REQUIRED)', () => {
  it('names the cause instead of the raw text and leads to the token form', async () => {
    h.login.mockRejectedValueOnce(MTLS_REQUIRED);
    const { container } = render(Login);

    await submitLogin(container);

    const hint = await waitFor(() => {
      const el = container.querySelector('[data-msg="mtls-required"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(hint.textContent).toContain('Geräte-Zertifikat');
    expect(container.textContent).not.toContain('ERR_MTLS_CERT_REQUIRED');
    expect(container.textContent).not.toContain('one-time enrollment token');

    await fireEvent.click(container.querySelector('[data-action="mtls-enroll"]')!);

    await waitFor(() =>
      expect(
        container.querySelector('input[placeholder="Token vom Administrator"]'),
      ).not.toBeNull(),
    );
    expect(container.querySelector('[data-msg="mtls-required"]')).toBeNull();
  });

  it('shows the hint when the retry after the trust dialog meets the enforced gateway', async () => {
    // A standard install: the first contact asks to trust the own-PKI leaf, and
    // the retry then reaches the gateway, which turns the certless device away.
    h.login.mockRejectedValueOnce(UNKNOWN_ISSUER).mockRejectedValueOnce(MTLS_REQUIRED);
    const { container, queryByTestId } = render(Login);

    await submitLogin(container);
    await waitFor(() => expect(queryByTestId('trust-dialog')).not.toBeNull());
    await fireEvent.click(container.querySelector('[data-action="trust-accept"]')!);

    await waitFor(() =>
      expect(container.querySelector('[data-msg="mtls-required"]')).not.toBeNull(),
    );
    expect(h.login).toHaveBeenCalledTimes(2);
    expect(container.textContent).not.toContain('ERR_MTLS_CERT_REQUIRED');
  });

  it('shows any other login failure as text, without the hint', async () => {
    h.login.mockRejectedValueOnce('Login fehlgeschlagen (401 Unauthorized): invalid credentials');
    const { container } = render(Login);

    await submitLogin(container);

    await waitFor(() =>
      expect(container.querySelector('.login-error')?.textContent).toContain(
        'Login fehlgeschlagen (401 Unauthorized)',
      ),
    );
    expect(container.querySelector('[data-msg="mtls-required"]')).toBeNull();
    expect(container.querySelector('[data-action="mtls-enroll"]')).toBeNull();
  });
});
