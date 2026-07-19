// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { Server } from '$lib/api/types';

// Infra store selection invariants (6.117): a selection that survives a reload/delete decides whether
// ServerDetail shows a live server or crashes on a null lookup. The sibling stores test this; infra
// didn't. Mock the API + side channels (session/status/i18n), same pattern as connections.test.
const h = vi.hoisted(() => ({
  list: vi.fn(async (..._a: unknown[]) => [] as Server[]),
  remove: vi.fn(async (..._a: unknown[]) => {}),
  create: vi.fn(async (..._a: unknown[]) => ({}) as Server),
  assignTemplate: vi.fn(async (..._a: unknown[]) => ({})),
  reportError: vi.fn(),
}));

vi.mock('$lib/api/servers', () => ({
  serversApi: { list: h.list, create: h.create, update: vi.fn(), remove: h.remove },
}));
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { assignTemplate: h.assignTemplate },
}));
vi.mock('./session', () => ({
  currentSession: () => ({
    serverUrl: 'https://srv',
    token: 't',
    refreshToken: 'r',
    username: 'a',
    isAdmin: true,
  }),
}));
vi.mock('./statusBar', () => ({ showStatus: vi.fn(), reportError: h.reportError }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));

import { loadServers, deleteServer, saveServer, setSelectedServer, infraSelectedId } from './infra';

const server = (id: string): Server => ({ id, name: id, hostname: 'h' });

describe('infra store selection invariants', () => {
  beforeEach(() => {
    h.list.mockReset();
    h.remove.mockReset();
    h.remove.mockResolvedValue(undefined);
  });

  it('loadServers drops a selection that no longer exists after the reload', async () => {
    h.list.mockResolvedValueOnce([server('s1'), server('s2')]);
    await loadServers();
    setSelectedServer('s1');
    expect(get(infraSelectedId)).toBe('s1');

    h.list.mockResolvedValueOnce([server('s2')]); // s1 is gone
    await loadServers();
    expect(get(infraSelectedId)).toBeNull();
  });

  it('loadServers keeps a selection that still exists', async () => {
    h.list.mockResolvedValueOnce([server('s1'), server('s2')]);
    await loadServers();
    setSelectedServer('s1');

    h.list.mockResolvedValueOnce([server('s1'), server('s3')]);
    await loadServers();
    expect(get(infraSelectedId)).toBe('s1');
  });

  it('deleteServer clears the selection only when the deleted id was selected', async () => {
    h.list.mockResolvedValue([server('s1'), server('s2')]);
    await loadServers();
    setSelectedServer('s2');

    await deleteServer('s1'); // a different server -> selection untouched
    expect(get(infraSelectedId)).toBe('s2');

    await deleteServer('s2'); // the selected one -> cleared
    expect(get(infraSelectedId)).toBeNull();
  });
});

describe('saveServer monitoring-template opt-in (T15)', () => {
  const input = (name: string, hostname: string) => ({
    name,
    hostname,
    os_type: null,
    tags: [],
    notes: '',
  });

  beforeEach(() => {
    h.create.mockReset();
    h.assignTemplate.mockReset();
    h.reportError.mockReset();
    h.list.mockResolvedValue([]);
  });

  it('assigns the chosen template with the created server data', async () => {
    h.create.mockResolvedValueOnce({ id: 'new-1', name: 'web01', hostname: 'web01.example' });
    const ok = await saveServer(input('web01', 'web01.example'), null, 'tpl-x');
    expect(ok).toBe(true);
    expect(h.assignTemplate).toHaveBeenCalledWith(
      expect.anything(),
      'tpl-x',
      'new-1',
      'web01.example',
      'web01',
    );
  });

  it('a failed assign reports but never fails the create', async () => {
    h.create.mockResolvedValueOnce({ id: 'new-1', name: 'web01', hostname: 'web01.example' });
    h.assignTemplate.mockRejectedValueOnce(new Error('monitoring down'));
    const ok = await saveServer(input('web01', 'web01.example'), null, 'tpl-x');
    expect(ok).toBe(true); // server stays created, modal may close
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('no template id means no assign call', async () => {
    h.create.mockResolvedValueOnce({ id: 'new-1', name: 'a', hostname: 'h' });
    await saveServer(input('a', 'h'), null, null);
    expect(h.assignTemplate).not.toHaveBeenCalled();
  });

  it('a 409 (already assigned by the tag sync) counts as success (T45)', async () => {
    h.create.mockResolvedValueOnce({ id: 'new-1', name: 'web01', hostname: 'web01.example' });
    h.assignTemplate.mockRejectedValueOnce(
      new Error('HTTP 409: Template bereits diesem Server zugewiesen'),
    );
    const ok = await saveServer(input('web01', 'web01.example'), null, 'tpl-x');
    expect(ok).toBe(true);
    expect(h.reportError).not.toHaveBeenCalled();
  });
});
