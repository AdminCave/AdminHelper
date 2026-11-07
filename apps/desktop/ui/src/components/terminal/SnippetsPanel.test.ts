// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The snippet panel (R-1071): the default list in the language of the app until the workspace
// has one of its own, a click runs a snippet in a running session only, new, edit and delete save
// the whole list (delete after a question), a failed save keeps the form, names show as text, and
// the broadcast checkbox is the store of the session list.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get, writable } from 'svelte/store';
import type { Settings, Snippet } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { getSettingsDefaults } from '$lib/models/settings';

const h = vi.hoisted(() => ({
  runSnippet: vi.fn(async (_key: string, _command: string) => {}),
  setSnippets: vi.fn<(list: unknown[]) => Promise<void>>(async () => {}),
  reportError: vi.fn(),
  confirm: vi.fn(async (_message: string, _opts?: unknown) => true),
}));

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { settings: writable(null), setSnippets: h.setSnippets };
});
vi.mock('$lib/stores/terminals', async () => {
  const { writable } = await import('svelte/store');
  const snippetBroadcast = writable(false);
  return {
    runSnippet: h.runSnippet,
    snippetBroadcast,
    // As Rust: the store follows the switch.
    setSnippetBroadcast: vi.fn(async (on: boolean) => snippetBroadcast.set(on)),
  };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: h.reportError }));
vi.mock('../ui/ConfirmDialog.svelte', () => ({ confirmDialog: h.confirm }));

import { settings } from '$lib/stores/session';
import { setSnippetBroadcast, snippetBroadcast as broadcastStore } from '$lib/stores/terminals';
import SnippetsPanel from './SnippetsPanel.svelte';

const settingsStore = settings as unknown as ReturnType<typeof writable<Settings | null>>;
const snippetBroadcast = broadcastStore as unknown as ReturnType<typeof writable<boolean>>;
const KEY = 'terminal-1';
const DISK = { name: 'Disk', command: 'df -h' };
const LOGS = { name: 'Logs', command: 'cd /var/log\nls -la' };

function withSnippets(snippets: Snippet[] | null): void {
  settingsStore.set({ ...getSettingsDefaults(), snippets });
}

function mount(running = true) {
  const onRun = vi.fn();
  const view = render(SnippetsPanel, { sessionKey: KEY, running, onRun });
  return { ...view, onRun };
}

const card = (command: string) =>
  screen.getByText(`$ ${command}`).closest('button') as HTMLButtonElement;
const button = (name: string) => screen.getByRole('button', { name });

async function fill(name: string, command: string): Promise<void> {
  await fireEvent.input(screen.getByLabelText(tNow('terminal.snippets.name')), {
    target: { value: name },
  });
  await fireEvent.input(screen.getByLabelText(tNow('terminal.snippets.command')), {
    target: { value: command },
  });
}

beforeAll(() => setLanguage('en'));

beforeEach(() => {
  vi.clearAllMocks();
  // As session.ts: the store holds what was saved.
  h.setSnippets.mockImplementation(async (list) => withSnippets(list as Snippet[]));
  h.confirm.mockResolvedValue(true);
  snippetBroadcast.set(false);
  withSnippets(null);
});

afterEach(() => cleanup());

describe('SnippetsPanel', () => {
  it('shows the default list in the language of the app until the workspace has its own', async () => {
    mount();
    expect(screen.getByText('Check disk')).toBeTruthy();
    expect(screen.getByText('$ systemctl --failed')).toBeTruthy();
    expect(screen.getAllByRole('listitem')).toHaveLength(7);

    setLanguage('de');
    await tick();
    expect(screen.getByText('Speicher prüfen')).toBeTruthy();
    setLanguage('en');
    await tick();

    withSnippets([DISK]);
    await tick();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.queryByText('Check disk')).toBeNull();
  });

  it('keeps an empty list empty', () => {
    withSnippets([]);
    mount();
    expect(screen.queryByRole('listitem')).toBeNull();
    expect(screen.getByText(tNow('terminal.snippets.empty'))).toBeTruthy();
  });

  it('runs a snippet in its session and hands the keys back', async () => {
    withSnippets([DISK, LOGS]);
    const { onRun } = mount();
    await fireEvent.click(card('df -h'));
    expect(h.runSnippet).toHaveBeenCalledWith(KEY, 'df -h');
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it('runs nothing in a session that does not run', async () => {
    withSnippets([DISK]);
    const { onRun } = mount(false);
    expect(card('df -h').disabled).toBe(true);
    await fireEvent.click(card('df -h'));
    expect(h.runSnippet).not.toHaveBeenCalled();
    expect(onRun).not.toHaveBeenCalled();
  });

  it('adds a snippet to the default list and saves the whole list', async () => {
    mount();
    await fireEvent.click(button(tNow('terminal.snippets.new')));
    const save = button(tNow('action.save')) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await fill('  ', 'uptime');
    expect(save.disabled).toBe(true);

    await fill('  Load  ', 'uptime\n\n');
    await fireEvent.click(save);
    await vi.waitFor(() => expect(h.setSnippets).toHaveBeenCalledTimes(1));
    const list = h.setSnippets.mock.calls[0][0] as Snippet[];
    expect(list).toHaveLength(8);
    expect(list[0]).toEqual({ name: 'Check disk', command: 'df -h' });
    expect(list[7]).toEqual({ name: 'Load', command: 'uptime' });
    await tick();
    expect(screen.queryByRole('button', { name: tNow('action.save') })).toBeNull();
    expect(screen.getByText('$ uptime', { selector: 'li:last-child code' })).toBeTruthy();
  });

  it('edits a snippet in its place', async () => {
    withSnippets([DISK, LOGS]);
    mount();
    await fireEvent.click(button(tNow('terminal.snippets.edit', { name: 'Logs' })));
    expect(
      (screen.getByLabelText(tNow('terminal.snippets.command')) as HTMLTextAreaElement).value,
    ).toBe(LOGS.command);
    await fill('Logs', 'journalctl -n 50');
    await fireEvent.click(button(tNow('action.save')));
    await vi.waitFor(() =>
      expect(h.setSnippets).toHaveBeenCalledWith([
        DISK,
        { name: 'Logs', command: 'journalctl -n 50' },
      ]),
    );
  });

  it('edits the snippet where it is now, after another tab changed the list', async () => {
    withSnippets([DISK, LOGS]);
    mount();
    await fireEvent.click(button(tNow('terminal.snippets.edit', { name: 'Logs' })));
    await fill('Logs', 'journalctl -n 50');
    // Meanwhile another tab put one in front.
    const other = { name: 'Other', command: 'id' };
    withSnippets([other, DISK, LOGS]);
    await tick();
    await fireEvent.click(button(tNow('action.save')));
    await vi.waitFor(() =>
      expect(h.setSnippets).toHaveBeenCalledWith([
        other,
        DISK,
        { name: 'Logs', command: 'journalctl -n 50' },
      ]),
    );
  });

  it('keeps an edit whose snippet another tab deleted, at the end', async () => {
    withSnippets([DISK, LOGS]);
    mount();
    await fireEvent.click(button(tNow('terminal.snippets.edit', { name: 'Disk' })));
    await fill('Disk', 'df -h /');
    withSnippets([LOGS]);
    await tick();
    await fireEvent.click(button(tNow('action.save')));
    await vi.waitFor(() =>
      expect(h.setSnippets).toHaveBeenCalledWith([LOGS, { name: 'Disk', command: 'df -h /' }]),
    );
  });

  it('cancels an edit without saving', async () => {
    withSnippets([DISK]);
    mount();
    await fireEvent.click(button(tNow('terminal.snippets.edit', { name: 'Disk' })));
    await fill('Other', 'ls');
    await fireEvent.click(button(tNow('action.cancel')));
    expect(screen.queryByLabelText(tNow('terminal.snippets.name'))).toBeNull();
    expect(h.setSnippets).not.toHaveBeenCalled();
  });

  it('deletes a snippet only after the question', async () => {
    withSnippets([DISK, LOGS]);
    mount();
    h.confirm.mockResolvedValueOnce(false);
    await fireEvent.click(button(tNow('terminal.snippets.delete', { name: 'Disk' })));
    await vi.waitFor(() => expect(h.confirm).toHaveBeenCalledTimes(1));
    expect(h.confirm.mock.calls[0][0]).toBe(
      tNow('terminal.snippets.confirmDelete', { name: 'Disk' }),
    );
    expect(h.setSnippets).not.toHaveBeenCalled();

    await fireEvent.click(button(tNow('terminal.snippets.delete', { name: 'Disk' })));
    await vi.waitFor(() => expect(h.setSnippets).toHaveBeenCalledWith([LOGS]));
  });

  it('deletes from the list as it is after the question', async () => {
    withSnippets([DISK, LOGS]);
    mount();
    let answer!: (ok: boolean) => void;
    h.confirm.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    await fireEvent.click(button(tNow('terminal.snippets.delete', { name: 'Logs' })));
    // Meanwhile another tab saved a list.
    const other = { name: 'Other', command: 'id' };
    withSnippets([other, DISK, LOGS]);
    answer(true);
    await vi.waitFor(() => expect(h.setSnippets).toHaveBeenCalledWith([other, DISK]));
  });

  it('keeps the form and reports when saving fails', async () => {
    withSnippets([DISK]);
    mount();
    h.setSnippets.mockRejectedValueOnce('a snippet name must not be empty');
    await fireEvent.click(button(tNow('terminal.snippets.new')));
    await fill('Load', 'uptime');
    await fireEvent.click(button(tNow('action.save')));
    await vi.waitFor(() =>
      expect(h.reportError).toHaveBeenCalledWith('a snippet name must not be empty'),
    );
    expect(screen.getByLabelText(tNow('terminal.snippets.name'))).toBeTruthy();
    expect(get(settingsStore)?.snippets).toEqual([DISK]);
  });

  it('shows names and commands as text', () => {
    withSnippets([{ name: '<b>bold</b>', command: '<img src=x onerror=alert(1)>' }]);
    const { container } = mount();
    expect(screen.getByText('<b>bold</b>')).toBeTruthy();
    expect(container.querySelector('b, img')).toBeNull();
  });

  it('switches the broadcast through Rust, unsaved', async () => {
    mount();
    const box = screen.getByRole('checkbox');
    expect(screen.getByText(tNow('terminal.snippets.broadcastHint'))).toBeTruthy();
    await fireEvent.click(box);
    expect(setSnippetBroadcast).toHaveBeenLastCalledWith(true);
    expect(get(snippetBroadcast)).toBe(true);
    await fireEvent.click(box);
    expect(setSnippetBroadcast).toHaveBeenLastCalledWith(false);
    expect(get(snippetBroadcast)).toBe(false);
    expect(h.setSnippets).not.toHaveBeenCalled();
  });

  it('shows the broadcast as the store has it', async () => {
    snippetBroadcast.set(true);
    mount();
    const box = screen.getByRole('checkbox') as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(
      within(box.closest('label') as HTMLElement).getByText(tNow('terminal.snippets.broadcast')),
    ).toBeTruthy();
  });
});
