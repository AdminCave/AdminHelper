// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import type { AuthSession, Settings, TunnelMapping } from '$lib/bridge/types';

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
  tunnelStatus: vi.fn(async () => ({ running: false })),
  loadSettings: vi.fn(),
  bridgeLogin: vi.fn(),
  bridgeLogout: vi.fn(),
  refreshTunnel: vi.fn(),
  fetchTunnels: vi.fn(),
  stopTunnel: vi.fn(),
  reloadWindow: vi.fn(),
  listen: vi.fn(),
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
vi.mock('$lib/bridge', () => ({
  saveSettings: h.saveSettingsBridge,
  tunnelStatus: h.tunnelStatus,
  loadSettings: h.loadSettings,
  login: h.bridgeLogin,
  logout: h.bridgeLogout,
  refreshTunnel: h.refreshTunnel,
  fetchTunnels: h.fetchTunnels,
  stopTunnel: h.stopTunnel,
}));
vi.mock('./tunnel', () => ({ stop: h.tunnelStop, startIfServerMode: h.tunnelStart }));
vi.mock('$lib/utils/reloadWindow', () => ({ reloadWindow: h.reloadWindow }));
vi.mock('@tauri-apps/api/event', () => ({ listen: h.listen }));

import { syncNow, saveSettings, stopSyncTimer } from './settings';
import { takeLoginNotice } from '$lib/utils/loginNotice';

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

  it('a server-URL change with an active session reloads the window after saving (R-0429)', async () => {
    // The forced logout leaves the old server's data in the stores; the reload empties them all.
    const result = await saveSettings(base({ mode: 'server', serverUrl: 'https://neu' }));
    expect(result.ok).toBe(true);
    expect(h.reloadWindow).toHaveBeenCalledOnce();
    expect(h.saveSettingsBridge.mock.invocationCallOrder[0]).toBeLessThan(
      h.reloadWindow.mock.invocationCallOrder[0],
    );
  });

  it('a server-URL change without a session saves without a reload', async () => {
    h.sess.session = null;
    const result = await saveSettings(base({ mode: 'server', serverUrl: 'https://neu' }));
    expect(result.ok).toBe(true);
    expect(h.saveSettingsBridge).toHaveBeenCalledOnce();
    expect(h.reloadWindow).not.toHaveBeenCalled();
  });

  it('a failed save after the forced logout does not reload', async () => {
    h.saveSettingsBridge.mockRejectedValueOnce(new Error('disk full'));
    const result = await saveSettings(base({ mode: 'server', serverUrl: 'https://neu' }));
    expect(result.ok).toBe(false);
    expect(h.dropSession).toHaveBeenCalled();
    expect(h.reloadWindow).not.toHaveBeenCalled();
  });

  it('saving in server mode leaves a running tunnel alone (R-0245)', async () => {
    // Nothing the tunnel depends on changed (a new server URL logs out above), and a
    // second start next to the running frpc fails with "frpc laeuft bereits".
    h.tunnelStatus.mockResolvedValueOnce({ running: true });
    await saveSettings(base({ mode: 'server', serverUrl: 'https://alt' }));
    expect(h.reloadForMode).toHaveBeenCalled();
    expect(h.tunnelStart).not.toHaveBeenCalled();
    expect(h.tunnelStop).not.toHaveBeenCalled();
  });

  it('saving in server mode still starts the tunnel when the status call fails', async () => {
    h.tunnelStatus.mockRejectedValueOnce(new Error('status unavailable'));
    const result = await saveSettings(base({ mode: 'server', serverUrl: 'https://alt' }));
    expect(h.tunnelStart).toHaveBeenCalledTimes(1);
    expect(result.ok).toBe(true);
  });

  it('saving in server mode starts the tunnel when none runs', async () => {
    h.tunnelStatus.mockResolvedValueOnce({ running: false });
    await saveSettings(base({ mode: 'server', serverUrl: 'https://alt' }));
    expect(h.tunnelStart).toHaveBeenCalledTimes(1);
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

describe('logoutAndReload: the logout buttons of the app shell and the settings (R-0402, R-0429)', () => {
  // The real session and tunnel stores over the mocked bridge, fresh for each test: what
  // counts is that frpc stops before the session goes and that no tick follows.
  const SESSION: AuthSession = {
    serverUrl: 'https://srv',
    username: 'alice',
    isAdmin: false,
  };
  const MAPPING: TunnelMapping = {
    id: 'm1',
    serverId: 's1',
    tunnelType: 'stcp',
    protocol: 'ssh',
    localPort: 22,
    visitorPort: 6000,
    customDomains: null,
    connectionId: null,
    enabled: true,
    name: 'db',
  };
  let logoutAndReload: () => Promise<void>;
  let listenForSessionExpiry: () => Promise<() => void>;
  let session: typeof import('./session');
  let tunnel: typeof import('./tunnel');

  beforeEach(async () => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    h.loadSettings.mockResolvedValue(base({ mode: 'server', serverUrl: SESSION.serverUrl }));
    h.bridgeLogin.mockResolvedValue(SESSION);
    h.bridgeLogout.mockResolvedValue(undefined);
    h.refreshTunnel.mockResolvedValue({
      status: { running: true, visitors: ['db-visitor'] },
      outcome: 'started',
    });
    h.fetchTunnels.mockResolvedValue([MAPPING]);
    h.stopTunnel.mockResolvedValue(undefined);
    vi.resetModules();
    vi.doUnmock('./session');
    vi.doUnmock('./tunnel');
    ({ logoutAndReload, listenForSessionExpiry } = await import('./settings'));
    session = await import('./session');
    tunnel = await import('./tunnel');
    await session.hydrate();
    await session.login(SESSION.serverUrl, SESSION.username, 'pw');
    await tunnel.startIfServerMode();
    expect(get(tunnel.tunnelUi)).toBe('connected');
    expect(tunnel.getMappings()).toEqual([MAPPING]);
  });

  afterEach(() => {
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it('stops the tunnel before it logs out and leaves connections.json alone', async () => {
    await logoutAndReload();
    expect(h.stopTunnel).toHaveBeenCalledOnce();
    expect(h.bridgeLogout).toHaveBeenCalledOnce();
    expect(h.stopTunnel.mock.invocationCallOrder[0]).toBeLessThan(
      h.bridgeLogout.mock.invocationCallOrder[0],
    );
    expect(get(session.session)).toBeNull();
    expect(h.reloadForMode).not.toHaveBeenCalled();
  });

  it('a failed stop does not keep the user logged in', async () => {
    h.stopTunnel.mockRejectedValueOnce(new Error('frpc not running'));
    await expect(logoutAndReload()).resolves.toBeUndefined();
    expect(h.bridgeLogout).toHaveBeenCalledOnce();
    expect(get(session.session)).toBeNull();
  });

  it('leaves the tunnel store idle without mappings, and no tick follows', async () => {
    await logoutAndReload();
    expect(get(tunnel.tunnelUi)).toBe('idle');
    expect(get(tunnel.tunnelStatus)).toBeNull();
    expect(tunnel.getMappings()).toEqual([]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
  });

  it('reloads the window after the tunnel stop and the logout', async () => {
    await logoutAndReload();
    expect(h.reloadWindow).toHaveBeenCalledOnce();
    expect(h.stopTunnel.mock.invocationCallOrder[0]).toBeLessThan(
      h.bridgeLogout.mock.invocationCallOrder[0],
    );
    expect(h.bridgeLogout.mock.invocationCallOrder[0]).toBeLessThan(
      h.reloadWindow.mock.invocationCallOrder[0],
    );
  });

  it('a failed tunnel stop does not prevent the reload', async () => {
    h.stopTunnel.mockRejectedValueOnce(new Error('frpc not running'));
    await logoutAndReload();
    expect(h.bridgeLogout).toHaveBeenCalledOnce();
    expect(h.reloadWindow).toHaveBeenCalledOnce();
  });

  it('a failed logout does not prevent the reload', async () => {
    h.bridgeLogout.mockRejectedValueOnce(new Error('keyring locked'));
    await expect(logoutAndReload()).resolves.toBeUndefined();
    expect(get(session.session)).toBeNull();
    expect(h.reloadWindow).toHaveBeenCalledOnce();
  });

  it('a logout button leaves the login screen no notice', async () => {
    await logoutAndReload();
    expect(takeLoginNotice()).toBe('');
  });

  it('session-expired logs out like the buttons, and the login screen says why (R-0430)', async () => {
    const heard = new Map<string, () => void>();
    h.listen.mockImplementation(async (event: string, handler: () => void) => {
      heard.set(event, handler);
      return () => {};
    });
    await listenForSessionExpiry();
    expect(heard.has('session-expired')).toBe(true);

    heard.get('session-expired')?.();

    await vi.waitFor(() => expect(h.reloadWindow).toHaveBeenCalledOnce());
    expect(h.stopTunnel).toHaveBeenCalledOnce();
    expect(h.bridgeLogout).toHaveBeenCalledOnce();
    expect(h.bridgeLogout.mock.invocationCallOrder[0]).toBeLessThan(
      h.reloadWindow.mock.invocationCallOrder[0],
    );
    expect(get(session.session)).toBeNull();
    expect(get(tunnel.tunnelUi)).toBe('idle');
    // The notice waits for the login screen after the reload (tNow is the key here).
    expect(takeLoginNotice()).toBe('login.sessionExpired');
  });
});
