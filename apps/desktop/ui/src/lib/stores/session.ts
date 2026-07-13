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
// (no localStorage copy in the frontend). For security the session is NOT
// restored from the keyring on startup: server mode always requires a fresh
// password login each time the app is opened (see hydrate). The keyring tokens
// are only used for mid-session refresh and are overwritten by the next login.

import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { setLanguage } from '$lib/i18n';
import type { AuthSession, Settings, SyncMode } from '$lib/bridge/types';

interface SessionState {
  settings: Settings | null;
  session: AuthSession | null;
  ready: boolean;
}

// The session store must not import ./connections: that module imports
// sessionStore back, and the cycle only held together because both sides
// deferred the import into function bodies (a derived store referencing
// reloadForMode at module-eval time would break with `undefined`). Instead the
// connections store's reload/clear are wired in at app start (see main.ts).
interface ConnectionsSync {
  reload: (settings: Settings | null, session: AuthSession | null) => Promise<void>;
  clear: () => void;
}
let connectionsSync: ConnectionsSync = { reload: async () => {}, clear: () => {} };
export function registerConnectionsSync(hooks: ConnectionsSync): void {
  connectionsSync = hooks;
}

const initial: SessionState = { settings: null, session: null, ready: false };
const _state = writable<SessionState>(initial);

export const sessionStore = { subscribe: _state.subscribe };

export const settings = derived(_state, ($s) => $s.settings);
export const session = derived(_state, ($s) => $s.session);

/** The current auth session, or null. Not a `require` — callers still guard with
 * `if (!session) return`; the name says what it does (2.98). */
export function currentSession(): AuthSession | null {
  return get(_state).session;
}
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

/** Loads settings at app start. */
export async function hydrate(): Promise<void> {
  try {
    const s = await bridge.loadSettings();
    setLanguage(s.language);
    // Security: never silently restore a server session from the keyring on
    // startup. Server mode requires a fresh password login every time the app is
    // opened (the login screen pre-fills server URL + username). The enrolled
    // mTLS device cert stays in the keyring and the stale session tokens are
    // overwritten by the next successful login; mid-session token refresh
    // (authenticated_get) is unaffected.
    _state.set({ settings: s, session: null, ready: true });
  } catch (err) {
    console.error('hydrate failed', err);
    _state.set({ settings: null, session: null, ready: true });
  }
}

export async function login(serverUrl: string, username: string, password: string): Promise<void> {
  const current = get(_state);
  const allowSelfSigned = current.settings?.allowSelfSignedCerts ?? false;
  const sess = await bridge.login(serverUrl, username, password, allowSelfSigned);

  // Persist server URL + username (never the password) so the next start can
  // pre-fill the login screen and only ask for the password. Best-effort: a
  // failed save must not block an otherwise successful login.
  let next = current.settings;
  if (current.settings) {
    next = { ...current.settings, serverUrl: serverUrl.trim(), lastUsername: username.trim() };
    try {
      await bridge.saveSettings(next);
    } catch {
      next = current.settings;
    }
  }

  // Fetch connections fresh from the new server — prevents the old
  // connections.json file cache from staying visible after a server switch.
  _state.update((s) => ({ ...s, settings: next ?? s.settings, session: sess }));
  if (next) {
    await connectionsSync.reload(next, sess);
  }
}

export async function logout(): Promise<void> {
  try {
    await bridge.logout();
  } finally {
    // Drop the in-memory list first (server/sync connections are held only as a
    // transient cache in connections.json), then null the session — otherwise
    // subscribers briefly see the old data in the already-logged-out state.
    // Crucially this does NOT touch connections.json: in local mode that file is
    // the persistent store and overwriting it here would erase the user's saved
    // connections.
    connectionsSync.clear();
    _state.update((s) => ({ ...s, session: null }));
  }
}

/** Drops the current server session: clears the keyring tokens (keeping the
 * enrolled mTLS device cert) and the in-memory session. Used when leaving
 * server mode so a later switch back forces a fresh login instead of reusing a
 * stale session still bound to the previous server URL. Connections are NOT
 * cleared here — the caller reloads them for the new mode. */
export async function dropSession(): Promise<void> {
  try {
    await bridge.logout();
  } catch {
    /* clearing local session state must not depend on the server being reachable */
  }
  _state.update((s) => ({ ...s, session: null }));
}

/** Persist "allow self-signed certificates". Used by the login screen's trust
 * dialog (ERR_TLS_UNKNOWN_ISSUER): before the first login/enrollment the
 * settings modal is unreachable, so the dialog is the only way to opt in to
 * the TOFU pin against a server running the standard own-PKI gateway. */
export async function setAllowSelfSignedCerts(allow: boolean): Promise<void> {
  const current = get(_state);
  if (!current.settings) return;
  const next = { ...current.settings, allowSelfSignedCerts: allow };
  await bridge.saveSettings(next);
  _state.update((s) => ({ ...s, settings: next }));
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
