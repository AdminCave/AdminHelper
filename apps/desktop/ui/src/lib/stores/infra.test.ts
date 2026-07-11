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
}));

vi.mock('$lib/api/servers', () => ({
  serversApi: { list: h.list, create: vi.fn(), update: vi.fn(), remove: h.remove },
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
vi.mock('./statusBar', () => ({ showStatus: vi.fn(), reportError: vi.fn() }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));

import { loadServers, deleteServer, setSelectedServer, infraSelectedId } from './infra';

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
