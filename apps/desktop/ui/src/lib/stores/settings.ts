// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Settings store: modal state, persistence and sync timer.

import { writable, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { sessionStore, refreshSettings } from './session';
import * as tunnelStore from './tunnel';
import { reloadForMode } from './connections';
import { reportError, showStatus } from './statusBar';
import { getIntervalMinutes, getSettingsDefaults, validateSettings } from '$lib/models/settings';
import { setLanguage, tNow } from '$lib/i18n';
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
  try {
    await reloadForMode(current, null);
    if (notify) showStatus(tNow('status.syncSuccess'));
  } catch (err) {
    if (notify) {
      reportError(err instanceof Error ? err.message : String(err));
    }
  }
}

export interface SaveResult {
  ok: boolean;
  needsLogin?: { serverUrl: string };
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
  if (serverUrlChanged && get(sessionStore).session) {
    await serverLogout();
  }

  try {
    await bridge.saveSettings(next);
    await refreshSettings();
    setLanguage(next.language);

    const { session } = get(sessionStore);

    if (next.mode === 'server') {
      stopSyncTimer();
      if (!session) {
        closeSettings();
        return { ok: true, needsLogin: { serverUrl: next.serverUrl ?? '' } };
      }
    } else if (next.mode === 'sync') {
      if (session) {
        try {
          await tunnelStore.stop();
        } catch {
          /* ignore */
        }
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
      }
      stopSyncTimer();
      await reloadForMode(next, null);
    }

    closeSettings();
    return { ok: true };
  } catch (err) {
    reportError(err instanceof Error ? err.message : String(err));
    return { ok: false };
  }
}

export async function serverLogout(): Promise<void> {
  try {
    await tunnelStore.stop();
  } catch {
    /* ignore */
  }
  try {
    await bridge.logout();
  } catch {
    /* ignore */
  }
  const current = get(sessionStore);
  if (current.settings) {
    await reloadForMode(current.settings, null);
  }
  closeSettings();
}
