// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A pinned-certificate mismatch is a dead end on the login screen unless it offers the
// matching reset (R-0276): the self-signed leaf case resets the pin, the enrolled-CA
// case the device identity. Both hang on the codes in the backend's message, so the
// login has to see them even where the user reads the message without them.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { IpcError } from '$lib/utils/errors';
import type { ResetOutcome } from '$lib/bridge';

// What a pin verifier leaves at the end of the reqwest source chain (error.rs).
const TOFU = new IpcError(
  'error sending request: client error (Connect): ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für srv.example hat sich geändert',
  'ERR_TOFU_PIN_MISMATCH',
);
const CA = new IpcError(
  'error sending request: client error (Connect): ERR_CA_PIN_MISMATCH: AdminHelper: Das Server-Zertifikat wird nicht mehr von der gepinnten CA gedeckt (mögliche MITM-Attacke)',
  'ERR_CA_PIN_MISMATCH',
);

const RESET_PIN = 'Gepinntes Server-Zertifikat zurücksetzen';
const RESET_IDENTITY = 'Geräte-Identität zurücksetzen';

const h = vi.hoisted(() => ({
  login: vi.fn(),
  setAllowSelfSignedCerts: vi.fn(async () => {}),
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(async (_serverUrl: string) => {}),
  resetDeviceIdentity: vi.fn(async (_serverUrl: string): Promise<ResetOutcome> => 'revoked'),
  confirmDialog: vi.fn(async (_message: string, _options?: unknown) => true),
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

async function submitEnroll(container: HTMLElement): Promise<void> {
  await fireEvent.click(container.querySelector('[data-action="enroll-switch"]')!);
  const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
  const token = container.querySelector<HTMLInputElement>('input[type="text"]')!;
  await fireEvent.input(url, { target: { value: 'https://srv.example' } });
  await fireEvent.input(token, { target: { value: 'tok-1' } });
  await fireEvent.submit(container.querySelector('form')!);
}

function buttonsLabelled(container: HTMLElement, label: string): HTMLButtonElement[] {
  return [...container.querySelectorAll<HTMLButtonElement>('button')].filter(
    (b) => b.textContent?.trim() === label,
  );
}

async function reset(container: HTMLElement, label: string): Promise<HTMLButtonElement> {
  return waitFor(() => {
    const [found] = buttonsLabelled(container, label);
    expect(found).toBeDefined();
    return found;
  });
}

describe('Login — a changed self-signed server certificate (ERR_TOFU_PIN_MISMATCH)', () => {
  it('offers to reset the pin, warns first, and resets only the pin', async () => {
    h.login.mockRejectedValueOnce(TOFU);
    const { container } = render(Login);
    await submitLogin(container);

    const button = await reset(container, RESET_PIN);
    expect(container.textContent).toContain('AdminHelper TOFU: Das Server-Zertifikat');
    expect(container.textContent).not.toContain('ERR_');
    await fireEvent.click(button);

    await waitFor(() => expect(h.resetServerCertPin).toHaveBeenCalledWith('https://srv.example'));
    expect(h.confirmDialog.mock.calls[0][0]).toContain('MITM');
    // The confirm button names the action of the button that raised the question.
    expect(h.confirmDialog.mock.calls[0][1]).toEqual({ confirmLabel: RESET_PIN });
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
    await waitFor(() => expect(container.textContent).toContain('Vertrauen zurückgesetzt'));
  });

  it('offers the same reset when the token registration hits it', async () => {
    h.enrollWithToken.mockRejectedValueOnce(TOFU);
    const { container } = render(Login);
    await submitEnroll(container);

    await fireEvent.click(await reset(container, RESET_PIN));
    await waitFor(() => expect(h.resetServerCertPin).toHaveBeenCalledWith('https://srv.example'));
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
  });

  it('resets nothing when the warning is declined', async () => {
    h.login.mockRejectedValueOnce(TOFU);
    h.confirmDialog.mockResolvedValueOnce(false);
    const { container } = render(Login);
    await submitLogin(container);

    await fireEvent.click(await reset(container, RESET_PIN));
    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(1));
    expect(h.resetServerCertPin).not.toHaveBeenCalled();
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
    expect(buttonsLabelled(container, RESET_PIN)).toHaveLength(1);
  });
});

describe('Login — a server certificate the enrolled CA no longer covers (ERR_CA_PIN_MISMATCH)', () => {
  it('offers to reset the device identity and resets that, not the pin alone', async () => {
    h.login.mockRejectedValueOnce(CA);
    const { container } = render(Login);
    await submitLogin(container);

    const button = await reset(container, RESET_IDENTITY);
    expect(buttonsLabelled(container, RESET_PIN)).toHaveLength(0);
    expect(container.textContent).not.toContain('ERR_');
    await fireEvent.click(button);

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example'));
    expect(h.confirmDialog.mock.calls[0][0]).toContain('MITM');
    expect(h.confirmDialog.mock.calls[0][1]).toEqual({ confirmLabel: RESET_IDENTITY });
    expect(h.resetServerCertPin).not.toHaveBeenCalled();
  });
});

describe('Login — a text that only names a pin code', () => {
  it('offers no reset', async () => {
    for (const code of ['ERR_TOFU_PIN_MISMATCH', 'ERR_CA_PIN_MISMATCH']) {
      h.login.mockRejectedValueOnce(
        new IpcError(`Login fehlgeschlagen: ${code}: x`, 'ERR_VALIDATION'),
      );
      const { container } = render(Login);
      await submitLogin(container);

      await waitFor(() =>
        expect(container.querySelector('.login-error')?.textContent).toContain(
          'Login fehlgeschlagen',
        ),
      );
      expect(buttonsLabelled(container, RESET_PIN)).toHaveLength(0);
      expect(buttonsLabelled(container, RESET_IDENTITY)).toHaveLength(0);
      cleanup();
    }
  });
});
