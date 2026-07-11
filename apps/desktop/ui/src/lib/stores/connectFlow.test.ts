// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// connectFlow is the core connect journey with a documented RDP race guard: a late rdp-error of an
// aborted attempt (correlationId) must not mark a newer attempt as failed, and markRdpError(null)
// clears every running attempt. These tests cover that race guard plus markConnectionUsed's
// mode-specific branches (6.5).

import { describe, it, expect, beforeEach, vi } from 'vitest';

// Shared mock state, hoisted so the vi.mock factories (which run before imports) can close over it.
const state = vi.hoisted(() => {
  let sessionValue: unknown = { settings: { mode: 'local', storePasswords: false }, session: null };
  let connectionsValue: unknown[] = [];
  return {
    setSession: (v: unknown) => {
      sessionValue = v;
    },
    setConnections: (v: unknown[]) => {
      connectionsValue = v;
    },
    sessionStore: {
      subscribe: (fn: (v: unknown) => void) => {
        fn(sessionValue);
        return () => {};
      },
    },
    connectionsStore: {
      subscribe: (fn: (v: unknown) => void) => {
        fn(connectionsValue);
        return () => {};
      },
    },
  };
});

vi.mock('$lib/bridge', () => ({
  openConnection: vi.fn(async () => {}),
  openConnectionStored: vi.fn(async () => {}),
  resolveConnection: vi.fn(async (c: unknown) => ({ connection: c })),
  passwordState: vi.fn(async () => ({ canStore: true, stored: false })),
  savePassword: vi.fn(async () => {}),
}));
vi.mock('./statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));
vi.mock('./tunnel', () => ({ getMappings: vi.fn(() => []) }));
vi.mock('./editor', () => ({ closeEditor: vi.fn() }));
vi.mock('./passwordPrompt', () => ({ requestPassword: vi.fn() }));
vi.mock('$lib/api/connections', () => ({ connectionsApi: { touch: vi.fn() } }));
vi.mock('$lib/models/connection', () => ({ validateConnection: vi.fn(() => ({ ok: true })) }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));
vi.mock('./session', () => ({ sessionStore: state.sessionStore }));
vi.mock('./connections', () => ({
  connections: state.connectionsStore,
  upsert: vi.fn(async () => {}),
  patchInMemory: vi.fn(),
}));

import { initiateConnect, markRdpError } from './connectFlow';
import { showStatus } from './statusBar';
import { connectionsApi } from '$lib/api/connections';
import { patchInMemory, upsert } from './connections';

const rdpConn = { id: 'r1', name: 'rdp', kind: 'rdp', host: 'h' } as never;

beforeEach(() => {
  vi.clearAllMocks();
  state.setSession({ settings: { mode: 'local', storePasswords: false }, session: null });
  state.setConnections([]);
});

describe('markRdpError race guard', () => {
  it('markRdpError(null) suppresses the delayed rdpStarting status', async () => {
    vi.useFakeTimers();
    await initiateConnect(rdpConn);
    markRdpError(null, 'auth failed'); // aborts every running attempt before the 800ms timer fires
    vi.advanceTimersByTime(800);
    expect(showStatus).not.toHaveBeenCalledWith('status.rdpStarting');
    vi.useRealTimers();
  });

  it('without an abort, the rdpStarting status fires after the delay', async () => {
    vi.useFakeTimers();
    await initiateConnect(rdpConn);
    vi.advanceTimersByTime(800);
    expect(showStatus).toHaveBeenCalledWith('status.rdpStarting');
    vi.useRealTimers();
  });
});

describe('markConnectionUsed mode branches', () => {
  it('server mode falls back to an in-memory patch when touch fails', async () => {
    state.setSession({ settings: { mode: 'server' }, session: { token: 't' } });
    (connectionsApi.touch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('offline'));
    const conn = { id: 'c1', name: 'c', kind: 'ssh', host: 'h' } as never;

    await initiateConnect(conn);

    expect(patchInMemory).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }));
  });

  it('sync mode patches in memory only (no touch, no upsert)', async () => {
    state.setSession({ settings: { mode: 'sync' }, session: null });
    const conn = { id: 'c2', name: 'c', kind: 'ssh', host: 'h' } as never;

    await initiateConnect(conn);

    expect(patchInMemory).toHaveBeenCalledWith(expect.objectContaining({ id: 'c2' }));
    expect(upsert).not.toHaveBeenCalled();
    expect(connectionsApi.touch).not.toHaveBeenCalled();
  });

  it('local mode upserts into the local store', async () => {
    state.setSession({ settings: { mode: 'local' }, session: null });
    const conn = { id: 'c3', name: 'c', kind: 'ssh', host: 'h' } as never;
    state.setConnections([conn]);

    await initiateConnect(conn);

    expect(upsert).toHaveBeenCalledWith(expect.objectContaining({ id: 'c3' }));
  });
});
