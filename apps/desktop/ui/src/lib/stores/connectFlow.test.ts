// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// connectFlow is the core connect journey with a documented RDP race guard: a late rdp-error of an
// aborted attempt (correlationId) must not mark a newer attempt as failed, and markRdpError(null)
// clears every running attempt. These tests cover that race guard plus markConnectionUsed's
// mode-specific branches (6.5), the tunnel resolution without mappings, the keyring key of a
// stored RDP password behind a tunnel, the user and domain from the password prompt, which
// password a start takes after the prompt's "remember password", when the prompt offers it, that
// a refused resolution ends the start, and the screen an RDP start hands to Rust.

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

// What resolve_connection rejects with for a loopback port of another workspace's tunnel.
const FOREIGN_PORT =
  'port 6001 on this machine belongs to the tunnel of another workspace; start the tunnel of ' +
  'this workspace to connect';

// The screen jsdom reports to an RDP start that stubs none: no size, a device pixel ratio of 1.
const JSDOM_CLIENT = { screenWidth: 0, screenHeight: 0, scaleFactor: 1 };

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

// A user without a mapping for the connection; Rust still resolves a target of 127.0.0.1 at the
// server port of a visitor to the local port that visitor got.
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

  // Rust refuses a loopback port that another workspace's tunnel holds (open_connection would
  // refuse it too): its reason shows, not the URL check of the unresolved connection.
  it('reports why Rust refused to resolve and opens nothing', async () => {
    vi.mocked(resolveConnection).mockRejectedValueOnce(FOREIGN_PORT);

    await initiateConnect(autoConnection('web'));

    expect(reportError).toHaveBeenCalledWith(FOREIGN_PORT);
    expect(reportError).toHaveBeenCalledTimes(1);
    expect(validateConnection).not.toHaveBeenCalled();
    expect(openConnection).not.toHaveBeenCalled();
    expect(upsert).not.toHaveBeenCalled();
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
      client: JSDOM_CLIENT,
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
      client: JSDOM_CLIENT,
      correlationId: expect.any(String),
    });
  });
});

// Same fresh module graph: what counts is which IPC command starts the session. On Windows only
// open_connection_stored hands a password to mstsc; Rust drops one given to open_connection.
describe('RDP start after the prompt remembers the password', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.doUnmock('@tauri-apps/api/core');
  });

  const listed: Connection = {
    id: 'r4',
    name: 'rdp',
    kind: 'rdp',
    host: '127.0.0.1',
    port: 6004,
    username: 'admin',
    tags: [],
    trustCert: false,
  };
  const typed: Connection = { ...listed, username: 'alice', domain: 'CORP' };

  interface PromptRun {
    saveFails?: boolean;
    mode?: 'local' | 'server' | 'sync';
    // What the connections store holds: in server mode, what the server already keeps.
    inList?: Connection[];
  }

  async function connectAfterPrompt(
    remember: boolean,
    { saveFails = false, mode = 'local', inList = [] }: PromptRun = {},
  ) {
    const invoke = vi.fn(async (cmd: string, args?: { connection?: Connection }) => {
      if (cmd === 'password_state') return { canStore: true, stored: false };
      if (cmd === 'save_password' && saveFails) throw new Error('keyring locked');
      if (cmd === 'resolve_connection') {
        return { connection: { ...args?.connection, port: 23004 }, viaTunnel: true };
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
      remember,
    });
    const status = await import('./statusBar');
    const flow = await import('./connectFlow');
    state.setSession({
      settings: { mode, storePasswords: true },
      session: mode === 'server' ? {} : null,
    });
    state.setConnections(inList);
    vi.useFakeTimers();

    await flow.initiateConnect(listed);
    return {
      invoke,
      requestPassword: vi.mocked(prompt.requestPassword),
      reportError: vi.mocked(status.reportError),
    };
  }

  it('starts with the stored password once the remembered one is saved', async () => {
    const { invoke, reportError } = await connectAfterPrompt(true);

    expect(invoke).toHaveBeenCalledWith('save_password', { connection: typed, password: 'pw' });
    expect(invoke).toHaveBeenCalledWith('open_connection_stored', {
      connection: { ...typed, port: 23004 },
      credentialConnection: typed,
      client: JSDOM_CLIENT,
      correlationId: expect.any(String),
    });
    expect(invoke).not.toHaveBeenCalledWith('open_connection', expect.anything());
    expect(reportError).not.toHaveBeenCalled();
  });

  it('starts with the typed password and reports the error when saving fails', async () => {
    const { invoke, reportError } = await connectAfterPrompt(true, { saveFails: true });

    expect(reportError).toHaveBeenCalledWith('error.passwordStore');
    expect(invoke).toHaveBeenCalledWith('open_connection', {
      connection: { ...typed, port: 23004 },
      password: 'pw',
      client: JSDOM_CLIENT,
      correlationId: expect.any(String),
    });
    expect(invoke).not.toHaveBeenCalledWith('open_connection_stored', expect.anything());
  });

  it('starts with the typed password when it is not remembered', async () => {
    const { invoke } = await connectAfterPrompt(false);

    expect(invoke).not.toHaveBeenCalledWith('save_password', expect.anything());
    expect(invoke).toHaveBeenCalledWith('open_connection', {
      connection: { ...typed, port: 23004 },
      password: 'pw',
      client: JSDOM_CLIENT,
      correlationId: expect.any(String),
    });
    expect(invoke).not.toHaveBeenCalledWith('open_connection_stored', expect.anything());
  });

  // The keyring key holds the connection's id. In server mode one the server does not keep yet
  // (the editor's "Connect" before "Save") has a client id the server replaces when it is saved,
  // so a password stored under it would belong to no connection.
  it('offers no remembering in server mode for a connection the server does not keep', async () => {
    const { invoke, requestPassword } = await connectAfterPrompt(true, { mode: 'server' });

    expect(requestPassword).toHaveBeenCalledWith(listed, false, false);
    expect(invoke).not.toHaveBeenCalledWith('save_password', expect.anything());
    expect(invoke).toHaveBeenCalledWith('open_connection', {
      connection: { ...typed, port: 23004 },
      password: 'pw',
      client: JSDOM_CLIENT,
      correlationId: expect.any(String),
    });
    expect(invoke).not.toHaveBeenCalledWith('open_connection_stored', expect.anything());
  });

  it('offers remembering in server mode for a connection the server keeps', async () => {
    const { invoke, requestPassword } = await connectAfterPrompt(true, {
      mode: 'server',
      inList: [listed],
    });

    expect(requestPassword).toHaveBeenCalledWith(listed, false, true);
    expect(invoke).toHaveBeenCalledWith('save_password', { connection: typed, password: 'pw' });
  });

  it.each(['local', 'sync'] as const)(
    'offers remembering in %s mode for a connection not in the list',
    async (mode) => {
      const { invoke, requestPassword } = await connectAfterPrompt(true, { mode });

      expect(requestPassword).toHaveBeenCalledWith(listed, false, true);
      expect(invoke).toHaveBeenCalledWith('save_password', { connection: typed, password: 'pw' });
    },
  );
});

// Same fresh module graph: a refusal of resolve_connection ends an RDP start before the keyring
// and the prompt, and after the prompt before the start.
describe('RDP start Rust refuses to resolve', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.doUnmock('@tauri-apps/api/core');
  });

  const listed: Connection = {
    id: 'r5',
    name: 'rdp',
    kind: 'rdp',
    host: '127.0.0.1',
    port: 6001,
    username: 'admin',
    tags: [],
    trustCert: false,
  };

  // Rust refuses from the `refuseFrom`-th call of resolve_connection on (1-based).
  async function connectRefused(refuseFrom: number) {
    let resolves = 0;
    const invoke = vi.fn(async (cmd: string, args?: { connection?: Connection }) => {
      if (cmd === 'password_state') return { canStore: true, stored: false };
      if (cmd === 'resolve_connection') {
        resolves += 1;
        if (resolves >= refuseFrom) throw FOREIGN_PORT;
        return { connection: args?.connection, viaTunnel: false };
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
      updated: listed,
      password: 'pw',
      remember: false,
    });
    const status = await import('./statusBar');
    const flow = await import('./connectFlow');
    state.setSession({ settings: { mode: 'local', storePasswords: true }, session: null });
    vi.useFakeTimers();

    await flow.initiateConnect(listed);
    return {
      invoke,
      requestPassword: vi.mocked(prompt.requestPassword),
      reportError: vi.mocked(status.reportError),
    };
  }

  it('asks for no password when Rust refuses the listed target', async () => {
    const { invoke, requestPassword, reportError } = await connectRefused(1);

    expect(reportError).toHaveBeenCalledWith(FOREIGN_PORT);
    expect(reportError).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith('password_state', expect.anything());
    expect(requestPassword).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalledWith('open_connection', expect.anything());
  });

  it('starts nothing when Rust refuses the target after the prompt', async () => {
    const { invoke, requestPassword, reportError } = await connectRefused(2);

    expect(requestPassword).toHaveBeenCalledTimes(1);
    expect(reportError).toHaveBeenCalledWith(FOREIGN_PORT);
    expect(reportError).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith('open_connection', expect.anything());
    expect(invoke).not.toHaveBeenCalledWith('open_connection_stored', expect.anything());
  });
});

// Same fresh module graph: Rust sizes "Fit" from the screen and picks the scale of "Automatic" and
// "HiDPI" from it (rdp_logic.rs fit_window_size, hdpi_scale), so both ways to start RDP hand it on.
describe('RDP start hands the screen to Rust', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.doUnmock('@tauri-apps/api/core');
  });

  const listed: Connection = {
    id: 'r6',
    name: 'rdp',
    kind: 'rdp',
    host: 'rdp.example.com',
    port: 3389,
    username: 'admin',
    tags: [],
    trustCert: false,
  };

  async function connectOnHidpiScreen(stored: boolean) {
    const invoke = vi.fn(async (cmd: string, args?: { connection?: Connection }) => {
      if (cmd === 'password_state') return { canStore: true, stored };
      if (cmd === 'resolve_connection') return { connection: args?.connection, viaTunnel: false };
      return undefined;
    });

    vi.stubGlobal('__TAURI_INTERNALS__', {});
    vi.resetModules();
    vi.doUnmock('$lib/bridge');
    vi.doMock('@tauri-apps/api/core', () => ({ invoke }));
    const prompt = await import('./passwordPrompt');
    vi.mocked(prompt.requestPassword).mockResolvedValue({
      cancelled: false,
      updated: listed,
      password: 'pw',
      remember: false,
    });
    const flow = await import('./connectFlow');
    // After the import: the window may have moved to another screen since, the start reads it.
    vi.stubGlobal('screen', { width: 1920, height: 1080 });
    vi.stubGlobal('devicePixelRatio', 2);
    state.setSession({ settings: { mode: 'local', storePasswords: true }, session: null });
    vi.useFakeTimers();

    await flow.initiateConnect(listed);
    return invoke;
  }

  it('hands the screen to open_connection after the password prompt', async () => {
    const invoke = await connectOnHidpiScreen(false);

    expect(invoke).toHaveBeenCalledWith('open_connection', {
      connection: listed,
      password: 'pw',
      client: { screenWidth: 1920, screenHeight: 1080, scaleFactor: 2 },
      correlationId: expect.any(String),
    });
  });

  it('hands the screen to open_connection_stored with a stored password', async () => {
    const invoke = await connectOnHidpiScreen(true);

    expect(invoke).toHaveBeenCalledWith('open_connection_stored', {
      connection: listed,
      credentialConnection: listed,
      client: { screenWidth: 1920, screenHeight: 1080, scaleFactor: 2 },
      correlationId: expect.any(String),
    });
  });
});
