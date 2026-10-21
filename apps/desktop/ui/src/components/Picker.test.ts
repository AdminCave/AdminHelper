// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The picker (R-0431) is the window of the launcher: it lists the workspaces, opens one in a
// process of its own, and makes, edits and deletes the closed ones. The bridge is mocked; the
// workspace store and the editor are the real ones.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor, within } from '@testing-library/svelte';
import type {
  ResetOutcome,
  WorkspaceContext,
  WorkspaceDraft,
  WorkspaceInfo,
  WorkspaceList,
} from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { WORKSPACE_PALETTE } from '$lib/models/workspace';

const h = vi.hoisted(() => ({
  workspaceContext: vi.fn<() => Promise<WorkspaceContext>>(),
  listWorkspaces: vi.fn<() => Promise<WorkspaceList>>(),
  saveWorkspace: vi.fn<(draft: WorkspaceDraft) => Promise<string>>(),
  deleteWorkspace: vi.fn<(id: string) => Promise<ResetOutcome>>(),
  openWorkspace: vi.fn<(id: string) => Promise<void>>(),
  confirmDialog: vi.fn(async (_message: string, _options?: unknown) => true),
}));

vi.mock('$lib/bridge', () => ({
  workspaceContext: h.workspaceContext,
  listWorkspaces: h.listWorkspaces,
  saveWorkspace: h.saveWorkspace,
  deleteWorkspace: h.deleteWorkspace,
  openWorkspace: h.openWorkspace,
}));
vi.mock('./ui/ConfirmDialog.svelte', () => ({ default: vi.fn(), confirmDialog: h.confirmDialog }));
// For App: hydrate is the store's, the context comes from loadContext below.
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { hydrate: vi.fn(), ready: writable(true), needsLogin: writable(false) };
});
vi.mock('./Login.svelte', () => ({ default: vi.fn() }));
vi.mock('./AppShell.svelte', () => ({ default: vi.fn() }));

import { loadContext, refresh } from '$lib/stores/workspace';
import Picker from './Picker.svelte';
import App from '../App.svelte';

const info = (over: Partial<WorkspaceInfo> = {}): WorkspaceInfo => ({
  id: 'standard',
  name: 'Standard',
  color: WORKSPACE_PALETTE[0],
  kind: 'server',
  url: 'https://ah.example.com',
  host: 'ah.example.com',
  open: false,
  ...over,
});

const kundeA = info({ id: 'w-0a1b2c3d', name: 'Kunde A', color: WORKSPACE_PALETTE[2] });
const sync = info({
  id: 'sync',
  name: 'Sync',
  color: WORKSPACE_PALETTE[4],
  kind: 'sync',
  url: 'https://sync.example.com/c.json?token=***',
  host: 'sync.example.com',
});
const lokal = info({
  id: 'lokal',
  name: 'Lokal',
  color: WORKSPACE_PALETTE[1],
  kind: 'local',
  url: null,
  host: null,
});

const listing = (
  workspaces: WorkspaceInfo[],
  lastUsed: string | null = null,
  migratedNotice = false,
): WorkspaceList => ({ workspaces, lastUsed, migratedNotice });

async function mount(given: WorkspaceList) {
  h.listWorkspaces.mockResolvedValue(given);
  const view = render(Picker);
  await waitFor(() => expect(view.getAllByRole('option')).toHaveLength(given.workspaces.length));
  const button = (label: string) =>
    view.getByRole('button', { name: tNow(label) }) as HTMLButtonElement;
  return {
    ...view,
    list: () => view.getByRole('listbox'),
    option: (name: string) => view.getByRole('option', { name: new RegExp(name) }),
    selected: () => view.getByRole('option', { selected: true }),
    key: (key: string) => fireEvent.keyDown(view.getByRole('listbox'), { key }),
    openButton: () => button('workspace.picker.open'),
    editButton: () => button('action.edit'),
    deleteButton: () => button('action.delete'),
    newButton: () => button('workspace.picker.new'),
    msg: (name: string) => view.container.querySelector<HTMLElement>(`[data-msg="${name}"]`),
  };
}

// jsdom gives a colour of an inline style as rgb().
const rgb = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
};

beforeAll(() => {
  setLanguage('en');
});

beforeEach(async () => {
  vi.clearAllMocks();
  h.confirmDialog.mockResolvedValue(true);
  // The store outlives a test: start each one from an empty list and no error.
  h.listWorkspaces.mockResolvedValue(listing([]));
  await refresh();
});

afterEach(() => {
  cleanup();
});

describe('Picker: the list', () => {
  it('shows colour, kind, name, host or "Local", and which one is open', async () => {
    const p = await mount(listing([kundeA, sync, lokal, info({ open: true })]));

    const a = p.option('Kunde A');
    expect(a.querySelector<HTMLElement>('.picker-dot')?.style.background).toBe(
      rgb(WORKSPACE_PALETTE[2]),
    );
    expect(within(a).getByRole('img').getAttribute('aria-label')).toBe(
      tNow('settings.mode.server'),
    );
    expect(a.querySelector('.picker-host')?.textContent).toBe('ah.example.com');
    expect(within(a).queryByText(tNow('workspace.picker.isOpen'))).toBeNull();

    const s = p.option('Sync');
    expect(within(s).getByRole('img').getAttribute('aria-label')).toBe(tNow('settings.mode.sync'));
    // The host only: the URL is the editor's.
    expect(s.querySelector('.picker-host')?.textContent).toBe('sync.example.com');
    expect(s.textContent).not.toContain('token');

    const l = p.option('Lokal');
    expect(within(l).getByRole('img').getAttribute('aria-label')).toBe(tNow('settings.mode.local'));
    expect(l.querySelector('.picker-host')?.textContent).toBe(tNow('settings.mode.local'));

    expect(within(p.option('Standard')).getByText(tNow('workspace.picker.isOpen'))).not.toBeNull();
  });

  it('selects the one used last and Enter opens it, the list has the focus', async () => {
    h.openWorkspace.mockReturnValue(new Promise(() => {}));
    const p = await mount(listing([info(), kundeA, sync], 'w-0a1b2c3d'));

    expect(p.selected()).toBe(p.option('Kunde A'));
    expect(document.activeElement).toBe(p.list());
    await p.key('Enter');
    expect(h.openWorkspace).toHaveBeenCalledExactlyOnceWith('w-0a1b2c3d');
  });

  it('without a last used one selects the first', async () => {
    const p = await mount(listing([kundeA, sync]));
    expect(p.selected()).toBe(p.option('Kunde A'));
  });

  it('arrow keys move the selection within the list, Enter opens the selected one', async () => {
    h.openWorkspace.mockReturnValue(new Promise(() => {}));
    const p = await mount(listing([info(), kundeA, sync], 'standard'));

    await p.key('ArrowUp');
    expect(p.selected()).toBe(p.option('Standard'));
    await p.key('ArrowDown');
    await p.key('ArrowDown');
    await p.key('ArrowDown');
    expect(p.selected()).toBe(p.option('Sync'));
    expect(p.list().getAttribute('aria-activedescendant')).toBe(p.option('Sync').id);
    await p.key('ArrowUp');
    expect(p.selected()).toBe(p.option('Kunde A'));

    await p.key('Enter');
    expect(h.openWorkspace).toHaveBeenCalledExactlyOnceWith('w-0a1b2c3d');
  });

  it('a click selects, the button opens', async () => {
    h.openWorkspace.mockReturnValue(new Promise(() => {}));
    const p = await mount(listing([info(), kundeA], 'standard'));

    await fireEvent.click(within(p.option('Kunde A')).getByText('Kunde A'));
    expect(p.selected()).toBe(p.option('Kunde A'));
    await fireEvent.click(p.openButton());
    expect(h.openWorkspace).toHaveBeenCalledExactlyOnceWith('w-0a1b2c3d');
  });

  it('shows the note on the migration exactly once, and keeps it after a listing anew', async () => {
    const p = await mount(listing([info()], 'standard', true));
    expect(p.getAllByText(tNow('workspace.picker.migrated'))).toHaveLength(1);

    // Rust gives the note in the first listing only (launcher.rs list).
    h.listWorkspaces.mockResolvedValue(listing([info({ name: 'Standard 2' })], 'standard'));
    await fireEvent.focus(window);
    await p.findByRole('option', { name: /Standard 2/ });
    expect(p.getAllByText(tNow('workspace.picker.migrated'))).toHaveLength(1);
    cleanup();

    const again = await mount(listing([info()], 'standard'));
    expect(again.msg('migrated')).toBeNull();
  });

  it('names the settings.json set aside as unreadable, below the short note on the migration, and keeps both', async () => {
    const setAside = 'settings.json.unreadable-20261021T080000Z';
    const standard = info({ kind: 'local', url: null, host: null });
    const p = await mount({
      ...listing([standard], 'standard', true),
      unreadableSettings: setAside,
    });

    const note = p.msg('unreadable-settings');
    expect(note?.textContent?.trim()).toBe(
      tNow('workspace.picker.unreadableSettings', { name: setAside }),
    );
    expect(note?.getAttribute('role')).toBe('status');
    // What Kevin decided it says (2026-10-21): the kind of a workspace is locked in the
    // editor, and a new server workspace keeps its keys apart from the old device identity.
    const said = note?.textContent ?? '';
    expect(said).toContain(setAside);
    expect(said).toContain('"Standard" has started as a local workspace');
    expect(said).toContain('connections from the previous cache as local connections');
    expect(said).toContain('make a new server workspace');
    expect(said).toContain('register the device there again with a one-time token');
    expect(said).not.toMatch(/rename|server URL/i);
    // The note of its own leaves the one on the migration as the live specs count it.
    expect(p.container.querySelectorAll('[data-msg="migrated"]')).toHaveLength(1);
    // That one says only what holds: the migration built "Standard" alone, local, from the
    // defaults (migration.rs plan), and took no settings and no other mode.
    const migrated = p.msg('migrated');
    expect(migrated?.textContent?.trim()).toBe(tNow('workspace.picker.migratedShort'));
    expect(migrated?.textContent).toContain('Each workspace opens in a window of its own');
    expect(migrated?.textContent).not.toMatch(/settings|connections|another mode/i);
    expect(
      [...p.container.querySelectorAll<HTMLElement>('.picker-note')].map((el) => el.dataset.msg),
    ).toEqual(['migrated', 'unreadable-settings']);

    // Rust gives the name in the first listing only (launcher.rs list).
    h.listWorkspaces.mockResolvedValue(listing([{ ...standard, name: 'Standard 2' }], 'standard'));
    await fireEvent.focus(window);
    await p.findByRole('option', { name: /Standard 2/ });
    expect(p.msg('unreadable-settings')?.textContent).toContain(setAside);
    expect(p.msg('migrated')?.textContent?.trim()).toBe(tNow('workspace.picker.migratedShort'));
    cleanup();

    for (const unreadableSettings of [undefined, null]) {
      // The store outlives the picker: empty it, so the mount waits for this listing.
      h.listWorkspaces.mockResolvedValue(listing([]));
      await refresh();
      const again = await mount({ ...listing([standard], 'standard', true), unreadableSettings });
      await waitFor(() =>
        expect(again.msg('migrated')?.textContent?.trim()).toBe(tNow('workspace.picker.migrated')),
      );
      expect(again.msg('unreadable-settings')).toBeNull();
      cleanup();
    }
  });

  it('a list that does not load says why, and Retry lists anew', async () => {
    h.listWorkspaces.mockRejectedValue(new Error('registry unreadable'));
    const view = render(Picker);
    const alert = await view.findByRole('alert');
    expect(alert.textContent).toContain('registry unreadable');

    h.listWorkspaces.mockResolvedValue(listing([info()]));
    await fireEvent.click(within(alert).getByRole('button', { name: tNow('action.retry') }));
    await view.findByRole('option', { name: /Standard/ });
    expect(view.queryByRole('alert')).toBeNull();
  });

  it('lists anew when the launcher gets the focus back: a closed window frees its workspace', async () => {
    const p = await mount(listing([kundeA, info({ open: true })], 'standard'));
    expect(p.openButton().disabled).toBe(true);

    h.listWorkspaces.mockResolvedValue(listing([kundeA, info()], 'standard'));
    await fireEvent.focus(window);
    await waitFor(() => expect(p.openButton().disabled).toBe(false));
    expect(p.msg('is-open')).toBeNull();
  });
});

describe('Picker: an open workspace', () => {
  it('is not opened, edited or deleted, and a hint says why', async () => {
    const p = await mount(listing([info({ open: true }), kundeA], 'standard'));

    expect(p.msg('is-open')?.textContent?.trim()).toBe(
      tNow('workspace.picker.openHint', { name: 'Standard' }),
    );
    expect(p.openButton().disabled).toBe(true);
    expect(p.editButton().disabled).toBe(true);
    expect(p.deleteButton().disabled).toBe(true);
    await p.key('Enter');
    await fireEvent.click(p.openButton());
    expect(h.openWorkspace).not.toHaveBeenCalled();

    // Another one can be made all the same.
    expect(p.newButton().disabled).toBe(false);
    await p.key('ArrowDown');
    expect(p.msg('is-open')).toBeNull();
    expect(p.openButton().disabled).toBe(false);
  });

  it('the open button stays locked while open_workspace runs', async () => {
    let fail: (err: Error) => void = () => {};
    h.openWorkspace.mockReturnValue(new Promise((_resolve, reject) => (fail = reject)));
    const p = await mount(listing([kundeA, sync], 'w-0a1b2c3d'));

    await fireEvent.click(p.openButton());
    const opening = p.getByRole('button', { name: tNow('workspace.picker.opening') });
    expect((opening as HTMLButtonElement).disabled).toBe(true);
    expect(p.deleteButton().disabled).toBe(true);
    expect(p.editButton().disabled).toBe(true);
    expect(p.newButton().disabled).toBe(true);
    // Two calls for the same id both return Ok, and the second process ends on the lock.
    await p.key('Enter');
    await fireEvent.click(opening);
    await p.key('ArrowDown');
    await p.key('Enter');
    expect(h.openWorkspace).toHaveBeenCalledExactlyOnceWith('w-0a1b2c3d');

    fail(new Error('the workspace w-0a1b2c3d did not start'));
    expect((await p.findByRole('alert')).textContent).toContain('did not start');
    expect(p.openButton().disabled).toBe(false);
  });
});

describe('Picker: delete', () => {
  it('asks with the name, and deletes only after a yes', async () => {
    h.deleteWorkspace.mockResolvedValue('revoked');
    const p = await mount(listing([kundeA, sync], 'w-0a1b2c3d'));

    h.confirmDialog.mockResolvedValueOnce(false);
    await fireEvent.click(p.deleteButton());
    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledOnce());
    expect(h.confirmDialog).toHaveBeenCalledWith(
      tNow('workspace.picker.delete.confirm.server', { name: 'Kunde A' }),
      { confirmLabel: tNow('action.delete') },
    );
    expect(h.confirmDialog.mock.calls[0][0]).toContain('Kunde A');
    expect(h.deleteWorkspace).not.toHaveBeenCalled();

    h.listWorkspaces.mockResolvedValue(listing([sync]));
    await fireEvent.click(p.deleteButton());
    await waitFor(() => expect(h.deleteWorkspace).toHaveBeenCalledExactlyOnceWith('w-0a1b2c3d'));
    await waitFor(() =>
      expect(p.msg('deleted')?.textContent).toContain(
        tNow('workspace.picker.deleted', { name: 'Kunde A' }),
      ),
    );
    expect(p.msg('deleted-local-only')).toBeNull();
    await waitFor(() => expect(p.queryByRole('option', { name: /Kunde A/ })).toBeNull());
    expect(p.selected()).toBe(p.option('Sync'));
  });

  it('a local workspace warns of the data lost with it', async () => {
    h.deleteWorkspace.mockResolvedValue('notEnrolled');
    const p = await mount(listing([lokal, sync], 'lokal'));

    await fireEvent.click(p.deleteButton());
    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledOnce());
    const asked = h.confirmDialog.mock.calls[0][0];
    expect(asked).toBe(tNow('workspace.picker.delete.confirm.local', { name: 'Lokal' }));
    expect(asked).toContain('Lokal');
    expect(asked).not.toBe(tNow('workspace.picker.delete.confirm.sync', { name: 'Lokal' }));
  });

  it('after localOnly the hint "on this device only", also when the listing after it fails', async () => {
    h.deleteWorkspace.mockResolvedValue('localOnly');
    const p = await mount(listing([kundeA, sync], 'w-0a1b2c3d'));

    h.listWorkspaces.mockRejectedValue(new Error('registry unreadable'));
    await fireEvent.click(p.deleteButton());

    await waitFor(() =>
      expect(p.msg('deleted-local-only')?.textContent).toBe(
        tNow('workspace.picker.deleted.localOnly'),
      ),
    );
    // The purge drops the fingerprint a later enrollment would name as replaced, so unlike
    // after an identity reset no registration retires the device; an administrator has to.
    const hint = p.msg('deleted-local-only')?.textContent ?? '';
    expect(hint).not.toBe(tNow('settings.resetDeviceId.localOnly'));
    expect(hint).toContain('until an administrator revokes the device');
    expect(hint).toContain('no later registration replaces it');
    expect(p.msg('list-failed')?.textContent).toContain('registry unreadable');
    expect(p.msg('action-failed')).toBeNull();
  });

  it('a delete Rust refuses shows why and keeps the workspace', async () => {
    h.deleteWorkspace.mockRejectedValue(new Error('the workspace w-0a1b2c3d is open'));
    const p = await mount(listing([kundeA], 'w-0a1b2c3d'));

    await fireEvent.click(p.deleteButton());
    expect((await p.findByRole('alert')).textContent).toContain('is open');
    expect(p.msg('deleted')).toBeNull();
    expect(p.option('Kunde A')).not.toBeNull();
    expect(p.deleteButton().disabled).toBe(false);
  });

  it('a focus during a delete lists nothing anew: its purge holds the lock, it would read as open', async () => {
    let done: (outcome: ResetOutcome) => void = () => {};
    h.deleteWorkspace.mockReturnValue(new Promise((resolve) => (done = resolve)));
    const p = await mount(listing([kundeA, sync], 'w-0a1b2c3d'));

    await fireEvent.click(p.deleteButton());
    await waitFor(() => expect(h.deleteWorkspace).toHaveBeenCalledOnce());
    // What Rust lists while the purge runs.
    h.listWorkspaces.mockResolvedValue(listing([{ ...kundeA, open: true }, sync], 'w-0a1b2c3d'));
    const listed = h.listWorkspaces.mock.calls.length;
    await fireEvent.focus(window);
    await new Promise((r) => setTimeout(r, 0));
    expect(h.listWorkspaces).toHaveBeenCalledTimes(listed);
    expect(within(p.option('Kunde A')).queryByText(tNow('workspace.picker.isOpen'))).toBeNull();
    expect(p.msg('is-open')).toBeNull();

    h.listWorkspaces.mockResolvedValue(listing([sync]));
    done('revoked');
    await waitFor(() => expect(p.queryByRole('option', { name: /Kunde A/ })).toBeNull());
    expect(p.msg('deleted')).not.toBeNull();
    expect(p.msg('is-open')).toBeNull();

    // Once the delete has ended, a focus lists anew again.
    h.listWorkspaces.mockResolvedValue(listing([{ ...sync, name: 'Sync 2' }]));
    await fireEvent.focus(window);
    await p.findByRole('option', { name: /Sync 2/ });
  });

  it('a delete Rust refuses lists anew: a focus during it listed nothing', async () => {
    let refuse: (err: Error) => void = () => {};
    h.deleteWorkspace.mockReturnValue(new Promise((_resolve, reject) => (refuse = reject)));
    const p = await mount(listing([kundeA, { ...sync, open: true }], 'w-0a1b2c3d'));

    await fireEvent.click(p.deleteButton());
    await waitFor(() => expect(h.deleteWorkspace).toHaveBeenCalledOnce());
    // The window of Sync closes meanwhile.
    h.listWorkspaces.mockResolvedValue(listing([kundeA, sync], 'w-0a1b2c3d'));
    await fireEvent.focus(window);
    expect(within(p.option('Sync')).queryByText(tNow('workspace.picker.isOpen'))).not.toBeNull();

    refuse(new Error('the workspace w-0a1b2c3d was not deleted'));
    expect((await p.findByRole('alert')).textContent).toContain('was not deleted');
    await waitFor(() =>
      expect(within(p.option('Sync')).queryByText(tNow('workspace.picker.isOpen'))).toBeNull(),
    );
    expect(p.option('Kunde A')).not.toBeNull();
  });
});

describe('Picker: the editor', () => {
  it('New workspace opens an empty editor, Edit the selected closed one', async () => {
    const p = await mount(listing([info(), kundeA], 'w-0a1b2c3d'));

    await fireEvent.click(p.newButton());
    const fresh = p.getByRole('dialog');
    expect(
      within(fresh).getByRole('heading', { name: tNow('workspace.editor.title.new') }),
    ).not.toBeNull();
    expect(
      (within(fresh).getByLabelText(tNow('editor.field.name')) as HTMLInputElement).value,
    ).toBe('');
    await fireEvent.click(within(fresh).getByRole('button', { name: tNow('action.cancel') }));
    expect(p.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(p.list());

    await fireEvent.click(p.editButton());
    const editor = p.getByRole('dialog');
    expect(
      within(editor).getByRole('heading', { name: tNow('workspace.editor.title.edit') }),
    ).not.toBeNull();
    expect(
      (within(editor).getByLabelText(tNow('editor.field.name')) as HTMLInputElement).value,
    ).toBe('Kunde A');
  });

  it('a save that went through closes the editor even when the listing after it fails', async () => {
    h.saveWorkspace.mockResolvedValue('w-0a1b2c3d');
    const p = await mount(listing([kundeA], 'w-0a1b2c3d'));

    await fireEvent.click(p.editButton());
    const editor = p.getByRole('dialog');
    h.listWorkspaces.mockRejectedValue(new Error('registry unreadable'));
    await fireEvent.input(within(editor).getByLabelText(tNow('editor.field.name')), {
      target: { value: 'Kunde B' },
    });
    await fireEvent.click(within(editor).getByRole('button', { name: tNow('action.save') }));

    await waitFor(() => expect(p.queryByRole('dialog')).toBeNull());
    expect(h.saveWorkspace).toHaveBeenCalledOnce();
    expect(h.saveWorkspace).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'w-0a1b2c3d', name: 'Kunde B' }),
    );
    expect(p.msg('list-failed')?.textContent).toContain('registry unreadable');
  });
});

describe('Picker: the hooks of the live specs', () => {
  it('each action has a data-action of its own, on its button', async () => {
    const p = await mount(listing([kundeA], 'w-0a1b2c3d'));
    const hook = (action: string) => {
      const found = p.container.querySelectorAll(`[data-action="${action}"]`);
      expect(found).toHaveLength(1);
      return found[0];
    };

    expect(hook('workspace-new')).toBe(p.newButton());
    expect(hook('workspace-edit')).toBe(p.editButton());
    expect(hook('workspace-delete')).toBe(p.deleteButton());
    expect(hook('workspace-open')).toBe(p.openButton());
  });
});

describe('App in the launcher', () => {
  it('shows the picker, not the login or a workspace', async () => {
    h.workspaceContext.mockResolvedValue({ launcher: true, workspace: null });
    await loadContext();
    h.listWorkspaces.mockResolvedValue(listing([info()], 'standard'));

    const view = render(App);
    await view.findByRole('option', { name: /Standard/ });
    expect(view.getByRole('heading', { name: tNow('workspace.picker.title') })).not.toBeNull();
  });

  it('a workspace window shows no picker and lists nothing', async () => {
    h.workspaceContext.mockResolvedValue({ launcher: false, workspace: info() });
    await loadContext();
    h.listWorkspaces.mockClear();

    const view = render(App);
    await Promise.resolve();
    expect(view.queryByRole('listbox')).toBeNull();
    expect(view.queryByRole('heading', { name: tNow('workspace.picker.title') })).toBeNull();
    expect(h.listWorkspaces).not.toHaveBeenCalled();
  });
});
