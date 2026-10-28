// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// "Delete" in the connection editor asks first (R-0661): it removes the connection, in server
// mode on the server, and a stored RDP password. The question sits in App's layer, outside the
// editor's overlay, while the focus stays on "Delete" in it: an Escape there must not close the
// editor under the question. confirmDialog is mocked here; the dialog itself is tested in
// ui/primitives.test.ts.

import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import { setLanguage, tNow } from '$lib/i18n';
import type { Connection } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  remove: vi.fn(async (_id: string) => undefined),
  deletePassword: vi.fn(async (_connection: Connection) => undefined),
  confirmDialog: vi.fn(
    async (_message: string, _opts?: { confirmLabel?: string }): Promise<boolean> => true,
  ),
}));

vi.mock('$lib/bridge', () => ({ deletePassword: h.deletePassword }));
vi.mock('$lib/stores/connections', () => ({ upsert: vi.fn(), remove: h.remove }));
vi.mock('$lib/stores/connectFlow', () => ({ initiateConnect: vi.fn() }));
vi.mock('./ui/ConfirmDialog.svelte', () => ({ confirmDialog: h.confirmDialog }));

import { emptyConnection } from '$lib/models/connection';
import { editorState, openEditor, closeEditor } from '$lib/stores/editor';
import ConnectionEditor from './ConnectionEditor.svelte';

const RDP: Connection = {
  ...emptyConnection('rdp'),
  id: 'conn-rdp-1',
  name: 'web01',
  host: 'web01.example',
};

beforeAll(() => {
  setLanguage('en');
});

afterEach(() => {
  cleanup();
  closeEditor();
  vi.clearAllMocks();
});

async function openOn(connection: Connection): Promise<HTMLElement> {
  openEditor(connection);
  const { container } = render(ConnectionEditor);
  await tick();
  return container;
}

function deleteButton(container: HTMLElement): HTMLButtonElement {
  const found = [...container.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === tNow('action.delete'),
  );
  expect(found).toBeDefined();
  return found!;
}

function editorOpen(container: HTMLElement): boolean {
  return get(editorState).open && container.querySelector('.editor-overlay') !== null;
}

describe('ConnectionEditor delete (R-0661)', () => {
  it('deletes nothing and stays open when the question is declined', async () => {
    h.confirmDialog.mockResolvedValueOnce(false);
    const container = await openOn(RDP);

    await fireEvent.click(deleteButton(container));
    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(1));
    await tick();

    expect(h.remove).not.toHaveBeenCalled();
    expect(h.deletePassword).not.toHaveBeenCalled();
    expect(editorOpen(container)).toBe(true);
  });

  it('deletes the RDP connection and its stored password once confirmed, then closes', async () => {
    h.confirmDialog.mockResolvedValueOnce(true);
    const container = await openOn(RDP);

    await fireEvent.click(deleteButton(container));

    await waitFor(() => expect(get(editorState).open).toBe(false));
    expect(h.remove).toHaveBeenCalledTimes(1);
    expect(h.remove).toHaveBeenCalledWith(RDP.id);
    expect(h.deletePassword).toHaveBeenCalledTimes(1);
    expect(h.deletePassword).toHaveBeenCalledWith(RDP);
    await waitFor(() => expect(container.querySelector('.editor-overlay')).toBeNull());
  });

  it('names the connection in the question and labels its button "Delete"', async () => {
    h.confirmDialog.mockResolvedValueOnce(false);
    const container = await openOn(RDP);

    await fireEvent.click(deleteButton(container));

    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(1));
    const [message, opts] = h.confirmDialog.mock.calls[0];
    expect(message).toBe(tNow('editor.deleteConfirm', { name: 'web01' }));
    expect(message).toContain('"web01"');
    expect(opts).toEqual({ confirmLabel: tNow('action.delete') });
  });

  it('names the host when the connection has no name', async () => {
    h.confirmDialog.mockResolvedValueOnce(false);
    const container = await openOn({ ...emptyConnection('ssh'), host: 'db01.example' });

    await fireEvent.click(deleteButton(container));

    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(1));
    expect(h.confirmDialog.mock.calls[0][0]).toBe(
      tNow('editor.deleteConfirm', { name: 'db01.example' }),
    );
  });

  it('keeps the editor open on Escape while the question is open', async () => {
    let answer: (ok: boolean) => void = () => {};
    h.confirmDialog.mockImplementationOnce(
      () =>
        new Promise<boolean>((resolve) => {
          answer = resolve;
        }),
    );
    const container = await openOn(RDP);

    await fireEvent.click(deleteButton(container));
    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(1));

    // Where the focus stays after the click: "Delete" inside the overlay.
    await fireEvent.keyDown(deleteButton(container), { key: 'Escape' });
    expect(editorOpen(container)).toBe(true);

    answer(false);
    await tick();
    expect(h.remove).not.toHaveBeenCalled();
    expect(h.deletePassword).not.toHaveBeenCalled();
    expect(editorOpen(container)).toBe(true);

    // The question is settled: the next Escape is the editor's own again.
    await fireEvent.keyDown(deleteButton(container), { key: 'Escape' });
    expect(get(editorState).open).toBe(false);
  });

  it('a second Delete replaces the question, and Escape still keeps the editor open', async () => {
    // As the real dialog: a new question settles the open one as cancelled.
    let answer: ((ok: boolean) => void) | null = null;
    const ask = (): Promise<boolean> =>
      new Promise<boolean>((resolve) => {
        answer?.(false);
        answer = resolve;
      });
    h.confirmDialog.mockImplementationOnce(ask).mockImplementationOnce(ask);
    const container = await openOn(RDP);

    // The focus is still on "Delete": Enter clicks it again under the question.
    await fireEvent.click(deleteButton(container));
    await fireEvent.click(deleteButton(container));
    await waitFor(() => expect(h.confirmDialog).toHaveBeenCalledTimes(2));
    await tick();

    await fireEvent.keyDown(deleteButton(container), { key: 'Escape' });
    expect(editorOpen(container)).toBe(true);

    answer!(false);
    await tick();
    expect(h.remove).not.toHaveBeenCalled();
    await fireEvent.keyDown(deleteButton(container), { key: 'Escape' });
    expect(get(editorState).open).toBe(false);
  });
});
