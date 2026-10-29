// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The notifications run while a server session is active and restart only when the server or
// the user changes (R-0663). Saving the settings re-emits an equal session object; that must
// not stop the stream, empty the feed and start it again. The notifications store is mocked
// to count the calls; the session changes through the store, as in the app.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import type { AuthSession, Settings } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  activateNotifications: vi.fn(async () => {}),
  deactivateNotifications: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({
  workspaceContext: vi.fn(async () => ({ launcher: false, workspace: null })),
  openLauncher: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { settings: writable(null), session: writable(null) };
});
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }));
vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn(async () => '0.0.0') }));
vi.mock('$lib/stores/settings', () => ({
  openSettings: vi.fn(),
  logoutAndReload: vi.fn(),
  listenForSessionExpiry: vi.fn(async () => () => {}),
  startSyncTimer: vi.fn(),
  stopSyncTimer: vi.fn(),
}));
vi.mock('$lib/stores/notifications', () => ({
  activateNotifications: h.activateNotifications,
  deactivateNotifications: h.deactivateNotifications,
  setNewNotificationHandler: vi.fn(),
}));
vi.mock('$lib/stores/tunnel', () => ({
  markTerminated: vi.fn(),
  markError: vi.fn(),
  startIfServerMode: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/connectFlow', () => ({ markRdpError: vi.fn() }));
vi.mock('$lib/stores/connections', async () => {
  const { writable } = await import('svelte/store');
  return { searchTerm: writable('') };
});
vi.mock('$lib/osNotify', () => ({ notifyOs: vi.fn() }));
vi.mock('../pages/Dashboard.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Connections.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Infrastructure.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Monitoring.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Ansible.svelte', () => ({ default: vi.fn() }));
vi.mock('./ConnectionEditor.svelte', () => ({ default: vi.fn() }));
vi.mock('./PasswordPrompt.svelte', () => ({ default: vi.fn() }));
vi.mock('./SettingsModal.svelte', () => ({ default: vi.fn() }));
vi.mock('./StatusBar.svelte', () => ({ default: vi.fn() }));
vi.mock('./TunnelIndicator.svelte', () => ({ default: vi.fn() }));
vi.mock('./NotificationBell.svelte', () => ({ default: vi.fn() }));

import { settings, session } from '$lib/stores/session';
import { replace } from '$lib/router';
import AppShell from './AppShell.svelte';

const settingsState = settings as unknown as Writable<Partial<Settings> | null>;
const sessionState = session as unknown as Writable<AuthSession | null>;

const SERVER = 'https://ah.example.com';
const aliceSession = (): AuthSession => ({ serverUrl: SERVER, username: 'alice', isAdmin: false });

async function setSession(next: AuthSession | null): Promise<void> {
  sessionState.set(next);
  await tick();
}

// Logged in as alice, then the settings are saved: `session` re-emits an equal, new object.
async function loggedInThenSettingsSaved(): Promise<void> {
  render(AppShell);
  await tick();
  await setSession(aliceSession());
}

beforeEach(async () => {
  vi.clearAllMocks();
  replace('/dashboard');
  settingsState.set({ mode: 'server' });
  sessionState.set(aliceSession());
});

afterEach(() => {
  cleanup();
});

describe('AppShell: notifications follow server and user, not the session object', () => {
  it('an equal session object after saving the settings leaves them running', async () => {
    render(AppShell);
    await tick();
    expect(h.activateNotifications).toHaveBeenCalledTimes(1);

    await setSession(aliceSession());
    expect(h.activateNotifications).toHaveBeenCalledTimes(1);
    expect(h.deactivateNotifications).not.toHaveBeenCalled();
  });

  it('another user on the same server restarts them', async () => {
    await loggedInThenSettingsSaved();

    await setSession({ serverUrl: SERVER, username: 'bob', isAdmin: false });
    expect(h.deactivateNotifications).toHaveBeenCalledTimes(1);
    expect(h.activateNotifications).toHaveBeenCalledTimes(2);
  });

  it('the same user on another server restarts them', async () => {
    await loggedInThenSettingsSaved();

    await setSession({ serverUrl: 'https://ah2.example.com', username: 'alice', isAdmin: false });
    expect(h.deactivateNotifications).toHaveBeenCalledTimes(1);
    expect(h.activateNotifications).toHaveBeenCalledTimes(2);
  });

  it('without a session they stop and do not start again', async () => {
    await loggedInThenSettingsSaved();
    await setSession({ serverUrl: SERVER, username: 'bob', isAdmin: false });

    await setSession(null);
    expect(h.deactivateNotifications).toHaveBeenCalledTimes(2);
    expect(h.activateNotifications).toHaveBeenCalledTimes(2);
  });
});
