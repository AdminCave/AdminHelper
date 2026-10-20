// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// connectFlow is the core connect journey with a documented RDP race guard: a late rdp-error of an
// aborted attempt (correlationId) must not mark a newer attempt as failed, and markRdpError(null)
// clears every running attempt. These tests cover that race guard plus markConnectionUsed's
// mode-specific branches (6.5), the tunnel resolution without mappings, the keyring key of a
// stored RDP password behind a tunnel, and the user and domain from the password prompt.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Connection, TunnelMapping } from '$lib/bridge/types';

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
import { reportError, showStatus } from './statusBar';
import { connectionsApi } from '$lib/api/connections';
import { validateConnection } from '$lib/models/connection';
import { openConnection, resolveConnection } from '$lib/bridge';
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
    state.setSession({ settings: { mode: 'server' }, session: {} });
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

// Only admins read mappings, so a non-admin has none; Rust still resolves a target of 127.0.0.1 at
// the server port of a visitor to the local port that visitor got.
describe('tunnel resolution without mappings', () => {
  const autoConnection = (kind: 'ssh' | 'web'): Connection => ({
    id: `${kind}-auto`,
    name: `${kind} (via FRP)`,
    kind,
    host: '127.0.0.1',
    port: 6001,
    url: null,
    tags: [],
    trustCert: false,
  });

  it('resolves the connection and opens what Rust returns', async () => {
    const listed = autoConnection('ssh');
    const resolved: Connection = { ...listed, port: 23001 };
    vi.mocked(resolveConnection).mockResolvedValueOnce({ connection: resolved, viaTunnel: true });

    await initiateConnect(listed);

    expect(resolveConnection).toHaveBeenCalledWith(listed, []);
    expect(openConnection).toHaveBeenCalledWith(resolved, undefined);
  });

  // The server creates its automatic web connections without a URL; the visitor gives them one.
  it('opens a web auto connection without a URL at the URL of its visitor', async () => {
    const actual =
      await vi.importActual<typeof import('$lib/models/connection')>('$lib/models/connection');
    vi.mocked(validateConnection).mockImplementationOnce(actual.validateConnection);
    const listed = autoConnection('web');
    const resolved: Connection = { ...listed, port: 23001, url: 'http://127.0.0.1:23001' };
    vi.mocked(resolveConnection).mockResolvedValueOnce({ connection: resolved, viaTunnel: true });

    await initiateConnect(listed);

    expect(reportError).not.toHaveBeenCalled();
    expect(openConnection).toHaveBeenCalledWith(resolved, undefined);
  });

  it('reports a web connection without a URL that no visitor resolves', async () => {
    const actual =
      await vi.importActual<typeof import('$lib/models/connection')>('$lib/models/connection');
    vi.mocked(validateConnection).mockImplementationOnce(actual.validateConnection);

    await initiateConnect(autoConnection('web'));

    expect(reportError).toHaveBeenCalledWith('validation.url.empty');
    expect(openConnection).not.toHaveBeenCalled();
  });
});

// The stored-password path runs only when connectFlow saw __TAURI_INTERNALS__ at import, and what
// counts is the IPC payload Rust receives. So this case loads a fresh module graph with the real
// bridge on top of a stubbed invoke; the static imports above keep their own instances.
describe('stored RDP password behind a tunnel', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.doUnmock('@tauri-apps/api/core');
  });

  it('opens the resolved connection and loads the password under the listed one', async () => {
    const listed: Connection = {
      id: 'r2',
      name: 'rdp',
      kind: 'rdp',
      host: 'rdp.example.com',
      port: 3389,
      username: 'admin',
      tags: [],
      trustCert: false,
    };
    const resolved: Connection = { ...listed, host: '127.0.0.1', port: 6000 };
    const mapping: TunnelMapping = {
      id: 't1',
      serverId: 's1',
      tunnelType: 'stcp',
      protocol: 'tcp',
      localPort: 3389,
      visitorPort: 6000,
      customDomains: null,
      connectionId: 'r2',
      enabled: true,
      name: 'rdp',
    };
    const invoke = vi.fn(async (cmd: string) => {
      if (cmd === 'password_state') return { canStore: true, stored: true };
      if (cmd === 'resolve_connection') return { connection: resolved };
      return undefined;
    });

    vi.stubGlobal('__TAURI_INTERNALS__', {});
    vi.resetModules();
    vi.doUnmock('$lib/bridge');
    vi.doMock('@tauri-apps/api/core', () => ({ invoke }));
    const tunnel = await import('./tunnel');
    vi.mocked(tunnel.getMappings).mockReturnValue([mapping]);
    const flow = await import('./connectFlow');
    state.setSession({ settings: { mode: 'local', storePasswords: true }, session: null });
    vi.useFakeTimers();

    await flow.initiateConnect(listed);

    expect(invoke).toHaveBeenCalledWith('password_state', { connection: listed });
    expect(invoke).toHaveBeenCalledWith('open_connection_stored', {
      connection: resolved,
      credentialConnection: listed,
      client: undefined,
      correlationId: expect.any(String),
    });
  });
});

// Same fresh module graph as above: the prompt path, too, runs only under __TAURI_INTERNALS__.
describe('RDP password prompt behind a tunnel', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.doUnmock('@tauri-apps/api/core');
  });

  it('opens the resolution of the connection with the user and domain from the prompt', async () => {
    const listed: Connection = {
      id: 'r3',
      name: 'rdp',
      kind: 'rdp',
      host: '127.0.0.1',
      port: 6002,
      username: 'admin',
      tags: [],
      trustCert: false,
    };
    const typed: Connection = { ...listed, username: 'alice', domain: 'CORP' };
    const invoke = vi.fn(async (cmd: string, args?: { connection?: Connection }) => {
      if (cmd === 'password_state') return { canStore: true, stored: false };
      if (cmd === 'resolve_connection') {
        return { connection: { ...args?.connection, port: 23002 }, viaTunnel: true };
      }
      return undefined;
    });

    vi.stubGlobal('__TAURI_INTERNALS__', {});
    vi.resetModules();
    vi.doUnmock('$lib/bridge');
    vi.doMock('@tauri-apps/api/core', () => ({ invoke }));
    const prompt = await import('./passwordPrompt');
    vi.mocked(prompt.requestPassword).mockResolvedValue({
      cancelled: false,
      updated: typed,
      password: 'pw',
      remember: false,
    });
    const flow = await import('./connectFlow');
    state.setSession({ settings: { mode: 'local', storePasswords: true }, session: null });
    vi.useFakeTimers();

    await flow.initiateConnect(listed);

    expect(invoke).toHaveBeenCalledWith('open_connection', {
      connection: { ...typed, port: 23002 },
      password: 'pw',
      client: undefined,
      correlationId: expect.any(String),
    });
  });
});
