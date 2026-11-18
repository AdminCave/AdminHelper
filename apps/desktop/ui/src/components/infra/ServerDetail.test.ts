// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The server overview names a platform the agent reported when it differs from the chosen
// one (R-1594); without a chosen platform it does not ask.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

const h = vi.hoisted(() => ({ progress: vi.fn(), isAdmin: { value: true } }));

vi.mock('$lib/api/provisioning', () => ({ provisioningApi: { progress: h.progress } }));
vi.mock('$lib/stores/session', async (importOriginal) => {
  const { readable } = await import('svelte/store');
  return {
    ...(await importOriginal<object>()),
    session: readable({
      serverUrl: 'https://srm.example',
      username: 'admin',
      get isAdmin() {
        return h.isAdmin.value;
      },
    }),
  };
});

import ServerDetail from './ServerDetail.svelte';

const SERVER = { id: 'srv-1', name: 'srv', hostname: 'srv.example.test', osType: 'linux' };

function answer(reportedPlatform: string | null, platformMismatch: boolean) {
  return {
    token: null,
    certificate: null,
    report: null,
    monitoringReachable: true,
    tunnel: { configured: false, connected: null },
    reportedPlatform,
    platformMismatch,
  };
}

// Lets the lookup's then/catch run before a negative assertion.
function settled(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 20));
}

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  h.isAdmin.value = true;
});

describe('ServerDetail — platform mismatch', () => {
  it('names the reported platform when it differs', async () => {
    h.progress.mockResolvedValue(answer('windows', true));
    const view = render(ServerDetail, { server: SERVER as never });
    await waitFor(() =>
      expect(
        view.container.querySelector('[data-testid="platform-mismatch"]')?.textContent,
      ).toContain('Windows'),
    );
    expect(h.progress).toHaveBeenCalledWith(expect.anything(), 'srv-1');
  });

  it('shows nothing when the platforms agree or the lookup fails', async () => {
    h.progress.mockResolvedValueOnce(answer('linux', false));
    const agree = render(ServerDetail, { server: SERVER as never });
    await waitFor(() => expect(h.progress).toHaveBeenCalledTimes(1));
    await settled();
    expect(agree.container.querySelector('[data-testid="platform-mismatch"]')).toBeNull();
    cleanup();

    h.progress.mockRejectedValueOnce(new Error('down'));
    const failed = render(ServerDetail, { server: SERVER as never });
    await waitFor(() => expect(h.progress).toHaveBeenCalledTimes(2));
    await settled();
    expect(failed.container.querySelector('[data-testid="platform-mismatch"]')).toBeNull();
  });

  it('does not ask without a chosen platform', async () => {
    render(ServerDetail, { server: { ...SERVER, osType: null } as never });
    await settled();
    expect(h.progress).not.toHaveBeenCalled();
  });

  it('does not ask for a user who is no admin', async () => {
    h.isAdmin.value = false;
    render(ServerDetail, { server: SERVER as never });
    await settled();
    expect(h.progress).not.toHaveBeenCalled();
  });
});
