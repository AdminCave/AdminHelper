// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Settings store: modal state, persistence and sync timer.

import { errMsg } from '$lib/utils/errors';
import { writable, get } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import * as bridge from '$lib/bridge';
import { sessionStore, refreshSettings, dropSession, logout } from './session';
import * as tunnelStore from './tunnel';
import { reloadForMode, connectionsStore } from './connections';
import { reportError, showStatus } from './statusBar';
import { getIntervalMinutes, getSettingsDefaults, validateSettings } from '$lib/models/settings';
import { setLanguage, tNow } from '$lib/i18n';
import { reloadWindow } from '$lib/utils/reloadWindow';
import { leaveLoginNotice } from '$lib/utils/loginNotice';
import type { Settings } from '$lib/bridge/types';

export const settingsModalOpen = writable<boolean>(false);

let syncTimer: ReturnType<typeof setInterval> | null = null;

export function openSettings(): void {
  settingsModalOpen.set(true);
}

export function closeSettings(): void {
  settingsModalOpen.set(false);
}

export function stopSyncTimer(): void {
  if (syncTimer) {
    clearInterval(syncTimer);
    syncTimer = null;
  }
}

export function startSyncTimer(): void {
  stopSyncTimer();
  const current = get(sessionStore).settings ?? getSettingsDefaults();
  const minutes = getIntervalMinutes(current);
  syncTimer = setInterval(() => {
    void syncNow(false);
  }, minutes * 60_000);
}

export async function syncNow(notify: boolean): Promise<void> {
  const current = get(sessionStore).settings;
  if (!current || current.mode !== 'sync' || !current.url) return;
  // reloadForMode never throws — it catches internally and records the failure in the store's
  // error state (and empties the list). Check that instead of a dead try/catch, or a failed sync
  // would clear the connection list AND still flash "sync successful" (4.42).
  await reloadForMode(current, null);
  if (!notify) return;
  const { error } = get(connectionsStore);
  if (error) reportError(error);
  else showStatus(tNow('status.syncSuccess'));
}

export interface SaveResult {
  ok: boolean;
  needsLogin?: { serverUrl: string };
}

async function tunnelRunning(): Promise<boolean> {
  try {
    return (await bridge.tunnelStatus()).running;
  } catch {
    return false; // the start then reports what is wrong
  }
}

/**
 * Saves settings, stops/starts tunnel + sync depending on the mode switch
 * and triggers a connection reload if needed. May return needsLogin.
 */
export async function saveSettings(next: Settings): Promise<SaveResult> {
  const v = validateSettings(next);
  if (!v.ok) {
    reportError(v.error ?? tNow('error.invalidSettings'));
    return { ok: false };
  }
  // A server URL change with an active session forces a logout: the old
  // JWT belongs to the old server and is rejected by the new server.
  // Without a logout, the data from the old server would stay visible in the
  // local connections.json + the store until the user logs in again.
  const previous = get(sessionStore).settings;
  const serverUrlChanged =
    previous?.mode === 'server' && next.mode === 'server' && previous.serverUrl !== next.serverUrl;
  const forcedLogout = serverUrlChanged && get(sessionStore).session !== null;
  if (forcedLogout) {
    await serverLogout();
  }

  try {
    await bridge.saveSettings(next);
    if (forcedLogout) {
      // The other stores (infrastructure, monitoring, Ansible) still hold the old server's
      // data; the reload empties them and comes up on the login screen for the new URL.
      reloadWindow();
      return { ok: true };
    }
    await refreshSettings();
    setLanguage(next.language);

    const { session } = get(sessionStore);

    if (next.mode === 'server') {
      stopSyncTimer();
      if (!session) {
        closeSettings();
        return { ok: true, needsLogin: { serverUrl: next.serverUrl ?? '' } };
      }
      // Session still valid: reload from the (possibly new) server and start the
      // tunnel. Without this, a server->local->server round-trip leaves stale
      // local data and no tunnel until the app is restarted.
      await reloadForMode(next, session);
      // A running tunnel stays: nothing it depends on changed (a new server URL
      // logged out above), and a second start next to it fails ("frpc laeuft
      // bereits"). The frpc status decides, not the indicator (R-0245).
      if (!(await tunnelRunning())) void tunnelStore.startIfServerMode();
    } else if (next.mode === 'sync') {
      if (session) {
        try {
          await tunnelStore.stop();
        } catch {
          /* ignore */
        }
        // Leaving server mode: drop the session so a later switch back forces a
        // fresh login instead of reusing a stale session bound to the old URL.
        await dropSession();
      }
      await syncNow(true);
      startSyncTimer();
    } else {
      if (session) {
        try {
          await tunnelStore.stop();
        } catch {
          /* ignore */
        }
        await dropSession();
      }
      stopSyncTimer();
      await reloadForMode(next, null);
    }

    closeSettings();
    return { ok: true };
  } catch (err) {
    reportError(errMsg(err));
    return { ok: false };
  }
}

export async function serverLogout(): Promise<void> {
  try {
    await tunnelStore.stop();
  } catch {
    /* ignore */
  }
  // dropSession ends the session in Rust AND the in-memory one — the latter
  // was previously missed here, leaving the UI in a half-logged-in state after
  // an explicit logout from the settings dialog.
  await dropSession();
  const current = get(sessionStore);
  if (current.settings) {
    await reloadForMode(current.settings, null);
  }
  closeSettings();
}

/**
 * The logout buttons of the app shell and the settings: stops the tunnel, logs out, then
 * reloads the window, so no store keeps the previous user's data. It lives here, not in
 * session.ts, because tunnel.ts imports session.ts. Unlike serverLogout it reloads no
 * connections: logout() leaves connections.json alone. A `notice` is the line the login
 * screen shows after the reload.
 */
export async function logoutAndReload(notice?: string): Promise<void> {
  try {
    await tunnelStore.stop();
  } catch {
    /* ignore */
  }
  try {
    await logout();
  } catch {
    /* logout() has dropped the session either way; the reload must not depend on it */
  }
  if (notice) leaveLoginNotice(notice);
  reloadWindow();
}

/**
 * Rust ended the session because it could not renew it (`session-expired`): out as through
 * the logout buttons, and the login screen says why. AppShell listens while it is mounted.
 */
export function listenForSessionExpiry(): Promise<UnlistenFn> {
  return listen('session-expired', () => void logoutAndReload(tNow('login.sessionExpired')));
}
