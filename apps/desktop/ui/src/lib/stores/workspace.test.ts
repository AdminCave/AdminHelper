// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { WorkspaceDraft, WorkspaceInfo, WorkspaceList } from '$lib/bridge/types';

vi.mock('$lib/bridge', () => ({
  workspaceContext: vi.fn(),
  listWorkspaces: vi.fn(),
  saveWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  openWorkspace: vi.fn(),
  openLauncher: vi.fn(),
}));

import * as bridge from '$lib/bridge';
import { context, list, loadContext, refresh, save, remove, open, openLauncher } from './workspace';

const info = (over: Partial<WorkspaceInfo> = {}): WorkspaceInfo => ({
  id: 'standard',
  name: 'Standard',
  color: '#3b82f6',
  kind: 'server',
  host: 'ah.example.com',
  open: false,
  ...over,
});

const listing = (workspaces: WorkspaceInfo[], lastUsed: string | null = null): WorkspaceList => ({
  workspaces,
  lastUsed,
  migratedNotice: false,
});

describe('workspace store', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  describe('loadContext', () => {
    it('holds the launcher context', async () => {
      vi.mocked(bridge.workspaceContext).mockResolvedValue({ launcher: true, workspace: null });
      await loadContext();
      expect(get(context)).toEqual({ launcher: true, workspace: null });
    });

    it('holds the workspace this window serves', async () => {
      const ws = info({ id: 'w-0a1b2c3d', name: 'Kunde A' });
      vi.mocked(bridge.workspaceContext).mockResolvedValue({ launcher: false, workspace: ws });
      await loadContext();
      expect(get(context)?.workspace).toEqual(ws);
    });

    it('rejects when Rust does, so hydrate can tell', async () => {
      vi.mocked(bridge.workspaceContext).mockRejectedValue(new Error('no data dir'));
      await expect(loadContext()).rejects.toThrow('no data dir');
    });
  });

  describe('refresh', () => {
    it('holds the list Rust gives', async () => {
      const given: WorkspaceList = { ...listing([info()], 'standard'), migratedNotice: true };
      vi.mocked(bridge.listWorkspaces).mockResolvedValue(given);
      await refresh();
      expect(get(list)).toEqual(given);
    });
  });

  describe('save', () => {
    const draft: WorkspaceDraft = {
      kind: 'server',
      name: 'Kunde B',
      color: '#22c55e',
      url: 'https://b.example.com',
    };

    it('hands the draft to Rust, then lists anew, and resolves to the id', async () => {
      const added = info({ id: 'w-0a1b2c3d', name: 'Kunde B', host: 'b.example.com' });
      vi.mocked(bridge.saveWorkspace).mockResolvedValue('w-0a1b2c3d');
      vi.mocked(bridge.listWorkspaces).mockResolvedValue(listing([info(), added]));

      await expect(save(draft)).resolves.toBe('w-0a1b2c3d');

      expect(bridge.saveWorkspace).toHaveBeenCalledWith(draft);
      expect(vi.mocked(bridge.saveWorkspace).mock.invocationCallOrder[0]).toBeLessThan(
        vi.mocked(bridge.listWorkspaces).mock.invocationCallOrder[0],
      );
      expect(get(list)?.workspaces).toEqual([info(), added]);
    });

    it('a rejected save keeps the list and does not list anew', async () => {
      vi.mocked(bridge.listWorkspaces).mockResolvedValue(listing([info()]));
      await refresh();
      vi.mocked(bridge.listWorkspaces).mockClear();
      vi.mocked(bridge.saveWorkspace).mockRejectedValue(new Error('the workspace is open'));

      await expect(save(draft)).rejects.toThrow('the workspace is open');

      expect(bridge.listWorkspaces).not.toHaveBeenCalled();
      expect(get(list)?.workspaces).toEqual([info()]);
    });
  });

  describe('remove', () => {
    it('deletes in Rust, lists anew and resolves to how the revoke went', async () => {
      vi.mocked(bridge.deleteWorkspace).mockResolvedValue('localOnly');
      vi.mocked(bridge.listWorkspaces).mockResolvedValue(listing([]));

      await expect(remove('standard')).resolves.toBe('localOnly');

      expect(bridge.deleteWorkspace).toHaveBeenCalledWith('standard');
      expect(vi.mocked(bridge.deleteWorkspace).mock.invocationCallOrder[0]).toBeLessThan(
        vi.mocked(bridge.listWorkspaces).mock.invocationCallOrder[0],
      );
      expect(get(list)?.workspaces).toEqual([]);
    });

    it('a rejected delete keeps the list and does not list anew', async () => {
      vi.mocked(bridge.listWorkspaces).mockResolvedValue(listing([info()]));
      await refresh();
      vi.mocked(bridge.listWorkspaces).mockClear();
      vi.mocked(bridge.deleteWorkspace).mockRejectedValue(new Error('the workspace is open'));

      await expect(remove('standard')).rejects.toThrow('the workspace is open');

      expect(bridge.listWorkspaces).not.toHaveBeenCalled();
      expect(get(list)?.workspaces).toEqual([info()]);
    });
  });

  describe('open and openLauncher', () => {
    it('open starts the workspace of the id', async () => {
      vi.mocked(bridge.openWorkspace).mockResolvedValue(undefined);
      await open('w-0a1b2c3d');
      expect(bridge.openWorkspace).toHaveBeenCalledWith('w-0a1b2c3d');
    });

    it('open passes a failure on (the picker shows it)', async () => {
      vi.mocked(bridge.openWorkspace).mockRejectedValue(new Error('the workspace did not start'));
      await expect(open('standard')).rejects.toThrow('the workspace did not start');
    });

    it('openLauncher brings up the launcher', async () => {
      vi.mocked(bridge.openLauncher).mockResolvedValue(undefined);
      await openLauncher();
      expect(bridge.openLauncher).toHaveBeenCalledOnce();
    });
  });
});
