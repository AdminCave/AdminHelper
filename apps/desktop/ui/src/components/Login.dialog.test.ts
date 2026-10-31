// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The login screen asks its questions in the app's own dialog (R-0395); the native
// one was refused by the capabilities and the reset buttons did nothing. App mounts
// the dialog beside the login screen, in the layer above it. The other Login tests
// mock confirmDialog; this one goes through App and the real dialog.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import type { ResetOutcome } from '$lib/bridge';
import { IpcError } from '$lib/utils/errors';

const REVOKED = new IpcError(
  'This device certificate is no longer valid. Reset the device identity and register the device again.',
  'ERR_CERT_REVOKED',
  403,
);

const h = vi.hoisted(() => ({
  login: vi.fn(),
  resetDeviceIdentity: vi.fn(async (_serverUrl: string): Promise<ResetOutcome> => 'revoked'),
}));

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    hydrate: vi.fn(),
    ready: writable(true),
    needsLogin: writable(true),
    login: h.login,
    setAllowSelfSignedCerts: vi.fn(async () => {}),
    settings: writable({
      mode: 'server',
      serverUrl: '',
      lastUsername: '',
      allowSelfSignedCerts: false,
    }),
  };
});
vi.mock('$lib/bridge', () => ({
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: h.resetDeviceIdentity,
}));
// Never rendered while the login is shown; mocked so its imports stay out.
vi.mock('./AppShell.svelte', () => ({ default: vi.fn() }));

import App from '../App.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// Signs in with a revoked certificate, clicks the reset and returns the question.
async function askReset(container: HTMLElement): Promise<HTMLElement> {
  h.login.mockRejectedValueOnce(REVOKED);
  const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
  const user = container.querySelector<HTMLInputElement>('input[type="text"]')!;
  const pass = container.querySelector<HTMLInputElement>('input[type="password"]')!;
  await fireEvent.input(url, { target: { value: 'https://srv.example' } });
  await fireEvent.input(user, { target: { value: 'alice' } });
  await fireEvent.input(pass, { target: { value: 'secret' } });
  await fireEvent.submit(container.querySelector('form')!);
  const reset = await waitFor(() => {
    const el = container.querySelector<HTMLButtonElement>('[data-action="cert-revoked-reset"]');
    expect(el).not.toBeNull();
    return el!;
  });
  await fireEvent.click(reset);
  return waitFor(() => {
    const dialog = container.querySelector<HTMLElement>('.confirm-layer [role="dialog"]');
    expect(dialog).not.toBeNull();
    return dialog!;
  });
}

function buttonIn(dialog: HTMLElement, label: string): HTMLButtonElement {
  const found = [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === label,
  );
  expect(found).toBeDefined();
  return found!;
}

describe('Login — the reset question in the app dialog', () => {
  it('opens above the login screen, and its confirm button resets', async () => {
    const { container } = render(App);
    const dialog = await askReset(container);
    expect(dialog.textContent).toContain(tNow('login.certRevoked.confirm'));

    await fireEvent.click(buttonIn(dialog, tNow('login.resetDeviceId')));

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledWith('https://srv.example'));
    await waitFor(() => expect(container.textContent).toContain('mit einem Einmal-Token neu'));
    expect(container.querySelector('.confirm-layer [role="dialog"]')).toBeNull();
  });

  it('cancelling closes it and resets nothing', async () => {
    const { container } = render(App);
    const dialog = await askReset(container);

    await fireEvent.click(buttonIn(dialog, tNow('action.cancel')));

    await waitFor(() =>
      expect(container.querySelector('.confirm-layer [role="dialog"]')).toBeNull(),
    );
    expect(h.resetDeviceIdentity).not.toHaveBeenCalled();
    expect(container.querySelector('[data-msg="cert-revoked"]')).not.toBeNull();
  });
});
