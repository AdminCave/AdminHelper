// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The provisioning tab lists the server's tokens and opens the provisioning dialog; the
// commands themselves are the dialog's (ProvisioningDialog.test.ts).

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

const SERVER_ID = '3f2b8c1e-5d4a-4b6f-9e2d-7a1c0b9e8f42';

const h = vi.hoisted(() => ({
  createToken: vi.fn(async () => ({ token: 'adminhelper_prov_tok-123', id: 't1' })),
  listTokens: vi.fn(async () => []),
  platforms: vi.fn(async () => ({ platforms: [] })),
}));

vi.mock('$lib/bridge', () => ({ pinnedCaFingerprint: vi.fn(async () => null) }));
vi.mock('$lib/api/provisioning', () => ({
  provisioningApi: { createToken: h.createToken, listTokens: h.listTokens, platforms: h.platforms },
}));
vi.mock('$lib/stores/session', async () => {
  const { readable, writable } = await import('svelte/store');
  return {
    session: readable({ serverUrl: 'https://srm.example', username: 'admin', isAdmin: true }),
    settings: writable({ mode: 'server', allowSelfSignedCerts: false }),
  };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import ProvisioningTab from './ProvisioningTab.svelte';

const server = { id: SERVER_ID, name: 'srv', osType: 'linux' } as never;

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('ProvisioningTab', () => {
  it('opens the dialog and reloads the list once a token was created there', async () => {
    h.platforms.mockResolvedValueOnce({
      platforms: [
        {
          id: 'linux',
          available: true,
          reason: null,
          versions: [],
          arch: [],
          abis: [],
          prerequisites: { systems: [], ports: [] },
          commands: [
            {
              action: 'install',
              shell: 'bash',
              base: 'curl -fsSL https://example/agent-install.sh | sudo bash -s --',
              args: [{ flag: '--token', value: 'token', optional: false, mode: 'automation' }],
            },
          ],
          doc: null,
        },
      ],
    } as never);
    const view = render(ProvisioningTab, { server });
    const doc = view.container.ownerDocument;
    await waitFor(() => expect(h.listTokens).toHaveBeenCalledTimes(1));
    expect(doc.querySelector('[role="dialog"]')).toBeNull();

    await fireEvent.click(view.container.querySelector('[data-action="prov-open"]') as HTMLElement);
    await waitFor(() => expect(doc.querySelector('[data-action="prov-mint"]')).not.toBeNull());
    await fireEvent.click(doc.querySelector('[data-action="prov-mint"]') as HTMLButtonElement);
    await waitFor(() => expect(h.listTokens).toHaveBeenCalledTimes(2));
  });

  it('tones the token states (R-1064)', async () => {
    h.listTokens.mockResolvedValueOnce([
      {
        id: 'a',
        createdAt: '2026-11-01T10:00:00Z',
        expiresAt: '2026-11-02T10:00:00Z',
        isValid: true,
      },
      {
        id: 'b',
        createdAt: '2026-11-01T10:00:00Z',
        expiresAt: '2026-11-02T10:00:00Z',
        usedAt: '2026-11-01T11:00:00Z',
        isValid: false,
      },
      {
        id: 'c',
        createdAt: '2026-10-01T10:00:00Z',
        expiresAt: '2026-10-02T10:00:00Z',
        isValid: false,
      },
    ] as never);
    const view = render(ProvisioningTab, { server });
    await waitFor(() =>
      expect(view.container.querySelectorAll('.prov-table tbody tr')).toHaveLength(3),
    );
    const tones = Array.from(view.container.querySelectorAll('.prov-table tbody .pill')).map((p) =>
      Array.from(p.classList).find((c) => c.startsWith('pill-')),
    );
    expect(tones).toEqual(['pill-accent', 'pill-ok', 'pill-crit']);
  });
});
