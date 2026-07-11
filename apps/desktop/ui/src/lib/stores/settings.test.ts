// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Settings } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  conn: { error: null as string | null },
  sess: { settings: { mode: 'sync', url: 'https://srv' } as unknown, session: null as unknown },
  reportError: vi.fn(),
  showStatus: vi.fn(),
  dropSession: vi.fn(async () => {}),
  refreshSettings: vi.fn(async () => {}),
  reloadForMode: vi.fn(async () => {}),
  tunnelStop: vi.fn(async () => {}),
  tunnelStart: vi.fn(),
  saveSettingsBridge: vi.fn(async () => {}),
}));

vi.mock('./connections', () => ({
  reloadForMode: h.reloadForMode,
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
  refreshSettings: h.refreshSettings,
  dropSession: h.dropSession,
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError, showStatus: h.showStatus }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k, setLanguage: vi.fn() }));
vi.mock('$lib/bridge', () => ({ saveSettings: h.saveSettingsBridge }));
vi.mock('./tunnel', () => ({ stop: h.tunnelStop, startIfServerMode: h.tunnelStart }));

import { syncNow, saveSettings, stopSyncTimer } from './settings';

const base = (over: Partial<Settings> = {}): Settings =>
  ({
    mode: 'local',
    url: null,
    intervalMinutes: 1,
    language: 'en',
    storePasswords: false,
    osNotifications: false,
    rdpScalingMode: 'auto',
    rdpWindowMode: 'fit',
    rdpCustomSize: null,
    rdpPerformanceProfile: 'auto',
    allowSelfSignedCerts: false,
    serverUrl: null,
    ...over,
  }) as Settings;

describe('syncNow', () => {
  beforeEach(() => {
    h.reportError.mockClear();
    h.showStatus.mockClear();
    h.conn.error = null;
    h.sess.settings = { mode: 'sync', url: 'https://srv' };
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

describe('saveSettings mode-switch orchestration (6.6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    h.conn.error = null;
    // Start from an active server session so each switch exercises the logout/teardown paths.
    h.sess.session = { token: 't' };
    h.sess.settings = { mode: 'server', serverUrl: 'https://alt' };
  });

  afterEach(() => {
    stopSyncTimer(); // the sync branch starts an interval; don't leak it across tests
  });

  it('a server-URL change with an active session logs out before saving', async () => {
    // The old JWT belongs to the old server; without a logout its data would linger.
    await saveSettings(base({ mode: 'server', serverUrl: 'https://neu' }));
    expect(h.dropSession).toHaveBeenCalled();
    expect(h.tunnelStop).toHaveBeenCalled();
  });

  it('switching server->local stops the tunnel and drops the session', async () => {
    await saveSettings(base({ mode: 'local' }));
    expect(h.tunnelStop).toHaveBeenCalled();
    expect(h.dropSession).toHaveBeenCalled();
  });

  it('switching server->sync stops the tunnel and drops the session', async () => {
    await saveSettings(base({ mode: 'sync', url: 'https://sync' }));
    expect(h.tunnelStop).toHaveBeenCalled();
    expect(h.dropSession).toHaveBeenCalled();
  });
});
