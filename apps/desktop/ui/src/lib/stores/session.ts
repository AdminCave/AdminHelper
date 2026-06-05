// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Session store for desktop auth.
//
// The desktop has three modes (Settings.mode):
//   - 'local':  no server connection, no auth needed
//   - 'sync':   JSON sync via URL only, no auth needed
//   - 'server': AdminHelper server with login required
//
// Auth token + refresh token are stored exclusively in the Rust keyring
// (no localStorage copy in the frontend). The frontend asks via
// bridge.checkSession() whether a valid session currently exists.

import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { setLanguage } from '$lib/i18n';
import { reloadForMode, saveAll as setConnections } from './connections';
import type { AuthSession, Settings, SyncMode } from '$lib/bridge/types';

interface SessionState {
  settings: Settings | null;
  session: AuthSession | null;
  ready: boolean;
}

const initial: SessionState = { settings: null, session: null, ready: false };
const _state = writable<SessionState>(initial);

export const sessionStore = { subscribe: _state.subscribe };

export const settings = derived(_state, ($s) => $s.settings);
export const session = derived(_state, ($s) => $s.session);
export const ready = derived(_state, ($s) => $s.ready);

/** Returns true if the current mode requires auth AND a session exists. */
export const isAuthenticated = derived(_state, ($s) => {
  if (!$s.settings) return false;
  if ($s.settings.mode !== 'server') return true;
  return $s.session !== null;
});

/** Returns true if the current mode requires auth but no session exists. */
export const needsLogin = derived(_state, ($s) => {
  return $s.ready && $s.settings?.mode === 'server' && $s.session === null;
});

/** Loads settings + optionally the session at app start. */
export async function hydrate(): Promise<void> {
  try {
    const s = await bridge.loadSettings();
    setLanguage(s.language);
    let sess: AuthSession | null = null;
    if (s.mode === 'server') {
      try {
        sess = await bridge.checkSession();
      } catch {
        sess = null;
      }
    }
    _state.set({ settings: s, session: sess, ready: true });
  } catch (err) {
    console.error('hydrate failed', err);
    _state.set({ settings: null, session: null, ready: true });
  }
}

export async function login(serverUrl: string, username: string, password: string): Promise<void> {
  const current = get(_state);
  const allowSelfSigned = current.settings?.allowSelfSignedCerts ?? false;
  const sess = await bridge.login(serverUrl, username, password, allowSelfSigned);
  _state.update((s) => ({ ...s, session: sess }));
  // Fetch connections fresh from the new server — prevents the old
  // connections.json file cache from staying visible after a server switch.
  if (current.settings) {
    await reloadForMode(current.settings, sess);
  }
}

export async function logout(): Promise<void> {
  try {
    await bridge.logout();
  } finally {
    // First clear the connection cache (memory + file via saveAll([])), then
    // set session to null — otherwise subscribers briefly see the old
    // data in the already-logged-out state.
    try {
      await setConnections([]);
    } catch {
      /* cache cleanup must not block logout */
    }
    _state.update((s) => ({ ...s, session: null }));
  }
}

export async function setMode(mode: SyncMode): Promise<void> {
  const current = get(_state);
  if (!current.settings) return;
  const next = { ...current.settings, mode };
  await bridge.saveSettings(next);
  _state.update((s) => ({ ...s, settings: next }));
}

export async function refreshSettings(): Promise<void> {
  const s = await bridge.loadSettings();
  _state.update((st) => ({ ...st, settings: s }));
}
