// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AuthSession, Settings, WorkspaceContext } from '$lib/bridge/types';

// Mock the bridge + collaborators: the session lifecycle (hydrate/login/
// logout) is what we test; persistence and i18n are side channels. The
// connections store is no longer imported here — it is wired in via
// registerConnectionsSync (see the "connections sync hooks" block below).
vi.mock('$lib/bridge', () => ({
  workspaceContext: vi.fn(),
  loadSettings: vi.fn(),
  saveSettings: vi.fn(async () => {}),
  login: vi.fn(),
  logout: vi.fn(async () => {}),
  fetchConnectionsJwt: vi.fn(async () => []),
}));
vi.mock('$lib/i18n', () => ({ setLanguage: vi.fn(), tNow: (key: string) => key }));

import * as bridge from '$lib/bridge';
import {
  hydrate,
  login,
  logout,
  needsLogin,
  isAuthenticated,
  ready,
  session,
  settings,
  setAllowSelfSignedCerts,
  registerConnectionsSync,
} from './session';
import { context } from './workspace';

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
  username: 'alice',
  isAdmin: true,
};

const launcher: WorkspaceContext = { launcher: true, workspace: null };
const serverWorkspace: WorkspaceContext = {
  launcher: false,
  workspace: {
    id: 'standard',
    name: 'Standard',
    color: '#3b82f6',
    kind: 'server',
    host: 'srv.example.com',
    open: true,
  },
};

/** The session module as the app starts it: not ready, no workspace context. */
async function freshStart() {
  vi.resetModules();
  const freshBridge = await import('$lib/bridge');
  const freshSession = await import('./session');
  return { bridge: freshBridge, session: freshSession };
}

describe('session store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bridge.workspaceContext).mockResolvedValue(serverWorkspace);
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

    it('the launcher never asks for a login, not even while it hydrates', async () => {
      const fresh = await freshStart();
      // The launcher's settings come without a workspace (mode local); `server` here proves
      // that the context, not the mode, keeps the login away.
      vi.mocked(fresh.bridge.workspaceContext).mockResolvedValue(launcher);
      vi.mocked(fresh.bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
      );
      const seen: boolean[] = [];
      const stop = fresh.session.needsLogin.subscribe((value) => seen.push(value));
      try {
        await fresh.session.hydrate();
      } finally {
        stop();
      }
      expect(get(fresh.session.ready)).toBe(true);
      expect(get(fresh.session.needsLogin)).toBe(false);
      expect(seen).not.toContain(true);
    });

    it('the context decides: the launcher no login, a server workspace without a session the login', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
      );
      vi.mocked(bridge.workspaceContext).mockResolvedValue(launcher);
      await hydrate();
      expect(get(needsLogin)).toBe(false);

      vi.mocked(bridge.workspaceContext).mockResolvedValue(serverWorkspace);
      await hydrate();
      expect(get(session)).toBeNull();
      expect(get(needsLogin)).toBe(true);
    });

    it('without a context a server workspace still asks for the login (fail closed)', async () => {
      const fresh = await freshStart();
      const error = vi.spyOn(console, 'error').mockImplementation(() => {});
      try {
        vi.mocked(fresh.bridge.workspaceContext).mockRejectedValue(new Error('no data dir'));
        vi.mocked(fresh.bridge.loadSettings).mockResolvedValue(
          baseSettings({ mode: 'server', serverUrl: 'https://srv.example.com' }),
        );
        await fresh.session.hydrate();
        expect(get(fresh.session.ready)).toBe(true);
        expect(get(fresh.session.settings)?.mode).toBe('server');
        expect(get(fresh.session.needsLogin)).toBe(true);
        expect(error).toHaveBeenCalledWith('workspace context failed', expect.any(Error));
      } finally {
        error.mockRestore();
      }
    });

    it('the real bridge module exports no keyring session-restore call', async () => {
      // 6.44: `'checkSession' in bridge` against the mock above is tautological — it only checks the
      // mock's shape. Assert against the ACTUAL module so adding a real keyring-restore export (a
      // security-relevant regression to the "login required, no silent restore" invariant) fails.
      const real = await vi.importActual<typeof import('$lib/bridge')>('$lib/bridge');
      expect('checkSession' in real).toBe(false);
    });
  });

  describe('login persists prefill data', () => {
    it('saves the server URL of the session and the trimmed username, never the password', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: '' }),
      );
      // Rust names the URL the workspace keeps, not the one the window sent (masked, say).
      const kept = 'https://bob:pw@srv.example.com/?token=t0k';
      vi.mocked(bridge.login).mockResolvedValue({ ...aSession, serverUrl: kept });
      await hydrate();
      await login('https://***@srv.example.com/?token=***', '  alice  ', 'secret');

      expect(bridge.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ serverUrl: kept, lastUsername: 'alice' }),
      );
      const saved = vi.mocked(bridge.saveSettings).mock.calls[0][0];
      expect(JSON.stringify(saved)).not.toContain('secret');
    });
  });

  // The save after the sign-in gives a workspace without a URL its first one (R-0431): the
  // context names it only once loaded anew, and the settings of the window read it there.
  describe('login loads the context anew after the first URL', () => {
    const withUrl: WorkspaceContext = {
      launcher: false,
      workspace: { ...serverWorkspace.workspace!, url: 'https://srv.example.com/' },
    };

    beforeEach(() => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', serverUrl: null }),
      );
      vi.mocked(bridge.login).mockResolvedValue(aSession);
    });

    it('a workspace without a URL shows the one the save gave it', async () => {
      await hydrate();
      expect(get(context)?.workspace?.url ?? null).toBeNull();
      vi.mocked(bridge.workspaceContext).mockResolvedValue(withUrl);

      await login('https://srv.example.com', 'alice', 'pw');

      expect(bridge.workspaceContext).toHaveBeenCalledTimes(2);
      expect(vi.mocked(bridge.saveSettings).mock.invocationCallOrder[0]).toBeLessThan(
        vi.mocked(bridge.workspaceContext).mock.invocationCallOrder[1],
      );
      expect(get(context)?.workspace?.url).toBe('https://srv.example.com/');
    });

    it('a save Rust refused leaves the context as it was', async () => {
      await hydrate();
      vi.mocked(bridge.saveSettings).mockRejectedValueOnce(new Error('identity without URL'));

      await login('https://srv.example.com', 'alice', 'pw');

      expect(bridge.workspaceContext).toHaveBeenCalledOnce();
      expect(get(session)).not.toBeNull();
    });

    it('a workspace that has its URL is not asked again', async () => {
      vi.mocked(bridge.workspaceContext).mockResolvedValue(withUrl);
      await hydrate();

      await login('https://srv.example.com', 'alice', 'pw');

      expect(bridge.workspaceContext).toHaveBeenCalledOnce();
    });

    it('a context that does not load again keeps the sign-in', async () => {
      const error = vi.spyOn(console, 'error').mockImplementation(() => {});
      try {
        await hydrate();
        vi.mocked(bridge.workspaceContext).mockRejectedValueOnce(new Error('no data dir'));

        await login('https://srv.example.com', 'alice', 'pw');

        expect(get(session)).toEqual(aSession);
        expect(get(context)?.workspace?.url ?? null).toBeNull();
        expect(error).toHaveBeenCalledWith('workspace context failed', expect.any(Error));
      } finally {
        error.mockRestore();
      }
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

  describe('setAllowSelfSignedCerts (login-screen trust dialog)', () => {
    it('persists the opt-in and updates the store so a retry reads true', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', allowSelfSignedCerts: false }),
      );
      await hydrate();

      await setAllowSelfSignedCerts(true);

      expect(bridge.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ allowSelfSignedCerts: true }),
      );
      expect(get(settings)?.allowSelfSignedCerts).toBe(true);
    });

    it('does not touch the store when persisting fails', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(
        baseSettings({ mode: 'server', allowSelfSignedCerts: false }),
      );
      await hydrate();
      vi.mocked(bridge.saveSettings).mockRejectedValueOnce(new Error('disk full'));

      await expect(setAllowSelfSignedCerts(true)).rejects.toThrow('disk full');
      expect(get(settings)?.allowSelfSignedCerts).toBe(false);
    });
  });
});
