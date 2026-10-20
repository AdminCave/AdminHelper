// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The window of a workspace says which one it is (R-0431): a chip with its colour and name on
// top of the sidebar, a stripe in its colour along the window, and the questions of the app
// dialog name it. The chip and "Workspaces…" bring up the launcher. A server-only page shows
// the dashboard in a workspace without a server session. The bridge is mocked; the workspace
// store, the router and the dialog are the real ones, the pages and the panels are stubs.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get, type Writable } from 'svelte/store';
import type { AuthSession, Settings, WorkspaceContext, WorkspaceInfo } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { WORKSPACE_PALETTE } from '$lib/models/workspace';

const h = vi.hoisted(() => ({
  workspaceContext: vi.fn<() => Promise<WorkspaceContext>>(),
  openLauncher: vi.fn<() => Promise<void>>(),
  Dashboard: vi.fn(),
  Infrastructure: vi.fn(),
  Monitoring: vi.fn(),
  Ansible: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({
  workspaceContext: h.workspaceContext,
  openLauncher: h.openLauncher,
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
  activateNotifications: vi.fn(async () => {}),
  deactivateNotifications: vi.fn(),
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
vi.mock('../pages/Dashboard.svelte', () => ({ default: h.Dashboard }));
vi.mock('../pages/Connections.svelte', () => ({ default: vi.fn() }));
vi.mock('../pages/Infrastructure.svelte', () => ({ default: h.Infrastructure }));
vi.mock('../pages/Monitoring.svelte', () => ({ default: h.Monitoring }));
vi.mock('../pages/Ansible.svelte', () => ({ default: h.Ansible }));
vi.mock('./ConnectionEditor.svelte', () => ({ default: vi.fn() }));
vi.mock('./PasswordPrompt.svelte', () => ({ default: vi.fn() }));
vi.mock('./SettingsModal.svelte', () => ({ default: vi.fn() }));
vi.mock('./StatusBar.svelte', () => ({ default: vi.fn() }));
vi.mock('./TunnelIndicator.svelte', () => ({ default: vi.fn() }));
vi.mock('./NotificationBell.svelte', () => ({ default: vi.fn() }));

import { settings, session } from '$lib/stores/session';
import { loadContext } from '$lib/stores/workspace';
import { status, clearStatus } from '$lib/stores/statusBar';
import { replace } from '$lib/router';
import AppShell from './AppShell.svelte';
import ConfirmDialog, { confirmDialog } from './ui/ConfirmDialog.svelte';

const settingsState = settings as unknown as Writable<Partial<Settings> | null>;
const sessionState = session as unknown as Writable<AuthSession | null>;

const kundeA: WorkspaceInfo = {
  id: 'w-0a1b2c3d',
  name: 'Kunde A',
  color: WORKSPACE_PALETTE[2],
  kind: 'local',
  url: null,
  host: null,
  open: true,
};

// jsdom gives a colour of an inline style as rgb().
const rgb = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
};

async function inWorkspace(ws: WorkspaceInfo | null): Promise<void> {
  h.workspaceContext.mockResolvedValue(
    ws ? { launcher: false, workspace: ws } : { launcher: true, workspace: null },
  );
  await loadContext();
}

beforeAll(() => {
  setLanguage('en');
});

beforeEach(async () => {
  vi.clearAllMocks();
  clearStatus();
  replace('/dashboard');
  settingsState.set({ mode: 'local' });
  sessionState.set(null);
  await inWorkspace(kundeA);
});

afterEach(() => {
  cleanup();
});

describe('AppShell: the workspace of the window', () => {
  it('the chip shows the name and the colour of the workspace, a click brings up the launcher', async () => {
    h.openLauncher.mockResolvedValue(undefined);
    const view = render(AppShell);

    const chip = view.getByRole('button', { name: 'Kunde A' });
    expect(chip.querySelector<HTMLElement>('.workspace-dot')?.style.background).toBe(
      rgb(WORKSPACE_PALETTE[2]),
    );
    // On top of the sidebar, before its navigation.
    const nav = view.container.querySelector('.sidebar-nav')!;
    expect(chip.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await fireEvent.click(chip);
    expect(h.openLauncher).toHaveBeenCalledOnce();
  });

  it('the title of the chip names the workspace, which the collapsed sidebar hides', async () => {
    const view = render(AppShell);
    const chip = view.getByRole('button', { name: 'Kunde A' });
    expect(chip.title).toBe('Kunde A — Workspaces…');

    await fireEvent.click(view.getByRole('button', { name: tNow('sidebar.collapse') }));
    const shell = view.container.querySelector<HTMLElement>('.app-shell')!;
    expect(shell.classList.contains('sidebar-collapsed')).toBe(true);
    expect(chip.title).toBe('Kunde A — Workspaces…');
  });

  it('the chip takes the place of the mode badge on the settings button', () => {
    const view = render(AppShell);
    const button = view.getByRole('button', { name: tNow('settings.label') });
    expect(button.textContent?.trim()).toBe(tNow('settings.label'));
  });

  it('"Workspaces…" brings up the launcher', async () => {
    h.openLauncher.mockResolvedValue(undefined);
    const view = render(AppShell);

    await fireEvent.click(view.getByRole('button', { name: tNow('workspace.openLauncher') }));
    expect(h.openLauncher).toHaveBeenCalledOnce();
  });

  it('a launcher that does not come up says why', async () => {
    h.openLauncher.mockRejectedValue(new Error('the launcher did not start'));
    const view = render(AppShell);

    await fireEvent.click(view.getByRole('button', { name: 'Kunde A' }));
    await waitFor(() => expect(get(status)?.text).toBe('the launcher did not start'));
    expect(get(status)?.isError).toBe(true);
  });

  it('the window carries a stripe in the colour of the workspace', () => {
    const view = render(AppShell);
    const shell = view.container.querySelector<HTMLElement>('.app-shell')!;
    expect(shell.classList.contains('workspace-stripe')).toBe(true);
    expect(shell.style.getPropertyValue('--workspace-color')).toBe(WORKSPACE_PALETTE[2]);
  });

  it('without a workspace to name neither chip nor stripe, "Workspaces…" stays', async () => {
    h.workspaceContext.mockResolvedValue({ launcher: false, workspace: null });
    await loadContext();
    const view = render(AppShell);

    expect(view.container.querySelector('.workspace-chip')).toBeNull();
    const shell = view.container.querySelector<HTMLElement>('.app-shell')!;
    expect(shell.classList.contains('workspace-stripe')).toBe(false);
    expect(shell.style.getPropertyValue('--workspace-color')).toBe('');
    expect(view.getByRole('button', { name: tNow('workspace.openLauncher') })).toBeTruthy();
  });
});

describe('AppShell: server-only pages', () => {
  it.each(['/infrastructure', '/monitoring', '/ansible'])(
    '%s in a local workspace shows the dashboard',
    (route) => {
      replace(route);
      const view = render(AppShell);

      expect(h.Dashboard).toHaveBeenCalled();
      expect(h.Infrastructure).not.toHaveBeenCalled();
      expect(h.Monitoring).not.toHaveBeenCalled();
      expect(h.Ansible).not.toHaveBeenCalled();
      expect(view.getByRole('heading', { level: 1 }).textContent).toBe(tNow('nav.dashboard'));
    },
  );

  it('/infrastructure in a sync workspace shows the dashboard', () => {
    settingsState.set({ mode: 'sync' });
    replace('/infrastructure');
    render(AppShell);

    expect(h.Dashboard).toHaveBeenCalled();
    expect(h.Infrastructure).not.toHaveBeenCalled();
  });

  it('/infrastructure with a server session shows the page', async () => {
    await inWorkspace({ ...kundeA, kind: 'server', url: 'https://ah.example.com' });
    settingsState.set({ mode: 'server' });
    sessionState.set({ serverUrl: 'https://ah.example.com', username: 'admin', isAdmin: false });
    replace('/infrastructure');
    const view = render(AppShell);

    expect(h.Infrastructure).toHaveBeenCalled();
    expect(h.Dashboard).not.toHaveBeenCalled();
    expect(view.getByRole('heading', { level: 1 }).textContent).toBe(tNow('nav.infrastructure'));
  });
});

describe('ConfirmDialog: the workspace that asks', () => {
  async function ask(): Promise<{ dialog: HTMLElement; answer: Promise<boolean> }> {
    render(ConfirmDialog);
    const answer = confirmDialog('Delete it?');
    const dialog = await waitFor(() => {
      const el = document.querySelector<HTMLElement>('[role="dialog"]');
      expect(el).not.toBeNull();
      return el!;
    });
    return { dialog, answer };
  }

  async function cancel(dialog: HTMLElement, answer: Promise<boolean>): Promise<void> {
    const button = [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(
      (b) => b.textContent?.trim() === tNow('action.cancel'),
    );
    await fireEvent.click(button!);
    await expect(answer).resolves.toBe(false);
  }

  it('names the workspace with its colour above the question', async () => {
    const { dialog, answer } = await ask();

    const named = dialog.querySelector<HTMLElement>('.confirm-workspace');
    expect(named?.textContent?.trim()).toBe('Kunde A');
    expect(named?.querySelector<HTMLElement>('.confirm-workspace-dot')?.style.background).toBe(
      rgb(WORKSPACE_PALETTE[2]),
    );
    const question = dialog.querySelector('.confirm-message')!;
    expect(question.textContent).toBe('Delete it?');
    expect(
      named!.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await cancel(dialog, answer);
  });

  it('in the launcher names none', async () => {
    await inWorkspace(null);
    const { dialog, answer } = await ask();

    expect(dialog.querySelector('.confirm-workspace')).toBeNull();
    expect(dialog.textContent).not.toContain('Kunde A');
    expect(dialog.querySelector('.confirm-message')?.textContent).toBe('Delete it?');

    await cancel(dialog, answer);
  });
});
