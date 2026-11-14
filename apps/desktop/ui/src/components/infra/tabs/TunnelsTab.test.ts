// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1316: the tunnel tab offers admins a "renew tunnel key" button behind a
// confirmation; non-admins never see it.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import type { Server } from '$lib/api/types';

const h = vi.hoisted(() => ({
  listTunnels: vi.fn().mockResolvedValue([]),
  listConfigs: vi.fn().mockResolvedValue([]),
  rotateKey: vi.fn().mockResolvedValue({ generation: 1, policySynced: true }),
  confirm: vi.fn(),
  isAdmin: true,
}));

vi.mock('$lib/api/frp', () => ({
  frpApi: { listTunnels: h.listTunnels, listConfigs: h.listConfigs, rotateKey: h.rotateKey },
}));
// Read h.isAdmin on every subscribe, so each test mounts with its own role.
vi.mock('$lib/stores/session', () => ({
  session: {
    subscribe(fn: (v: unknown) => void) {
      fn({ serverUrl: 'https://srv', username: 'u', isAdmin: h.isAdmin });
      return () => {};
    },
  },
}));
vi.mock('$lib/stores/statusBar', () => ({
  reportError: vi.fn(),
  showStatus: vi.fn(),
  showNotice: vi.fn(),
}));
vi.mock('../../ui/ConfirmDialog.svelte', () => ({ confirmDialog: h.confirm }));

import { setLanguage } from '$lib/i18n';
import { reportError, showNotice, showStatus } from '$lib/stores/statusBar';
import TunnelsTab from './TunnelsTab.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  h.isAdmin = true;
});

const server = { id: 'srv-1', name: 'alpha', hostname: 'alpha.example' } as Server;

function rotateButton(container: HTMLElement): HTMLElement | null {
  return container.querySelector('[data-action="tun-rotate-key"]');
}

describe('TunnelsTab tunnel key renewal', () => {
  it('hides the button for non-admins', async () => {
    h.isAdmin = false;
    const { container } = render(TunnelsTab, { props: { server } });
    await waitFor(() => expect(h.listTunnels).toHaveBeenCalled());
    expect(rotateButton(container)).toBeNull();
  });

  it('calls nothing when the admin cancels', async () => {
    h.confirm.mockResolvedValueOnce(false);
    const { container } = render(TunnelsTab, { props: { server } });
    await waitFor(() => expect(rotateButton(container)).not.toBeNull());
    await fireEvent.click(rotateButton(container)!);
    await waitFor(() => expect(h.confirm).toHaveBeenCalledTimes(1));
    expect(h.confirm.mock.calls[0][0]).toContain('frpc.toml');
    expect(h.rotateKey).not.toHaveBeenCalled();
    expect(showStatus).not.toHaveBeenCalled();
  });

  it('calls the route for this server after confirmation and reports success', async () => {
    h.confirm.mockResolvedValueOnce(true);
    const { container } = render(TunnelsTab, { props: { server } });
    await waitFor(() => expect(rotateButton(container)).not.toBeNull());
    await fireEvent.click(rotateButton(container)!);
    await waitFor(() => expect(h.rotateKey).toHaveBeenCalledTimes(1));
    expect(h.rotateKey).toHaveBeenCalledWith(expect.objectContaining({ isAdmin: true }), 'srv-1');
    await waitFor(() => expect(showStatus).toHaveBeenCalledWith(expect.stringContaining('alpha')));
    expect(reportError).not.toHaveBeenCalled();
    expect(showNotice).not.toHaveBeenCalled();
  });

  // R-1437: the rotation stands, but frps still admits the old key until the next sync.
  it('warns when the server could not write the frps policy', async () => {
    h.confirm.mockResolvedValueOnce(true);
    h.rotateKey.mockResolvedValueOnce({ generation: 2, policySynced: false });
    const { container } = render(TunnelsTab, { props: { server } });
    await waitFor(() => expect(rotateButton(container)).not.toBeNull());
    await fireEvent.click(rotateButton(container)!);
    await waitFor(() => expect(showNotice).toHaveBeenCalledTimes(1));
    const notice = vi.mocked(showNotice).mock.calls[0][0];
    expect(notice.tone).toBe('warning');
    expect(notice.title).toContain('alpha');
    expect(notice.body).toContain('frps-Policy');
    expect(showStatus).not.toHaveBeenCalled();
    expect(reportError).not.toHaveBeenCalled();
  });

  it('reports a failed rotation through the status bar', async () => {
    h.confirm.mockResolvedValueOnce(true);
    h.rotateKey.mockRejectedValueOnce(new Error('forbidden'));
    const { container } = render(TunnelsTab, { props: { server } });
    await waitFor(() => expect(rotateButton(container)).not.toBeNull());
    await fireEvent.click(rotateButton(container)!);
    await waitFor(() =>
      expect(reportError).toHaveBeenCalledWith(expect.stringContaining('forbidden')),
    );
    expect(showStatus).not.toHaveBeenCalled();
  });
});
