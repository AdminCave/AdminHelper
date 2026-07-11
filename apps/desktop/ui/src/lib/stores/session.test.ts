// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AuthSession, Settings } from '$lib/bridge/types';

// Mock the bridge + collaborators: the session lifecycle (hydrate/login/
// dropSession) is what we test; persistence and i18n are side channels. The
// connections store is no longer imported here — it is wired in via
// registerConnectionsSync (see the "connections sync hooks" block below).
vi.mock('$lib/bridge', () => ({
  loadSettings: vi.fn(),
  saveSettings: vi.fn(async () => {}),
  login: vi.fn(),
  logout: vi.fn(async () => {}),
  fetchConnectionsJwt: vi.fn(async () => []),
}));
vi.mock('$lib/i18n', () => ({ setLanguage: vi.fn() }));

import * as bridge from '$lib/bridge';
import {
  hydrate,
  login,
  logout,
  dropSession,
  needsLogin,
  isAuthenticated,
  ready,
  session,
  registerConnectionsSync,
} from './session';

const baseSettings = (over: Partial<Settings> = {}): Settings => ({
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
});

const aSession: AuthSession = {
  serverUrl: 'https://srv.example.com',
  token: 'tok',
  refreshToken: 'ref',
  username: 'alice',
  isAdmin: true,
};

describe('session store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('hydrate (no silent restore)', () => {
    it('requires login in server mode and never restores a keyring session', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
      );
      await hydrate();
      expect(get(ready)).toBe(true);
      expect(get(session)).toBeNull();
      expect(get(needsLogin)).toBe(true);
      // The whole point: startup must not pull a session from the keyring. The "no keyring restore"
      // surface invariant is asserted against the REAL bridge module below (not this mock).
    });

    it('does not require login in local mode', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(baseSettings({ mode: 'local' }));
      await hydrate();
      expect(get(needsLogin)).toBe(false);
      expect(get(isAuthenticated)).toBe(true);
    });

    it('the real bridge module exports no keyring session-restore call', async () => {
      // 6.44: `'checkSession' in bridge` against the mock above is tautological — it only checks the
      // mock's shape. Assert against the ACTUAL module so adding a real keyring-restore export (a
      // security-relevant regression to the "login required, no silent restore" invariant) fails.
      const real = await vi.importActual<typeof import('$lib/bridge')>('$lib/bridge');
      expect('checkSession' in real).toBe(false);
    });
  });

  describe('dropSession', () => {
    it('clears the keyring tokens and the in-memory session', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
      );
      vi.mocked(bridge.login).mockResolvedValue(aSession);
      await hydrate();
      await login('https://srv.example.com', 'alice', 'pw');
      expect(get(session)).not.toBeNull();

      await dropSession();
      expect(bridge.logout).toHaveBeenCalledOnce();
      expect(get(session)).toBeNull();
      expect(get(needsLogin)).toBe(true);
    });

    it('still clears the local session when the server logout call fails', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
      );
      vi.mocked(bridge.login).mockResolvedValue(aSession);
      vi.mocked(bridge.logout).mockRejectedValueOnce(new Error('offline'));
      await hydrate();
      await login('https://srv.example.com', 'alice', 'pw');

      await dropSession();
      expect(get(session)).toBeNull();
    });
  });

  describe('login persists prefill data', () => {
    it('saves the trimmed server URL + username, never the password', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: '' }),
      );
      vi.mocked(bridge.login).mockResolvedValue(aSession);
      await hydrate();
      await login('  https://srv.example.com  ', '  alice  ', 'secret');

      expect(bridge.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          serverUrl: 'https://srv.example.com',
          lastUsername: 'alice',
        }),
      );
      const saved = vi.mocked(bridge.saveSettings).mock.calls[0][0];
      expect(JSON.stringify(saved)).not.toContain('secret');
    });
  });

  // The session store drives the connections store only through the hooks wired
  // in at app start (registerConnectionsSync in main.ts) — not a direct import.
  describe('connections sync hooks', () => {
    afterEach(() => {
      // Reset to no-ops so the singleton hook doesn't leak into other tests.
      registerConnectionsSync({ reload: async () => {}, clear: () => {} });
    });

    it('login reloads and logout clears via the registered hooks', async () => {
      const reload = vi.fn(async () => {});
      const clear = vi.fn();
      registerConnectionsSync({ reload, clear });

      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
      );
      vi.mocked(bridge.login).mockResolvedValue(aSession);
      await hydrate();
      await login('https://srv.example.com', 'alice', 'pw');
      expect(reload).toHaveBeenCalledWith(expect.objectContaining({ mode: 'server' }), aSession);

      await logout();
      expect(clear).toHaveBeenCalledOnce();
      expect(get(session)).toBeNull();
    });

    it('logout clears the in-memory list BEFORE nulling the session (order invariant)', async () => {
      // Documented order (session.ts): clear first, then session=null — otherwise subscribers briefly
      // see the old connection data in the already-logged-out state (6.119).
      let sessionWhenCleared: unknown = 'unset';
      registerConnectionsSync({
        reload: async () => {},
        clear: () => {
          sessionWhenCleared = get(session);
        },
      });
      vi.mocked(bridge.login).mockResolvedValue(aSession);
      await login('https://srv.example.com', 'alice', 'pw');
      expect(get(session)).not.toBeNull();

      await logout();
      expect(sessionWhenCleared).not.toBeNull(); // session still present when clear ran -> clear first
      expect(get(session)).toBeNull();
    });

    it('logout still clears + nulls the session when bridge.logout rejects (finally path)', async () => {
      const clear = vi.fn();
      registerConnectionsSync({ reload: async () => {}, clear });
      vi.mocked(bridge.login).mockResolvedValue(aSession);
      await login('https://srv.example.com', 'alice', 'pw');
      vi.mocked(bridge.logout).mockRejectedValueOnce(new Error('server unreachable'));

      // The error propagates (try/finally re-raises), but the finally must still have run.
      await expect(logout()).rejects.toThrow('server unreachable');
      expect(clear).toHaveBeenCalledOnce();
      expect(get(session)).toBeNull();
    });
  });
});
