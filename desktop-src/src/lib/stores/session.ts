// Session-Store fuer Desktop-Auth.
//
// Der Desktop kennt drei Modi (Settings.mode):
//   - 'local':  keine Server-Verbindung, keine Auth noetig
//   - 'sync':   nur JSON-Sync ueber URL, keine Auth noetig
//   - 'server': AdminHelper-Server mit Login erforderlich
//
// Auth-Token + Refresh-Token werden ausschliesslich im Rust-Keyring abgelegt
// (keine localStorage-Kopie im Frontend). Das Frontend fragt via
// bridge.checkSession() ob aktuell eine gueltige Session existiert.

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

/** Liefert true, wenn der aktuelle Modus Auth erfordert UND eine Session existiert. */
export const isAuthenticated = derived(_state, ($s) => {
  if (!$s.settings) return false;
  if ($s.settings.mode !== 'server') return true;
  return $s.session !== null;
});

/** Liefert true, wenn der aktuelle Modus Auth erfordert, aber keine Session existiert. */
export const needsLogin = derived(_state, ($s) => {
  return $s.ready && $s.settings?.mode === 'server' && $s.session === null;
});

/** Laedt Settings + optional Session beim App-Start. */
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

export async function login(
  serverUrl: string,
  username: string,
  password: string,
): Promise<void> {
  const current = get(_state);
  const allowSelfSigned = current.settings?.allowSelfSignedCerts ?? false;
  const sess = await bridge.login(serverUrl, username, password, allowSelfSigned);
  _state.update((s) => ({ ...s, session: sess }));
  // Connections vom neuen Server frisch holen — verhindert, dass nach
  // Server-Wechsel der alte connections.json-Datei-Cache sichtbar bleibt.
  if (current.settings) {
    await reloadForMode(current.settings, sess);
  }
}

export async function logout(): Promise<void> {
  try {
    await bridge.logout();
  } finally {
    // Erst Connection-Cache leeren (Memory + Datei via saveAll([])), dann
    // Session auf null setzen — sonst sehen Subscriber kurz die alten
    // Daten im bereits ausgeloggten State.
    try {
      await setConnections([]);
    } catch {
      /* Cache-Cleanup darf Logout nicht blocken */
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
