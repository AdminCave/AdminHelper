// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';

const h = vi.hoisted(() => ({
  conn: { error: null as string | null },
  sess: { settings: { mode: 'sync', url: 'https://srv' } as unknown },
  reportError: vi.fn(),
  showStatus: vi.fn(),
}));

vi.mock('./connections', () => ({
  reloadForMode: vi.fn(async () => {}),
  connectionsStore: {
    subscribe: (fn: (v: { error: string | null }) => void) => {
      fn(h.conn);
      return () => {};
    },
  },
}));
vi.mock('./session', () => ({
  sessionStore: {
    subscribe: (fn: (v: unknown) => void) => {
      fn(h.sess);
      return () => {};
    },
  },
  refreshSettings: vi.fn(),
  dropSession: vi.fn(),
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError, showStatus: h.showStatus }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k, setLanguage: vi.fn() }));
vi.mock('$lib/bridge', () => ({}));
vi.mock('./tunnel', () => ({}));

import { syncNow } from './settings';

describe('syncNow', () => {
  beforeEach(() => {
    h.reportError.mockClear();
    h.showStatus.mockClear();
    h.conn.error = null;
  });

  it('reports the store error instead of "success" when the sync failed (4.42)', async () => {
    h.conn.error = 'Server nicht erreichbar';
    await syncNow(true);
    expect(h.reportError).toHaveBeenCalledWith('Server nicht erreichbar');
    expect(h.showStatus).not.toHaveBeenCalled();
  });

  it('shows sync success when the store has no error', async () => {
    await syncNow(true);
    expect(h.showStatus).toHaveBeenCalledWith('status.syncSuccess');
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('stays silent when notify is false', async () => {
    h.conn.error = 'boom';
    await syncNow(false);
    expect(h.reportError).not.toHaveBeenCalled();
    expect(h.showStatus).not.toHaveBeenCalled();
  });
});
