// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Settings store: modal state, persistence and sync timer.

import { errMsg } from '$lib/utils/errors';
import { writable, get } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import * as bridge from '$lib/bridge';
import { sessionStore, refreshSettings, logout } from './session';
import * as tunnelStore from './tunnel';
import { reloadForMode, connectionsStore } from './connections';
import { reportError, showStatus } from './statusBar';
import {
  getIntervalMinutes,
  getSettingsDefaults,
  validateWindowSettings,
} from '$lib/models/settings';
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
  // error state (the list stays if the last successful fetch had the same URL, else it empties).
  // Check that instead of a dead try/catch, or a failed sync would still flash "sync successful"
  // (4.42).
  await reloadForMode(current, null);
  if (!notify) return;
  const { error } = get(connectionsStore);
  if (error) reportError(error);
  else showStatus(tNow('status.syncSuccess'));
}

export interface SaveResult {
  ok: boolean;
}

/**
 * Saves the settings of this window: the fields of its workspace and the prefs of the device.
 * The kind and the URL of a workspace stay as they are (Rust keeps them), so a save neither
 * signs out nor touches the tunnel or the connections; a sync workspace restarts its timer, which
 * takes the interval saved.
 */
export async function saveSettings(next: Settings): Promise<SaveResult> {
  const v = validateWindowSettings(next);
  if (!v.ok) {
    reportError(v.error ?? tNow('error.invalidSettings'));
    return { ok: false };
  }
  try {
    await bridge.saveSettings(next);
    await refreshSettings();
    setLanguage(next.language);
    if (next.mode === 'sync') startSyncTimer();
    closeSettings();
    return { ok: true };
  } catch (err) {
    reportError(errMsg(err));
    return { ok: false };
  }
}

/**
 * The logout buttons of the app shell and the settings: stops the tunnel, logs out, then
 * reloads the window, so no store keeps the previous user's data. It lives here, not in
 * session.ts, because tunnel.ts imports session.ts. It reloads no connections: logout()
 * leaves connections.json alone. A `notice` is the line the login screen shows after the
 * reload.
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
