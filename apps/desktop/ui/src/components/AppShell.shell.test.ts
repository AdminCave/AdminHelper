// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

// The shell after the DS mockup (R-1062): the active page is marked for assistive tech and
// by weight and a bar, the sidebar is 232 px and 68 px collapsed, the header shows an avatar
// with the user name. The classes the live specs drive stay in place. Bridge and stores are
// mocked as in AppShell.workspace.test.ts; the pages and panels are stubs.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import type { AuthSession, Settings, WorkspaceContext } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';

const h = vi.hoisted(() => ({
  workspaceContext: vi.fn<() => Promise<WorkspaceContext>>(),
  logoutAndReload: vi.fn(),
  initiateConnect: vi.fn(),
  openSettings: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({
  workspaceContext: h.workspaceContext,
  openLauncher: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { settings: writable(null), session: writable(null) };
});
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }));
vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn(async () => '0.0.0') }));
vi.mock('$lib/stores/settings', () => ({
  openSettings: h.openSettings,
  logoutAndReload: h.logoutAndReload,
  listenForSessionExpiry: vi.fn(async () => () => {}),
  startSyncTimer: vi.fn(),
  stopSyncTimer: vi.fn(),
}));
vi.mock('$lib/stores/notifications', () => ({
  activateNotifications: vi.fn(async () => {}),
  deactivateNotifications: vi.fn(),
  setNewNotificationHandler: vi.fn(),
}));
vi.mock('$lib/stores/tunnel', () => ({
  markTerminated: vi.fn(),
  markError: vi.fn(),
  startIfServerMode: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/connectFlow', () => ({
  markRdpError: vi.fn(),
  initiateConnect: h.initiateConnect,
}));
vi.mock('$lib/stores/connections', async () => {
  const { writable } = await import('svelte/store');
  return {
    searchTerm: writable(''),
    connections: writable([
      {
        id: 'c1',
        name: 'Backup NAS',
        kind: 'ssh',
        host: 'nas.example',
        tags: [],
        trustCert: false,
      },
    ]),
  };
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
vi.mock('./StatusFooter.svelte', () => ({ default: vi.fn() }));
vi.mock('./TunnelIndicator.svelte', () => ({ default: vi.fn() }));
vi.mock('./NotificationBell.svelte', () => ({ default: vi.fn() }));

import { settings, session } from '$lib/stores/session';
import { loadContext } from '$lib/stores/workspace';
import { replace } from '$lib/router';
import AppShell from './AppShell.svelte';
import StatusFooter from './StatusFooter.svelte';

const settingsState = settings as unknown as Writable<Partial<Settings> | null>;
const sessionState = session as unknown as Writable<AuthSession | null>;

const APP_CSS = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '..', 'styles', 'app.css'),
  'utf-8',
);

// The declarations of a top-level rule with exactly this selector.
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = new RegExp(`^${escaped}\\s*\\{([^}]*)\\}`, 'm').exec(APP_CSS);
  expect(m, `rule ${selector} in app.css`).not.toBeNull();
  return m![1];
}

async function serverSession(): Promise<void> {
  h.workspaceContext.mockResolvedValue({
    launcher: false,
    workspace: {
      id: 'w-0a1b2c3d',
      name: 'Kunde A',
      color: '#3b82f6',
      kind: 'server',
      url: 'https://ah.example.com',
      host: 'ah.example.com',
      open: true,
    },
  });
  await loadContext();
  settingsState.set({ mode: 'server' });
  sessionState.set({
    serverUrl: 'https://ah.example.com',
    username: 'Kevin Stenzel',
    isAdmin: true,
  });
}

beforeAll(() => {
  setLanguage('en');
});

beforeEach(async () => {
  vi.clearAllMocks();
  replace('/dashboard');
  settingsState.set({ mode: 'local' });
  sessionState.set(null);
  h.workspaceContext.mockResolvedValue({ launcher: true, workspace: null });
  await loadContext();
});

afterEach(() => {
  cleanup();
});

describe('AppShell: sidebar', () => {
  it('marks the active page with aria-current and the active class, and only that one', () => {
    replace('/connections');
    const view = render(AppShell);
    const items = [...view.container.querySelectorAll<HTMLElement>('.sidebar-nav .sidebar-item')];
    const active = items.filter((el) => el.getAttribute('aria-current') === 'page');
    expect(active.map((el) => el.dataset.nav)).toEqual(['connections']);
    expect(items.filter((el) => el.classList.contains('active'))).toEqual(active);
  });

  it('follows the route: the dashboard is active on a page the mode does not show', () => {
    replace('/monitoring');
    const view = render(AppShell);
    const current = view.container.querySelector('.sidebar-nav [aria-current="page"]');
    expect((current as HTMLElement | null)?.dataset.nav).toBe('dashboard');
  });

  it('collapses and expands with the button, which says what it will do', async () => {
    const view = render(AppShell);
    const shell = view.container.querySelector<HTMLElement>('.app-shell')!;
    await fireEvent.click(view.getByRole('button', { name: tNow('sidebar.collapse') }));
    expect(shell.classList.contains('sidebar-collapsed')).toBe(true);
    await fireEvent.click(view.getByRole('button', { name: tNow('sidebar.expand') }));
    expect(shell.classList.contains('sidebar-collapsed')).toBe(false);
  });

  it('is 232 px wide and 68 px collapsed; the active item is bold with a bar, without a fill', () => {
    expect(rule(':root')).toMatch(/--sidebar-width:\s*232px;/);
    expect(rule('.app-shell.sidebar-collapsed')).toMatch(/--sidebar-width:\s*68px;/);
    const active = rule('.sidebar-item.active');
    expect(active).toMatch(/font-weight:\s*600;/);
    expect(active).not.toMatch(/background/);
    expect(rule('.sidebar-item.active::before')).toMatch(/width:\s*3px;/);
  });

  it('keeps the classes the live specs drive', () => {
    const view = render(AppShell);
    const c = view.container;
    expect(c.querySelectorAll('.sidebar-nav .sidebar-item').length).toBeGreaterThan(0);
    // The first item at the bottom opens the settings, the one with an aria-label is the theme.
    const bottom = [...c.querySelectorAll<HTMLElement>('.sidebar-bottom .sidebar-item')];
    expect(bottom[0].textContent?.trim()).toBe(tNow('settings.label'));
    const labelled = c.querySelectorAll('.sidebar-bottom .sidebar-item[aria-label]');
    expect(labelled.length).toBe(1);
    expect(labelled[0].getAttribute('aria-label')).toBe(tNow('theme.toggle'));
  });
});

describe('AppShell: header', () => {
  it('without a session neither avatar nor sign-out', () => {
    const view = render(AppShell);
    expect(view.container.querySelector('.content-header .ui-avatar')).toBeNull();
    expect(view.container.querySelector('.content-header-right .btn.ghost.small')).toBeNull();
  });

  it('with a server session shows the avatar, the user name and the sign-out button', async () => {
    await serverSession();
    const view = render(AppShell);
    const header = view.container.querySelector<HTMLElement>('.content-header')!;
    expect(header.querySelector('.ui-avatar')?.textContent).toBe('KS');
    expect(header.querySelector('.header-user-name')?.textContent).toBe('Kevin Stenzel');

    const logout = header.querySelector<HTMLElement>('.content-header-right .btn.ghost.small')!;
    expect(logout.textContent?.trim()).toBe(tNow('nav.logout'));
    await fireEvent.click(logout);
    expect(h.logoutAndReload).toHaveBeenCalledOnce();
  });
});

describe('AppShell: status footer', () => {
  it('renders the footer in a third grid row under the content', () => {
    render(AppShell);
    expect(StatusFooter).toHaveBeenCalledOnce();
    expect(rule('.app-shell')).toMatch(
      /grid-template-rows:\s*var\(--header-height\)\s+1fr\s+var\(--footer-height\);/,
    );
    const footer = rule('.status-footer');
    expect(footer).toMatch(/grid-row:\s*3;/);
    expect(footer).toMatch(/font-family:\s*var\(--font-mono\);/);
    expect(footer).toMatch(/font-size:\s*11px;/);
  });
});

describe('AppShell: command palette', () => {
  function paletteLabels(): string[] {
    return [...document.querySelectorAll('.palette-item .palette-label')].map(
      (el) => el.textContent ?? '',
    );
  }

  it('opens with Ctrl+K from inside an input and hands the focus back on Escape', async () => {
    replace('/connections');
    const view = render(AppShell);
    const search = view.container.querySelector<HTMLInputElement>('.search-box input')!;
    search.focus();
    await fireEvent.keyDown(search, { key: 'k', ctrlKey: true });
    await tick();
    const input = document.querySelector<HTMLInputElement>('.palette-input');
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);

    await fireEvent.keyDown(document, { key: 'Escape' });
    await tick();
    expect(document.querySelector('.palette')).toBeNull();
    expect(document.activeElement).toBe(search);
  });

  it('opens with Cmd+K and from the header button, but not on a plain k', async () => {
    const view = render(AppShell);
    await fireEvent.keyDown(window, { key: 'k' });
    await tick();
    expect(document.querySelector('.palette')).toBeNull();

    await fireEvent.keyDown(window, { key: 'K', metaKey: true });
    await tick();
    expect(document.querySelector('.palette')).not.toBeNull();
    await fireEvent.keyDown(document, { key: 'Escape' });
    await tick();

    const button = view.container.querySelector<HTMLElement>('.header-palette-btn')!;
    expect(button.getAttribute('aria-label')).toBe(tNow('palette.open'));
    await fireEvent.click(button);
    await tick();
    expect(document.querySelector('.palette')).not.toBeNull();
  });

  it('stays shut over another dialog and follows the K key on other layouts', async () => {
    render(AppShell);
    const other = document.createElement('div');
    other.setAttribute('role', 'dialog');
    other.setAttribute('aria-modal', 'true');
    document.body.appendChild(other);
    await fireEvent.keyDown(window, { key: 'k', code: 'KeyK', ctrlKey: true });
    await tick();
    expect(document.querySelector('.palette')).toBeNull();
    other.remove();

    await fireEvent.keyDown(window, { key: '\u043b', code: 'KeyK', ctrlKey: true });
    await tick();
    expect(document.querySelector('.palette')).not.toBeNull();
  });

  it('lists connections, the pages of this mode and the actions', async () => {
    render(AppShell);
    await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await tick();
    expect(paletteLabels()).toEqual([
      'Backup NAS',
      tNow('nav.dashboard'),
      tNow('nav.connections'),
      tNow('connections.new'),
      tNow('settings.label'),
      tNow('theme.toggle'),
      tNow('workspace.openLauncher'),
    ]);
  });

  it('server mode adds its pages; at most nine entries show', async () => {
    await serverSession();
    render(AppShell);
    await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await tick();
    const labels = paletteLabels();
    expect(labels).toHaveLength(9);
    expect(labels).toContain(tNow('nav.monitoring'));
  });

  it('Enter on a connection connects through the usual path, on a page navigates', async () => {
    const view = render(AppShell);
    await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await tick();
    const input = document.querySelector<HTMLInputElement>('.palette-input')!;
    await fireEvent.input(input, { target: { value: 'nas' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    await tick();
    expect(h.initiateConnect).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }));
    expect(document.querySelector('.palette')).toBeNull();

    await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await tick();
    const again = document.querySelector<HTMLInputElement>('.palette-input')!;
    await fireEvent.input(again, { target: { value: tNow('nav.connections') } });
    await fireEvent.keyDown(again, { key: 'Enter' });
    await tick();
    // navigate() sets the hash; the route follows on the hashchange event.
    await waitFor(() =>
      expect(
        view.container.querySelector('[data-nav="connections"]')?.getAttribute('aria-current'),
      ).toBe('page'),
    );
  });

  it('an action runs on Enter', async () => {
    render(AppShell);
    await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await tick();
    const input = document.querySelector<HTMLInputElement>('.palette-input')!;
    await fireEvent.input(input, { target: { value: tNow('settings.label') } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(h.openSettings).toHaveBeenCalledOnce();
  });
});
