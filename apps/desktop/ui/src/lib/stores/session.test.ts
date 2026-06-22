// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AuthSession, Settings } from '$lib/bridge/types';

// Mock the bridge + collaborators: the session lifecycle (hydrate/login/
// dropSession) is what we test; persistence and i18n are side channels.
vi.mock('$lib/bridge', () => ({
  loadSettings: vi.fn(),
  saveSettings: vi.fn(async () => {}),
  login: vi.fn(),
  logout: vi.fn(async () => {}),
  fetchConnectionsJwt: vi.fn(async () => []),
}));
vi.mock('$lib/i18n', () => ({ setLanguage: vi.fn() }));
vi.mock('./connections', () => ({
  reloadForMode: vi.fn(async () => {}),
  clearInMemory: vi.fn(),
}));

import * as bridge from '$lib/bridge';
import {
  hydrate,
  login,
  dropSession,
  needsLogin,
  isAuthenticated,
  ready,
  session,
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
      // The whole point: startup must not pull a session from the keyring.
      expect('checkSession' in bridge).toBe(false);
    });

    it('does not require login in local mode', async () => {
      vi.mocked(bridge.loadSettings).mockResolvedValue(baseSettings({ mode: 'local' }));
      await hydrate();
      expect(get(needsLogin)).toBe(false);
      expect(get(isAuthenticated)).toBe(true);
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
});
