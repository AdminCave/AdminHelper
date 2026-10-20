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
// The session itself (server URL, access and refresh token, certificate choice)
// lives only in the Rust process; this store holds who signed in where
// (AuthSession), never a token. Nothing survives the app: server mode requires
// a fresh password login each time the app is opened (see hydrate). The mode is
// the kind of the workspace this window serves; the launcher never signs in.

import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { setLanguage, tNow } from '$lib/i18n';
import { errMsg } from '$lib/utils/errors';
import type { AuthSession, Settings } from '$lib/bridge/types';
import { reportError } from './statusBar';
import { context, loadContext } from './workspace';

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

/** Returns true in a workspace whose mode requires auth while no session exists. A window
 * without a context (it failed to load) counts as a workspace: it still asks for the login. */
export const needsLogin = derived([_state, context], ([$s, $ctx]) => {
  return (
    $s.ready && $ctx?.launcher !== true && $s.settings?.mode === 'server' && $s.session === null
  );
});

/** Loads the workspace context and the settings at app start. */
export async function hydrate(): Promise<void> {
  try {
    // Before `ready`: the launcher must never show the login, not even for a frame.
    await loadContext();
  } catch (err) {
    console.error('workspace context failed', err);
  }
  try {
    const s = await bridge.loadSettings();
    setLanguage(s.language);
    // Security: never silently restore a server session on startup. Server mode
    // requires a fresh password login every time the app is opened (the login
    // screen pre-fills server URL + username). The enrolled mTLS device cert
    // stays in the keyring; the session is renewed in Rust while the app runs.
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

  // Persist the server Rust signed in at and the username (never the password): the
  // workspace takes that server as its URL if it has none yet, the next start pre-fills the
  // username, and no other workspace signs in to this server as this user. The URL sent may be
  // the one the window shows, masked; the session names the one the workspace keeps. A failed
  // save must not block an otherwise successful login, but the user learns of it.
  let next = current.settings;
  if (current.settings) {
    next = { ...current.settings, serverUrl: sess.serverUrl, lastUsername: username.trim() };
    try {
      await bridge.saveSettings(next);
    } catch (err) {
      next = current.settings;
      reportError(tNow('login.notSaved', { message: errMsg(err) }));
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

/** Drops the current server session: ends it in Rust (keeping the enrolled
 * mTLS device cert) and clears the in-memory one. Used when leaving
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

export async function refreshSettings(): Promise<void> {
  const s = await bridge.loadSettings();
  _state.update((st) => ({ ...st, settings: s }));
}
