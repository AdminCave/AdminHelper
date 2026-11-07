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
  setNewNotificationHandler: vi.fn(),
  notifyOs: vi.fn(async () => {}),
  allows: vi.fn((_severity: string) => true),
}));

vi.mock('$lib/bridge', () => ({
  workspaceContext: vi.fn(async () => ({ launcher: false, workspace: null })),
  openLauncher: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    setOpenSessions: vi.fn(async () => {}),
    settings: writable(null),
    session: writable(null),
  };
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
  setNewNotificationHandler: h.setNewNotificationHandler,
}));
vi.mock('$lib/stores/tunnel', () => ({
  markTerminated: vi.fn(),
  markError: vi.fn(),
  startIfServerMode: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/connectFlow', () => ({ markRdpError: vi.fn(), initiateConnect: vi.fn() }));
vi.mock('$lib/stores/connections', async () => {
  const { writable } = await import('svelte/store');
  return {
    searchTerm: writable(''),
    // An empty list: the tabs of the last run are neither opened nor saved (R-1070).
    connectionsStore: writable({ items: [], loading: false }),
    connections: writable([]),
  };
});
vi.mock('$lib/osNotify', () => ({ notifyOs: h.notifyOs }));
vi.mock('$lib/stores/dnd', () => ({ allows: h.allows }));
vi.mock('../pages/Dashboard.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Connections.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Infrastructure.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Monitoring.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Ansible.svelte', () => ({ default: vi.fn() }));
vi.mock('./ConnectionEditor.svelte', () => ({ default: vi.fn() }));
vi.mock('./PasswordPrompt.svelte', () => ({ default: vi.fn() }));
vi.mock('./SettingsModal.svelte', () => ({ default: vi.fn() }));
vi.mock('./StatusBar.svelte', () => ({ default: vi.fn() }));
vi.mock('./StatusFooter.svelte', () => ({ default: vi.fn() }));
vi.mock('./CommandPalette.svelte', () => ({ default: vi.fn() }));
vi.mock('./TunnelIndicator.svelte', () => ({ default: vi.fn() }));
vi.mock('./NotificationBell.svelte', () => ({ default: vi.fn() }));

import { settings, session } from '$lib/stores/session';
import { replace } from '$lib/router';
import { get } from 'svelte/store';
import { toasts, clearStatus } from '$lib/stores/statusBar';
import type { NotificationItem } from '$lib/api/types';
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
  h.allows.mockImplementation(() => true);
  replace('/dashboard');
  settingsState.set({ mode: 'server' });
  sessionState.set(aliceSession());
});

afterEach(() => {
  cleanup();
  clearStatus();
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

// R-1078: the switch from new feed entries to toasts and OS notifications.
const entry = (id: number, severity: NotificationItem['severity']): NotificationItem => ({
  id,
  createdAt: '2026-11-04T09:00:00Z',
  severity,
  category: 'monitoring',
  eventType: 'monitoring.check.transition',
  title: `entry ${id}`,
  body: `body ${id}`,
  sourceType: 'server',
  sourceId: 'srv-1',
  read: false,
  readAt: null,
});

type Handler = ((items: NotificationItem[]) => void) | null;
const lastHandler = (): Handler =>
  h.setNewNotificationHandler.mock.calls.at(-1)?.[0] as unknown as Handler;

describe('AppShell: new entries as toasts and OS notifications', () => {
  it('shows each new entry as a toast with its tone; a critical one stands', async () => {
    render(AppShell);
    await tick();
    lastHandler()?.([entry(1, 'info'), entry(2, 'warning'), entry(3, 'critical')]);
    expect(get(toasts).map((m) => [m.text, m.body, m.tone, m.sticky])).toEqual([
      ['entry 1', 'body 1', 'info', false],
      ['entry 2', 'body 2', 'warning', false],
      ['entry 3', 'body 3', 'danger', true],
    ]);
    expect(h.notifyOs).not.toHaveBeenCalled();
  });

  it('a toast opens its entry on the center page', async () => {
    render(AppShell);
    await tick();
    lastHandler()?.([entry(7, 'warning')]);
    get(toasts)[0].onOpen?.();
    expect(location.hash).toBe('#/notifications/7');
  });

  it('sends OS notifications too, once the user opted in', async () => {
    settingsState.set({ mode: 'server', osNotifications: true });
    render(AppShell);
    await tick();
    lastHandler()?.([entry(1, 'info')]);
    expect(h.notifyOs).toHaveBeenCalledWith([entry(1, 'info')]);
    expect(get(toasts)).toHaveLength(1);
  });

  it('do not disturb holds back toast and OS notification, but not a critical entry', async () => {
    settingsState.set({ mode: 'server', osNotifications: true });
    h.allows.mockImplementation((severity: string) => severity === 'critical');
    render(AppShell);
    await tick();
    lastHandler()?.([entry(1, 'info'), entry(2, 'warning'), entry(3, 'critical')]);
    expect(get(toasts).map((m) => m.text)).toEqual(['entry 3']);
    expect(h.notifyOs).toHaveBeenCalledWith([entry(3, 'critical')]);

    h.notifyOs.mockClear();
    lastHandler()?.([entry(4, 'info')]);
    expect(h.notifyOs).not.toHaveBeenCalled();
  });
});
