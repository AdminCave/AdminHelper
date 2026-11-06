// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Sessions of the embedded terminal in the shell (R-1069): the tab bar comes with the first
// session and goes with the last, the page and every session stay mounted behind the tab in
// front, the sidebar and a route change bring the page back, the header names the session in
// front, closing a running session asks when the options say so, and Ctrl+K stays with the shell
// inside a terminal. A detached session keeps its tab but leaves its pane (R-1070); docked, it gets a
// new terminal. The real store of the sessions runs on a mocked bridge and a fake xterm.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import type { TerminalMessage } from '$lib/bridge';
import type { Connection, Settings } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { getSettingsDefaults, getTerminalDefaults } from '$lib/models/settings';

const h = vi.hoisted(() => {
  class FakeTerminal {
    static all: FakeTerminal[] = [];
    options: Record<string, unknown>;
    cols = 80;
    rows = 24;
    dispose = vi.fn();
    constructor(options: Record<string, unknown>) {
      this.options = { ...options };
      FakeTerminal.all.push(this);
    }
    // As xterm: its element, with the textarea that takes the keys, inside the host.
    open(parent: HTMLElement): void {
      const el = document.createElement('div');
      el.className = 'xterm';
      el.appendChild(document.createElement('textarea'));
      parent.appendChild(el);
    }
    write(): void {}
    reset(): void {}
    focus(): void {}
    loadAddon(): void {}
    clearSelection(): void {}
    paste(): void {}
    hasSelection(): boolean {
      return false;
    }
    getSelection(): string {
      return '';
    }
    attachCustomKeyEventHandler(): void {}
    onData() {
      return { dispose: () => {} };
    }
    onBinary() {
      return { dispose: () => {} };
    }
    onResize() {
      return { dispose: () => {} };
    }
  }
  return {
    FakeTerminal,
    channels: [] as ((message: TerminalMessage) => void)[],
    terminalOpenSsh: vi.fn(),
    terminalClose: vi.fn(async () => {}),
    terminalAttach: vi.fn(),
    terminalDetach: vi.fn(async () => {}),
    listeners: new Map<string, (e: { payload: unknown }) => void>(),
    confirm: vi.fn<(message: string) => Promise<boolean>>(),
  };
});

vi.mock('@xterm/xterm', () => ({ Terminal: h.FakeTerminal }));
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit(): void {}
  },
}));
vi.mock('@xterm/addon-search', () => ({ SearchAddon: class {} }));
vi.mock('$lib/bridge', () => ({
  workspaceContext: vi.fn(async () => ({ launcher: true, workspace: null })),
  openLauncher: vi.fn(async () => {}),
  terminalOpenSsh: h.terminalOpenSsh,
  terminalClose: h.terminalClose,
  terminalCloseAll: vi.fn(async () => {}),
  terminalWrite: vi.fn(async () => {}),
  terminalResize: vi.fn(async () => {}),
  terminalAttach: h.terminalAttach,
  terminalDetach: h.terminalDetach,
  terminalDock: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    setOpenSessions: vi.fn(async () => {}),
    settings: writable(null),
    session: writable(null),
    refreshSettings: vi.fn(),
  };
});
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async (name: string, handler: (e: { payload: unknown }) => void) => {
    h.listeners.set(name, handler);
    return () => {};
  }),
}));
vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn(async () => '0.0.0') }));
vi.mock('$lib/stores/settings', () => ({
  openSettings: vi.fn(),
  logoutAndReload: vi.fn(),
  listenForSessionExpiry: vi.fn(async () => () => {}),
  startSyncTimer: vi.fn(),
  stopSyncTimer: vi.fn(),
}));
vi.mock('$lib/stores/notifications', () => ({
  activateNotifications: vi.fn(async () => {}),
  deactivateNotifications: vi.fn(),
  setNewNotificationHandler: vi.fn(),
}));
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return {
    markTerminated: vi.fn(),
    markError: vi.fn(),
    startIfServerMode: vi.fn(async () => {}),
    getMappings: vi.fn(() => []),
    tunnelMappings: writable([]),
  };
});
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
vi.mock('./ui/ConfirmDialog.svelte', async (orig) => ({
  ...(await orig<typeof import('./ui/ConfirmDialog.svelte')>()),
  confirmDialog: h.confirm,
}));
vi.mock('$lib/osNotify', () => ({ notifyOs: vi.fn() }));
vi.mock('../pages/Dashboard.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Connections.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Infrastructure.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Monitoring.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Ansible.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Notifications.svelte', () => ({ default: vi.fn() }));
vi.mock('./ConnectionEditor.svelte', () => ({ default: vi.fn() }));
vi.mock('./PasswordPrompt.svelte', () => ({ default: vi.fn() }));
vi.mock('./SettingsModal.svelte', () => ({ default: vi.fn() }));
vi.mock('./StatusBar.svelte', () => ({ default: vi.fn() }));
vi.mock('./StatusFooter.svelte', () => ({ default: vi.fn() }));
vi.mock('./TunnelIndicator.svelte', () => ({ default: vi.fn() }));
vi.mock('./NotificationBell.svelte', () => ({ default: vi.fn() }));

import { settings } from '$lib/stores/session';
import { replace } from '$lib/router';
import { closeAllTerminals, openTerminal } from '$lib/stores/terminals';
import AppShell from './AppShell.svelte';
import Dashboard from '../pages/Dashboard.svelte';

const settingsState = settings as unknown as Writable<Settings | null>;

function conn(name: string): Connection {
  return { id: name, name, kind: 'ssh', host: `${name}.example` } as Connection;
}

const WEB = conn('web');
const DB = conn('db');

/** Opens `c` as the next session; its program runs once it has sent something. */
async function open(c: Connection, output = true): Promise<number> {
  const n = h.channels.length;
  await openTerminal(c, c);
  if (output) h.channels[n](new Uint8Array([0x24]).buffer);
  await tick();
  return n;
}

function exit(n: number): void {
  h.channels[n]({ exitCode: 0 });
}

const tablist = () => screen.queryByRole('tablist', { name: tNow('terminal.tabs') });
const tab = (name: string | RegExp) => within(tablist()!).getByRole('tab', { name });
const page = () => document.querySelector<HTMLElement>('main.content-main')!;
const panes = () => [...document.querySelectorAll<HTMLElement>('.terminal-pane')];
const shown = (el: HTMLElement) => !el.classList.contains('hidden');
const title = () => document.querySelector('.page-title')?.textContent;
const subtitle = () => document.querySelector('.page-subtitle')?.textContent ?? null;

function withPrefs(confirmClose: boolean): void {
  settingsState.set({
    ...getSettingsDefaults(),
    terminal: { ...getTerminalDefaults(), confirmClose },
  });
}

beforeAll(() => setLanguage('en'));

beforeEach(async () => {
  vi.clearAllMocks();
  h.FakeTerminal.all = [];
  h.channels = [];
  let id = 0;
  h.terminalOpenSsh.mockImplementation(
    async (_c: Connection, _cols: number, _rows: number, onMessage) => {
      h.channels.push(onMessage);
      id += 1;
      return id;
    },
  );
  h.terminalAttach.mockImplementation(async (_id: number, onMessage) => {
    h.channels.push(onMessage);
  });
  replace('/connections');
  withPrefs(true);
  await closeAllTerminals();
});

afterEach(() => cleanup());

describe('AppShell: sessions of the embedded terminal', () => {
  it('shows the tab bar from the first session on and hides it with the last', async () => {
    render(AppShell);
    expect(tablist()).toBeNull();
    expect(panes()).toEqual([]);

    const n = await open(WEB);
    expect(tablist()).not.toBeNull();
    expect(
      within(tablist()!)
        .getAllByRole('tab')
        .map((t) => t.textContent?.trim()),
    ).toEqual([tNow('nav.connections'), 'web']);
    expect(tab(/web/).getAttribute('aria-selected')).toBe('true');
    expect(title()).toBe('web');
    expect(subtitle()).toBe('SSH · web.example');

    exit(n);
    await tick();
    await fireEvent.click(
      screen.getByRole('button', { name: tNow('terminal.tabs.close', { name: 'web' }) }),
    );
    await tick();
    expect(tablist()).toBeNull();
    expect(panes()).toEqual([]);
    expect(shown(page())).toBe(true);
    expect(title()).toBe(tNow('nav.connections'));
    expect(subtitle()).toBeNull();
  });

  it('keeps the page and every session mounted behind the tab in front', async () => {
    render(AppShell);
    await open(WEB);
    await open(DB);
    const [web, db] = panes();
    // A terminal starts once its font has loaded.
    await waitFor(() => expect(h.FakeTerminal.all).toHaveLength(2));
    expect([shown(page()), shown(web), shown(db)]).toEqual([false, false, true]);
    expect(title()).toBe('db');

    await fireEvent.click(tab(/web/));
    expect([shown(page()), shown(web), shown(db)]).toEqual([false, true, false]);
    expect(title()).toBe('web');

    await fireEvent.click(tab(tNow('nav.connections')));
    expect([shown(page()), shown(web), shown(db)]).toEqual([true, false, false]);
    expect(title()).toBe(tNow('nav.connections'));
    expect(subtitle()).toBeNull();

    // The same terminals all along: none was made anew or disposed.
    expect(panes()).toEqual([web, db]);
    expect(h.FakeTerminal.all).toHaveLength(2);
    expect(h.FakeTerminal.all.map((t) => t.dispose.mock.calls.length)).toEqual([0, 0]);
  });

  it('brings the page to the front from the sidebar, also the page already open', async () => {
    const view = render(AppShell);
    await open(WEB);
    expect(shown(page())).toBe(false);

    await fireEvent.click(view.container.querySelector<HTMLElement>('[data-nav="connections"]')!);
    expect(shown(page())).toBe(true);
    expect(tab(tNow('nav.connections')).getAttribute('aria-selected')).toBe('true');
    expect(panes()).toHaveLength(1);
  });

  it('brings the page to the front when the route changes another way', async () => {
    render(AppShell);
    await open(WEB);
    vi.mocked(Dashboard).mockClear();

    replace('/dashboard');
    await tick();
    expect(shown(page())).toBe(true);
    expect(Dashboard).toHaveBeenCalled();
    expect(tab(tNow('nav.dashboard')).getAttribute('aria-selected')).toBe('true');
  });

  it('asks before it ends a running session and keeps it when the answer is no', async () => {
    render(AppShell);
    await open(WEB);
    await open(DB);

    h.confirm.mockResolvedValueOnce(false);
    await fireEvent.click(
      screen.getByRole('button', { name: tNow('terminal.tabs.close', { name: 'web' }) }),
    );
    expect(h.confirm).toHaveBeenCalledExactlyOnceWith(
      tNow('terminal.confirmEnd', { name: 'web' }),
      { confirmLabel: tNow('terminal.close') },
    );
    await tick();
    expect(panes()).toHaveLength(2);
    expect(h.terminalClose).not.toHaveBeenCalled();

    // The end in the header of the terminal asks the same; yes ends the program and brings the
    // tab before it to the front.
    h.confirm.mockResolvedValueOnce(true);
    const [, db] = panes();
    await fireEvent.click(within(db).getByRole('button', { name: tNow('terminal.close') }));
    await waitFor(() => expect(panes()).toHaveLength(1));
    expect(h.confirm).toHaveBeenCalledTimes(2);
    expect(h.terminalClose).toHaveBeenCalledExactlyOnceWith(2);
    expect(tab(/web/).getAttribute('aria-selected')).toBe('true');
    expect(title()).toBe('web');
  });

  it('closes without asking a session that has ended or when the options say so', async () => {
    render(AppShell);
    const n = await open(WEB);
    exit(n);
    await tick();
    await fireEvent.click(
      screen.getByRole('button', { name: tNow('terminal.tabs.close', { name: 'web' }) }),
    );
    await tick();
    expect(panes()).toHaveLength(0);
    // Its program has ended already: nothing to end.
    expect(h.terminalClose).not.toHaveBeenCalled();

    withPrefs(false);
    await open(DB);
    await fireEvent.click(
      screen.getByRole('button', { name: tNow('terminal.tabs.close', { name: 'db' }) }),
    );
    await tick();
    expect(panes()).toHaveLength(0);
    expect(h.terminalClose).toHaveBeenCalledExactlyOnceWith(2);
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it('leaves Ctrl+K to the shell inside a terminal and opens the palette outside it', async () => {
    render(AppShell);
    await open(WEB);
    await waitFor(() => expect(panes()[0].querySelector('.xterm textarea')).not.toBeNull());
    const textarea = panes()[0].querySelector<HTMLTextAreaElement>('.xterm textarea')!;

    const inside = new KeyboardEvent('keydown', {
      key: 'k',
      code: 'KeyK',
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    textarea.dispatchEvent(inside);
    await tick();
    expect(inside.defaultPrevented).toBe(false);
    expect(document.querySelector('.palette')).toBeNull();

    await fireEvent.keyDown(tab(/web/), { key: 'k', code: 'KeyK', ctrlKey: true });
    await tick();
    expect(document.querySelector('.palette')).not.toBeNull();
  });

  it('leaves the pane of a detached session and makes a new terminal once it docks', async () => {
    render(AppShell);
    await open(WEB);
    await open(DB);
    await waitFor(() => expect(h.FakeTerminal.all).toHaveLength(2));

    await fireEvent.click(
      screen.getByRole('button', { name: tNow('terminal.tabs.detach', { name: 'db' }) }),
    );
    await waitFor(() => expect(panes()).toHaveLength(1));
    expect(h.terminalDetach).toHaveBeenCalledExactlyOnceWith(2, 'db');
    expect(h.FakeTerminal.all[1].dispose).toHaveBeenCalled();
    // The tab stays, the one before it comes to the front.
    expect(tab(/db/).getAttribute('title')).toBe(tNow('terminal.tabs.detached'));
    expect(tab(/web/).getAttribute('aria-selected')).toBe('true');

    // A click on it brings its window to the front and leaves the shell as it is.
    await fireEvent.click(tab(/db/));
    expect(h.terminalDetach).toHaveBeenCalledTimes(2);
    expect(panes()).toHaveLength(1);

    await waitFor(() => expect(h.listeners.has('terminal-docked')).toBe(true));
    h.listeners.get('terminal-docked')!({ payload: { id: 2 } });
    await waitFor(() => expect(panes()).toHaveLength(2));
    await waitFor(() => expect(h.FakeTerminal.all).toHaveLength(3));
    expect(h.terminalAttach).toHaveBeenCalledExactlyOnceWith(2, expect.any(Function));
    expect(tab(/db/).getAttribute('aria-selected')).toBe('true');
    expect(tab(/db/).getAttribute('title')).toBeNull();
    expect(title()).toBe('db');
  });
});
