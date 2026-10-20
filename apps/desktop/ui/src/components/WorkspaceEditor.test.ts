// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The workspace editor (R-0431) makes a workspace or edits a closed one. Rust checks the
// draft again (launcher.rs save); here the form: the name that follows the host, the URL
// rules of validateDraft, the warning on another URL, and the URL of WorkspaceInfo sent back
// as it came, so Rust keeps the stored one with what the webview never saw.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { fromStore, writable } from 'svelte/store';
import type { WorkspaceDraft, WorkspaceInfo } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { WORKSPACE_NAME_MAX, WORKSPACE_PALETTE } from '$lib/models/workspace';
import WorkspaceEditor from './WorkspaceEditor.svelte';

const h = vi.hoisted(() => ({
  save: vi.fn<(draft: WorkspaceDraft) => Promise<string>>(),
}));

vi.mock('$lib/stores/workspace', () => ({ save: h.save }));

const info = (over: Partial<WorkspaceInfo> = {}): WorkspaceInfo => ({
  id: 'w-0a1b2c3d',
  name: 'Kunde A',
  color: WORKSPACE_PALETTE[2],
  kind: 'server',
  url: 'https://ah.example.com',
  host: 'ah.example.com',
  open: false,
  ...over,
});

async function mount(workspace: WorkspaceInfo | null = null) {
  const onClose = vi.fn();
  // Each prop on a signal of its own, as a parent passes them: testing-library's rerender
  // swaps all props at once, and each of them then reads as changed.
  const open = writable(true);
  const shown = writable(workspace);
  const openNow = fromStore(open);
  const shownNow = fromStore(shown);
  const view = render(WorkspaceEditor, {
    props: {
      onClose,
      get open() {
        return openNow.current;
      },
      get workspace() {
        return shownNow.current;
      },
    },
  });
  await tick();
  const field = (label: string) => view.getByLabelText(label) as HTMLInputElement;
  return {
    ...view,
    onClose,
    setOpen: async (next: boolean) => {
      open.set(next);
      await tick();
    },
    setWorkspace: async (next: WorkspaceInfo | null) => {
      shown.set(next);
      await tick();
    },
    serverUrl: () => field(tNow('settings.serverUrl')),
    syncUrl: () => field(tNow('settings.syncUrl')),
    name: () => field(tNow('editor.field.name')),
    kind: () => view.getByLabelText(tNow('workspace.editor.kind')) as HTMLSelectElement,
    saveButton: () => view.getByRole('button', { name: tNow('action.save') }) as HTMLButtonElement,
    warning: () => view.queryByText(tNow('workspace.editor.urlChanged')),
    maskedHint: () => view.queryByText(tNow('workspace.editor.maskedValues')),
  };
}

const type = (input: HTMLInputElement, value: string) =>
  fireEvent.input(input, { target: { value } });

beforeAll(() => {
  setLanguage('en');
});

beforeEach(() => {
  h.save.mockReset();
  h.save.mockResolvedValue('w-0a1b2c3d');
});

afterEach(() => {
  cleanup();
});

describe('WorkspaceEditor: a new workspace', () => {
  it('the name follows the host until the user types one', async () => {
    const ed = await mount();
    expect(ed.name().value).toBe('');

    await type(ed.serverUrl(), 'https://ah.example.com/app');
    expect(ed.name().value).toBe('ah.example.com');
    await type(ed.serverUrl(), 'https://kunde-b.example.com');
    expect(ed.name().value).toBe('kunde-b.example.com');

    await type(ed.name(), 'Kunde B');
    await type(ed.serverUrl(), 'https://kunde-c.example.com');
    expect(ed.name().value).toBe('Kunde B');
  });

  it('a sync workspace is named after its host too', async () => {
    const ed = await mount();
    await fireEvent.change(ed.kind(), { target: { value: 'sync' } });
    await type(ed.syncUrl(), 'https://sync.example.com/connections.json');
    expect(ed.name().value).toBe('sync.example.com');
  });

  it('a long host is cut to the name limit, so it does not block saving', async () => {
    const host = `${'a'.repeat(50)}.example.com`;
    const ed = await mount();
    await type(ed.serverUrl(), `https://${host}`);

    expect(ed.name().value).toBe(host.slice(0, WORKSPACE_NAME_MAX));
    expect(ed.saveButton().disabled).toBe(false);
    await fireEvent.click(ed.saveButton());
    expect(h.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: host.slice(0, WORKSPACE_NAME_MAX) }),
    );
  });

  it('an invalid URL blocks saving and says why', async () => {
    const ed = await mount();
    // Without a URL a server workspace cannot be made.
    expect(ed.saveButton().disabled).toBe(true);

    await type(ed.serverUrl(), 'http://ah.example.com');
    expect(ed.name().value).toBe('ah.example.com');
    expect(ed.saveButton().disabled).toBe(true);
    expect(ed.getByText(tNow('validation.serverUrl.https'))).not.toBeNull();
    await fireEvent.click(ed.saveButton());
    expect(h.save).not.toHaveBeenCalled();

    await fireEvent.change(ed.kind(), { target: { value: 'sync' } });
    await type(ed.syncUrl(), 'http://sync.example.com/connections.json');
    expect(ed.saveButton().disabled).toBe(true);
    expect(ed.getByText(tNow('validation.syncUrl.https'))).not.toBeNull();

    await type(ed.syncUrl(), 'https://sync.example.com/connections.json');
    expect(ed.saveButton().disabled).toBe(false);
    expect(ed.queryByText(tNow('validation.syncUrl.https'))).toBeNull();
  });

  it('saving hands the draft to the store, without an id, and closes', async () => {
    const ed = await mount();
    await type(ed.serverUrl(), '  https://ah.example.com  ');
    await fireEvent.click(ed.getByRole('radio', { name: WORKSPACE_PALETTE[4] }));
    expect(ed.getByRole('radio', { name: WORKSPACE_PALETTE[4] }).getAttribute('aria-checked')).toBe(
      'true',
    );
    await fireEvent.click(ed.saveButton());

    expect(h.save).toHaveBeenCalledOnce();
    const draft = h.save.mock.calls[0][0];
    expect(draft).toEqual({
      kind: 'server',
      name: 'ah.example.com',
      color: WORKSPACE_PALETTE[4],
      url: 'https://ah.example.com',
    });
    expect(draft).not.toHaveProperty('id');
    await vi.waitFor(() => expect(ed.onClose).toHaveBeenCalledOnce());
    // Nothing to warn about: there is no previous installation.
    expect(ed.warning()).toBeNull();
  });

  it('switching to local drops a typed URL (Rust refuses a local one with a URL)', async () => {
    const ed = await mount();
    await type(ed.serverUrl(), 'https://ah.example.com');

    await fireEvent.change(ed.kind(), { target: { value: 'local' } });
    expect(ed.queryByLabelText(tNow('settings.serverUrl'))).toBeNull();
    // The name followed the host, which is gone with the URL.
    expect(ed.name().value).toBe('');
    await type(ed.name(), 'Lokal 2');
    await fireEvent.click(ed.saveButton());
    expect(h.save).toHaveBeenCalledWith({
      kind: 'local',
      name: 'Lokal 2',
      color: WORKSPACE_PALETTE[0],
      url: null,
    });

    await fireEvent.change(ed.kind(), { target: { value: 'server' } });
    expect(ed.serverUrl().value).toBe('');
  });
});

describe('WorkspaceEditor: editing a closed workspace', () => {
  it('a failed save shows the error and keeps the editor open', async () => {
    const refused = 'the workspace w-0a1b2c3d is open; close it to edit it';
    h.save.mockRejectedValue(new Error(refused));
    const ed = await mount(info());
    await type(ed.name(), 'Kunde B');
    await fireEvent.click(ed.saveButton());

    expect((await ed.findByRole('alert')).textContent).toContain(refused);
    expect(ed.onClose).not.toHaveBeenCalled();
    expect(ed.saveButton().disabled).toBe(false);
  });

  it('shows what the workspace has and keeps its kind', async () => {
    const ed = await mount(info());
    expect(ed.getByText(tNow('workspace.editor.title.edit'))).not.toBeNull();
    expect(ed.kind().value).toBe('server');
    expect(ed.kind().disabled).toBe(true);
    expect(ed.serverUrl().value).toBe('https://ah.example.com');
    expect(ed.name().value).toBe('Kunde A');
    expect(ed.getByRole('radio', { name: WORKSPACE_PALETTE[2] }).getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(ed.warning()).toBeNull();
  });

  it('an unchanged URL goes back as WorkspaceInfo gave it, masked values included', async () => {
    const url = 'https://sync.example.com/c.json?token=***#***';
    const ed = await mount(info({ kind: 'sync', url, host: 'sync.example.com' }));
    expect(ed.syncUrl().value).toBe(url);

    await type(ed.name(), 'Kunde Z');
    await fireEvent.click(ed.getByRole('radio', { name: WORKSPACE_PALETTE[6] }));
    expect(ed.warning()).toBeNull();
    expect(ed.maskedHint()).toBeNull();
    await fireEvent.click(ed.saveButton());

    expect(h.save).toHaveBeenCalledWith({
      id: 'w-0a1b2c3d',
      kind: 'sync',
      name: 'Kunde Z',
      color: WORKSPACE_PALETTE[6],
      url,
    });
  });

  it('a changed URL shows the warning, the old URL again hides it', async () => {
    const ed = await mount(info());

    await type(ed.serverUrl(), 'https://other.example.com');
    expect(ed.warning()).not.toBeNull();
    // The name of a workspace does not follow its host.
    expect(ed.name().value).toBe('Kunde A');

    await type(ed.serverUrl(), ' https://ah.example.com ');
    expect(ed.warning()).toBeNull();

    await type(ed.serverUrl(), 'https://other.example.com');
    await fireEvent.click(ed.saveButton());
    expect(h.save).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'w-0a1b2c3d', url: 'https://other.example.com' }),
    );
  });

  it('a workspace that has a URL keeps needing one', async () => {
    const ed = await mount(info());
    await type(ed.serverUrl(), '');
    expect(ed.warning()).not.toBeNull();
    expect(ed.getByText(tNow('validation.serverUrl.required'))).not.toBeNull();
    expect(ed.saveButton().disabled).toBe(true);
  });

  it('changing a URL with masked values says to enter them again', async () => {
    const ed = await mount(
      info({
        kind: 'sync',
        url: 'https://sync.example.com/c.json?token=***',
        host: 'sync.example.com',
      }),
    );
    expect(ed.maskedHint()).toBeNull();

    await type(ed.syncUrl(), 'https://sync.example.com/d.json?token=***');
    expect(ed.maskedHint()).not.toBeNull();
    expect(ed.warning()).not.toBeNull();
    // A hint, not a block: the URL is saved as it stands, `***` included.
    expect(ed.saveButton().disabled).toBe(false);

    // Entered anew, nothing masked is left to save.
    await type(ed.syncUrl(), 'https://sync.example.com/d.json?token=abc');
    expect(ed.maskedHint()).toBeNull();
    expect(ed.warning()).not.toBeNull();
    await fireEvent.click(ed.saveButton());
    expect(h.save).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'https://sync.example.com/d.json?token=abc' }),
    );
  });

  it('a migrated server workspace without a URL is renamed without one', async () => {
    const ed = await mount(info({ id: 'standard', name: 'Standard', url: null, host: null }));
    expect(ed.serverUrl().value).toBe('');
    expect(ed.saveButton().disabled).toBe(false);

    await type(ed.name(), 'Kunde A');
    expect(ed.warning()).toBeNull();
    await fireEvent.click(ed.saveButton());
    expect(h.save).toHaveBeenCalledWith({
      id: 'standard',
      kind: 'server',
      name: 'Kunde A',
      color: WORKSPACE_PALETTE[2],
      url: null,
    });

    // A URL typed there is checked all the same.
    await type(ed.serverUrl(), 'http://ah.example.com');
    expect(ed.saveButton().disabled).toBe(true);
    expect(ed.getByText(tNow('validation.serverUrl.https'))).not.toBeNull();
  });

  it('opening seeds the form anew, a new prop while open leaves the typing alone', async () => {
    const ed = await mount(info());
    await type(ed.name(), 'Kunde Neu');

    // The picker lists anew while the editor is open: a fresh object, the same workspace.
    await ed.setWorkspace(info());
    expect(ed.name().value).toBe('Kunde Neu');

    await ed.setOpen(false);
    await ed.setWorkspace(info({ name: 'Kunde B' }));
    await ed.setOpen(true);
    expect(ed.name().value).toBe('Kunde B');

    await ed.setOpen(false);
    await ed.setWorkspace(null);
    await ed.setOpen(true);
    expect(ed.getByText(tNow('workspace.editor.title.new'))).not.toBeNull();
    expect(ed.name().value).toBe('');
    expect(ed.kind().disabled).toBe(false);
  });
});
