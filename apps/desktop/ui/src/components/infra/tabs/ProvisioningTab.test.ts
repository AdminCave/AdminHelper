// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The provisioning tab is the trusted courier for the agent's first-contact
// trust anchors: with an enrolled desktop it must embed the pinned CA
// fingerprint (--ca-fp) into BOTH generated commands (install script +
// provision-only) and display it for out-of-band comparison; without an
// enrolled identity it must fall back to the previous TOFU behaviour and say
// so visibly.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

const FP = 'ab'.repeat(32);

const h = vi.hoisted(() => ({
  pinnedCaFingerprint: vi.fn(async (): Promise<string | null> => null),
  createToken: vi.fn(async () => ({ token: 'tok-123', id: 't1' })),
  listTokens: vi.fn(async () => []),
  allowSelfSigned: { value: false },
}));

vi.mock('$lib/bridge', () => ({ pinnedCaFingerprint: h.pinnedCaFingerprint }));
vi.mock('$lib/api/provisioning', () => ({
  provisioningApi: { createToken: h.createToken, listTokens: h.listTokens },
}));
vi.mock('$lib/stores/session', async () => {
  const { readable, writable } = await import('svelte/store');
  return {
    session: readable({
      serverUrl: 'https://srm.example',
      token: 't',
      refreshToken: 'r',
      username: 'admin',
      isAdmin: true,
    }),
    settings: writable({ mode: 'server', allowSelfSignedCerts: h.allowSelfSigned.value }),
  };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import ProvisioningTab from './ProvisioningTab.svelte';

const server = { id: 'sid-9', name: 'srv' } as never;

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('ProvisioningTab — trust anchor handover', () => {
  it('embeds --ca-fp in both commands and shows the fingerprint when enrolled', async () => {
    h.pinnedCaFingerprint.mockResolvedValue(FP);
    const { getByTestId, queryByTestId, getByText } = render(ProvisioningTab, { server });

    await waitFor(() => expect(getByTestId('ca-fp').textContent).toContain(FP));
    expect(queryByTestId('no-ca-fp')).toBeNull();

    await fireEvent.click(getByText('Token erzeugen'));

    await waitFor(() => expect(queryByTestId('script-command')).not.toBeNull());
    const script = getByTestId('script-command').textContent ?? '';
    expect(script).toContain('scripts/agent-install.sh');
    expect(script).toContain('--server https://srm.example');
    expect(script).toContain('--token tok-123');
    expect(script).toContain('--server-id sid-9');
    expect(script).toContain(`--ca-fp ${FP}`);

    const plain = getByTestId('provision-command').textContent ?? '';
    expect(plain).toContain('adminhelper-agent provision');
    expect(plain).toContain(`--ca-fp ${FP}`);
    expect(plain).not.toContain('--insecure');
  });

  it('falls back to TOFU without an enrolled identity and warns visibly', async () => {
    h.pinnedCaFingerprint.mockResolvedValue(null);
    h.allowSelfSigned.value = true;
    const { getByTestId, queryByTestId, getByText } = render(ProvisioningTab, { server });

    await waitFor(() => expect(queryByTestId('no-ca-fp')).not.toBeNull());

    await fireEvent.click(getByText('Token erzeugen'));
    await waitFor(() => expect(queryByTestId('script-command')).not.toBeNull());

    expect(getByTestId('script-command').textContent).not.toContain('--ca-fp');
    // The settings store was built with allowSelfSignedCerts at mock-module init;
    // the plain command honours it exactly like the login path does.
    const plain = getByTestId('provision-command').textContent ?? '';
    expect(plain).not.toContain('--ca-fp');
  });
});
