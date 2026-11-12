// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// connectFlow is the core connect journey with a documented RDP race guard: a late rdp-error of an
// aborted attempt (correlationId) must not mark a newer attempt as failed, and markRdpError(null)
// clears every running attempt. These tests cover that race guard plus markConnectionUsed's
// mode-specific branches (6.5), the tunnel resolution without mappings, the keyring key of a
// stored RDP password behind a tunnel, the user and domain from the password prompt, which
// password a start takes after the prompt's "remember password", when the prompt offers it, that
// a refused resolution ends the start, the screen an RDP start hands to Rust, which console an
// SSH start takes, where an RDP start opens and with which password (R-1098), and the session
// history: a connect begins a session, the rdp-exit of its start ends it (R-1068), and that a
// reconnect of an RDP tab after a refused login asks for the password again (R-1196).

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Connection, TunnelMapping } from '$lib/bridge/types';

// Shared mock state, hoisted so the vi.mock factories (which run before imports) can close over it.
const state = vi.hoisted(() => {
  let sessionValue: unknown = { settings: { mode: 'local', storePasswords: false }, session: null };
  let connectionsValue: unknown[] = [];
  let terminalsValue: unknown = { sessions: [], active: 'page' };
  return {
    setTerminals: (v: unknown) => {
      terminalsValue = v;
    },
    terminalsStore: {
      subscribe: (fn: (v: unknown) => void) => {
        fn(terminalsValue);
        return () => {};
      },
    },
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
  startSession: vi.fn(async (connectionId: string) => ({ id: `local-${connectionId}` })),
  endSession: vi.fn(async () => {}),
  // A hostname with a bell, a newline and blanks: the server refuses control characters.
  deviceName: vi.fn(async () => ' box\u0007\n'),
}));
vi.mock('./statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));
vi.mock('./tunnel', () => ({ getMappings: vi.fn(() => []) }));
vi.mock('./editor', () => ({ closeEditor: vi.fn() }));
vi.mock('./terminals', () => ({
  openTerminal: vi.fn(async () => true),
  openRdp: vi.fn(async () => 'started'),
  reconnectRdp: vi.fn(async () => true),
  terminals: state.terminalsStore,
}));
vi.mock('./passwordPrompt', () => ({ requestPassword: vi.fn() }));
vi.mock('$lib/api/connections', () => ({
  connectionsApi: { touch: vi.fn(), endSession: vi.fn(async () => ({})) },
}));
vi.mock('$lib/models/connection', () => ({ validateConnection: vi.fn(() => ({ ok: true })) }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));
vi.mock('./session', () => ({ sessionStore: state.sessionStore }));
vi.mock('./connections', () => ({
  connections: state.connectionsStore,
  upsert: vi.fn(async () => {}),
  patchInMemory: vi.fn(),
  sessionsChanged: vi.fn(),
}));

import {
  connectCredential,
  connectServiceLog,
  initiateConnect,
  markRdpError,
  markRdpExit,
  reconnectRdpTab,
} from './connectFlow';
import { reportError, showStatus } from './statusBar';
import { connectionsApi } from '$lib/api/connections';
import { validateConnection } from '$lib/models/connection';
import {
  endSession,
  openConnection,
  openConnectionStored,
  passwordState,
  resolveConnection,
  savePassword,
  startSession,
} from '$lib/bridge';
import { patchInMemory, sessionsChanged, upsert } from './connections';
import { closeEditor } from './editor';
import { openRdp, openTerminal, reconnectRdp } from './terminals';
import { requestPassword } from './passwordPrompt';

const settleAll = () => new Promise((resolve) => setTimeout(resolve, 0));

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
  state.setTerminals({ sessions: [], active: 'page' });
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
    // The OS terminal; the embedded one at a resolved target is tested with the console below.
    state.setSession({
      settings: { mode: 'local', storePasswords: false, sshConsole: 'external' },
      session: null,
    });
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

describe('session history (R-1068)', () => {
  // The correlationId the last RDP start handed to Rust.
  const lastCid = (): string =>
    (openConnection as ReturnType<typeof vi.fn>).mock.calls.at(-1)![3] as string;

  it('server mode: touch carries the cleaned device, rdp-exit ends the session there', async () => {
    const session = { token: 't' };
    state.setSession({ settings: { mode: 'server' }, session });
    (connectionsApi.touch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'r1',
      sessionId: 's-9',
    });

    await initiateConnect(rdpConn);

    expect(connectionsApi.touch).toHaveBeenCalledWith(session, 'r1', 'box');
    // The session id is no field of the connection.
    expect(patchInMemory).toHaveBeenCalledWith({ id: 'r1' });
    expect(startSession).not.toHaveBeenCalled();
    const cid = lastCid();
    await markRdpExit(cid);
    expect(connectionsApi.endSession).toHaveBeenCalledWith(session, 'r1', 's-9');
    // A second exit of the same start ends nothing more.
    await markRdpExit(cid);
    expect(connectionsApi.endSession).toHaveBeenCalledTimes(1);
  });

  it('local mode: the session goes to the local history and rdp-exit ends it', async () => {
    state.setConnections([rdpConn]);
    await initiateConnect(rdpConn);

    expect(startSession).toHaveBeenCalledWith('r1');
    expect(connectionsApi.touch).not.toHaveBeenCalled();
    // A shown history reloads once the session is written, and again once it ended.
    expect(sessionsChanged).toHaveBeenCalledTimes(1);
    await markRdpExit(lastCid());
    expect(endSession).toHaveBeenCalledWith('local-r1');
    expect(sessionsChanged).toHaveBeenCalledTimes(2);
  });

  it('sync mode writes the local history too, and SSH begins a session without an end', async () => {
    state.setSession({ settings: { mode: 'sync' }, session: null });
    await initiateConnect({ id: 'c9', name: 'c', kind: 'ssh', host: 'h' } as never);
    expect(startSession).toHaveBeenCalledWith('c9');
    expect(endSession).not.toHaveBeenCalled();
  });

  it('an SSH start in the embedded terminal reloads a shown history too', async () => {
    state.setSession({
      settings: { mode: 'local', storePasswords: false, sshConsole: 'embedded' },
      session: null,
    });
    await initiateConnect({ id: 's7', name: 's', kind: 'ssh', host: 'h' } as never);
    expect(openTerminal).toHaveBeenCalledOnce();
    expect(startSession).toHaveBeenCalledWith('s7');
    expect(sessionsChanged).toHaveBeenCalledTimes(1);
  });

  // The end of the tab, as the last embedded start heard it.
  const tabEnd = (): (() => void) => vi.mocked(openTerminal).mock.calls.at(-1)![2]!;
  const embedded = (mode: 'local' | 'server', session: unknown = null) =>
    state.setSession({
      settings: { mode, storePasswords: false, sshConsole: 'embedded' },
      session,
    });

  it('the end of an embedded SSH tab ends its session in the local history', async () => {
    embedded('local');
    await initiateConnect({ id: 's7', name: 's', kind: 'ssh', host: 'h' } as never);
    expect(endSession).not.toHaveBeenCalled();
    tabEnd()();
    await vi.waitFor(() => expect(endSession).toHaveBeenCalledWith('local-s7'));
    expect(endSession).toHaveBeenCalledTimes(1);
    expect(sessionsChanged).toHaveBeenCalledTimes(2);
  });

  it('the end of an embedded SSH tab ends its session on the server', async () => {
    const session = { token: 't' };
    embedded('server', session);
    (connectionsApi.touch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 's7',
      sessionId: 's-3',
    });
    await initiateConnect({ id: 's7', name: 's', kind: 'ssh', host: 'h' } as never);
    tabEnd()();
    await vi.waitFor(() =>
      expect(connectionsApi.endSession).toHaveBeenCalledWith(session, 's7', 's-3'),
    );
    expect(endSession).not.toHaveBeenCalled();
  });

  it('a tab that ended before its session was written ends that session right after', async () => {
    embedded('local');
    vi.mocked(openTerminal).mockImplementationOnce(async (_c, _r, onEnd) => {
      onEnd?.();
      return true;
    });
    await initiateConnect({ id: 's8', name: 's', kind: 'ssh', host: 'h' } as never);
    await vi.waitFor(() => expect(endSession).toHaveBeenCalledWith('local-s8'));
    expect(startSession).toHaveBeenCalledWith('s8');
  });

  it('an embedded start that did not open begins no session', async () => {
    embedded('local');
    vi.mocked(openTerminal).mockResolvedValueOnce(false);
    await initiateConnect({ id: 's9', name: 's', kind: 'ssh', host: 'h' } as never);
    tabEnd()();
    await settleAll();
    expect(startSession).not.toHaveBeenCalled();
    expect(endSession).not.toHaveBeenCalled();
  });

  it('a start that fails ends its session at once; an unknown exit is ignored', async () => {
    (openConnection as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('no client'));
    await initiateConnect(rdpConn);
    await vi.waitFor(() => expect(endSession).toHaveBeenCalledWith('local-r1'));
    await markRdpExit('unknown');
    expect(endSession).toHaveBeenCalledTimes(1);
  });

  it('a session that could not be written leaves nothing to end', async () => {
    (startSession as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('broken file'));
    await initiateConnect(rdpConn);
    await markRdpExit(lastCid());
    expect(endSession).not.toHaveBeenCalled();
    expect(sessionsChanged).not.toHaveBeenCalled();
    expect(reportError).not.toHaveBeenCalled();
  });
});

describe('SSH console (R-1069)', () => {
  const sshConn: Connection = {
    id: 's1',
    name: 'ssh',
    kind: 'ssh',
    host: 'h',
    port: 22,
    url: null,
    tags: [],
    trustCert: false,
  };

  const withConsole = (sshConsole: 'embedded' | 'external') =>
    state.setSession({
      settings: { mode: 'local', storePasswords: false, sshConsole },
      session: null,
    });

  it('opens a tab of the embedded terminal at the resolved target when the settings ask', async () => {
    withConsole('embedded');
    const resolved: Connection = { ...sshConn, port: 23001 };
    vi.mocked(resolveConnection).mockResolvedValueOnce({ connection: resolved, viaTunnel: true });

    await initiateConnect(sshConn);

    // A shell: no action instead (arch-monitoring-ui).
    expect(openTerminal).toHaveBeenCalledWith(sshConn, resolved, expect.any(Function), undefined);
    expect(openConnection).not.toHaveBeenCalled();
    expect(upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 's1', lastUsed: expect.any(String) }),
    );
    expect(closeEditor).toHaveBeenCalledOnce();
    expect(showStatus).not.toHaveBeenCalled();
  });

  it('starts the OS terminal when the settings ask', async () => {
    withConsole('external');
    await initiateConnect(sshConn);

    expect(openConnection).toHaveBeenCalledOnce();
    expect(openTerminal).not.toHaveBeenCalled();
  });

  it('opens the embedded terminal, the default, while the settings have not loaded', async () => {
    state.setSession({ settings: null, session: null });
    await initiateConnect(sshConn);

    expect(openTerminal).toHaveBeenCalledOnce();
    expect(openConnection).not.toHaveBeenCalled();
  });

  it('takes the console asked for at the start over the setting', async () => {
    withConsole('external');
    await initiateConnect(sshConn, false, 'embedded');
    expect(openTerminal).toHaveBeenCalledOnce();
    expect(openConnection).not.toHaveBeenCalled();

    withConsole('embedded');
    await initiateConnect(sshConn, false, 'external');
    expect(openConnection).toHaveBeenCalledWith(sshConn, undefined);
    expect(openTerminal).toHaveBeenCalledOnce();
  });

  it('keeps the editor open when the start asks', async () => {
    withConsole('embedded');
    await initiateConnect(sshConn, true);
    expect(openTerminal).toHaveBeenCalledOnce();
    expect(closeEditor).not.toHaveBeenCalled();
  });

  it('marks nothing used and keeps the editor when the program did not start', async () => {
    withConsole('embedded');
    vi.mocked(openTerminal).mockResolvedValueOnce(false);
    await initiateConnect(sshConn);
    expect(upsert).not.toHaveBeenCalled();
    expect(closeEditor).not.toHaveBeenCalled();
  });

  it('reports a failed lastUsed and still closes the editor over the open tab', async () => {
    withConsole('embedded');
    vi.mocked(upsert).mockRejectedValueOnce(new Error('disk full'));
    await initiateConnect(sshConn);
    expect(reportError).toHaveBeenCalledWith('disk full');
    expect(closeEditor).toHaveBeenCalledOnce();
  });

  it('opens no tab for a refused resolution or an invalid connection', async () => {
    withConsole('embedded');
    vi.mocked(resolveConnection).mockRejectedValueOnce(new Error(FOREIGN_PORT));
    await initiateConnect(sshConn);
    vi.mocked(validateConnection).mockReturnValueOnce({ ok: false, message: 'bad host' });
    await initiateConnect(sshConn);

    expect(openTerminal).not.toHaveBeenCalled();
    expect(reportError).toHaveBeenCalledWith(FOREIGN_PORT);
    expect(reportError).toHaveBeenCalledWith('bad host');
  });

  it('opens RDP and web connections as before whatever the console', async () => {
    withConsole('embedded');
    const web: Connection = { ...sshConn, id: 'w1', kind: 'web', url: 'https://example.test' };
    await initiateConnect(web, false, 'embedded');
    await initiateConnect(rdpConn);

    expect(openTerminal).not.toHaveBeenCalled();
    expect(openConnection).toHaveBeenCalledWith(web, undefined);
    expect(openConnection).toHaveBeenCalledWith(
      rdpConn,
      undefined,
      JSDOM_CLIENT,
      expect.any(String),
    );
  });

  // arch-monitoring-ui T10: the agent's prompt for a monitoring credential runs only in the
  // embedded terminal, whatever the console; a session like any start, the editor left alone.
  it('opens the credential prompt embedded at the resolved target whatever the console', async () => {
    withConsole('external');
    const resolved: Connection = { ...sshConn, port: 23001 };
    vi.mocked(resolveConnection).mockResolvedValueOnce({ connection: resolved, viaTunnel: true });

    await connectCredential(sshConn, 'mysql/3306/monitor');

    expect(openTerminal).toHaveBeenCalledWith(sshConn, resolved, expect.any(Function), {
      credential: { ref: 'mysql/3306/monitor' },
    });
    expect(openConnection).not.toHaveBeenCalled();
    expect(upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 's1', lastUsed: expect.any(String) }),
    );
    expect(closeEditor).not.toHaveBeenCalled();
  });

  it('opens no credential prompt for a refused resolution or an invalid connection', async () => {
    vi.mocked(resolveConnection).mockRejectedValueOnce(new Error(FOREIGN_PORT));
    await connectCredential(sshConn, 'mysql/3306/monitor');
    vi.mocked(validateConnection).mockReturnValueOnce({ ok: false, message: 'bad host' });
    await connectCredential(sshConn, 'mysql/3306/monitor');

    expect(openTerminal).not.toHaveBeenCalled();
    expect(reportError).toHaveBeenCalledWith(FOREIGN_PORT);
    expect(reportError).toHaveBeenCalledWith('bad host');
  });

  // arch-monitoring-ui-3 T10: "Mehr Log" shows the journal of a unit in the embedded terminal
  // only, whatever the console; a session like any start, the editor left alone.
  it('opens the journal of a unit embedded at the resolved target whatever the console', async () => {
    withConsole('external');
    const resolved: Connection = { ...sshConn, port: 23001 };
    vi.mocked(resolveConnection).mockResolvedValueOnce({ connection: resolved, viaTunnel: true });

    await connectServiceLog(sshConn, 'nginx.service');

    expect(openTerminal).toHaveBeenCalledExactlyOnceWith(sshConn, resolved, expect.any(Function), {
      journal: { unit: 'nginx.service' },
    });
    expect(openConnection).not.toHaveBeenCalled();
    expect(upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 's1', lastUsed: expect.any(String) }),
    );
    expect(closeEditor).not.toHaveBeenCalled();
  });

  it('opens no journal for a refused resolution or an invalid connection', async () => {
    vi.mocked(resolveConnection).mockRejectedValueOnce(new Error(FOREIGN_PORT));
    await connectServiceLog(sshConn, 'nginx.service');
    vi.mocked(validateConnection).mockReturnValueOnce({ ok: false, message: 'bad host' });
    await connectServiceLog(sshConn, 'nginx.service');

    expect(openTerminal).not.toHaveBeenCalled();
    expect(reportError).toHaveBeenCalledWith(FOREIGN_PORT);
    expect(reportError).toHaveBeenCalledWith('bad host');
  });
});

// Where an RDP start opens (R-1098): the client of the settings, by default the OS one, or the one
// asked for at the start. A tab takes the stored password or asks for one, since no OS client is
// there to ask; one only the OS client can open starts there with the same password.
describe('RDP in a tab (R-1098)', () => {
  afterEach(() => vi.useRealTimers());

  const typed: Connection = { ...(rdpConn as Connection), username: 'alice', domain: 'CORP' };

  const withClient = (rdpClient: 'embedded' | 'os' | undefined, storePasswords = true) =>
    state.setSession({ settings: { mode: 'local', storePasswords, rdpClient }, session: null });

  const prompted = (password: string, remember = false) =>
    vi.mocked(requestPassword).mockResolvedValueOnce({
      cancelled: false,
      updated: typed,
      password,
      remember,
    });

  it('opens a tab with the stored password when the settings ask, and asks for none', async () => {
    withClient('embedded');
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });

    await initiateConnect(rdpConn);

    expect(openRdp).toHaveBeenCalledExactlyOnceWith(rdpConn, undefined, expect.any(Function));
    expect(requestPassword).not.toHaveBeenCalled();
    expect(openConnection).not.toHaveBeenCalled();
    expect(upsert).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1' }));
    expect(closeEditor).toHaveBeenCalledOnce();
  });

  it('starts the OS client, the default, without a setting or before the settings load', async () => {
    withClient(undefined);
    await initiateConnect(rdpConn);
    state.setSession({ settings: null, session: null });
    await initiateConnect(rdpConn);

    expect(openRdp).not.toHaveBeenCalled();
    expect(openConnection).toHaveBeenCalledTimes(2);
  });

  it('takes the client asked for at the start over the setting', async () => {
    withClient('os');
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });
    await initiateConnect(rdpConn, false, 'embedded');
    expect(openRdp).toHaveBeenCalledOnce();

    withClient('embedded');
    await initiateConnect(rdpConn, false, 'external');
    expect(openRdp).toHaveBeenCalledOnce();
    expect(openConnection).toHaveBeenCalledOnce();
  });

  it('hands the typed password to the tab when it is not remembered', async () => {
    withClient('embedded');
    prompted('pw');
    await initiateConnect(rdpConn, true);

    expect(requestPassword).toHaveBeenCalledWith(rdpConn, true, true);
    expect(savePassword).not.toHaveBeenCalled();
    expect(openRdp).toHaveBeenCalledExactlyOnceWith(typed, 'pw', expect.any(Function));
    expect(closeEditor).not.toHaveBeenCalled();
  });

  it('hands no password to the tab once the remembered one is saved', async () => {
    withClient('embedded');
    prompted('pw', true);
    await initiateConnect(rdpConn);

    expect(savePassword).toHaveBeenCalledWith(typed, 'pw');
    expect(openRdp).toHaveBeenCalledExactlyOnceWith(typed, undefined, expect.any(Function));
  });

  it('asks without a store and offers no remembering, and keeps the typed one on a failed save', async () => {
    withClient('embedded', false);
    prompted('pw');
    await initiateConnect(rdpConn);
    expect(passwordState).not.toHaveBeenCalled();
    expect(requestPassword).toHaveBeenLastCalledWith(rdpConn, false, false);
    expect(openRdp).toHaveBeenLastCalledWith(typed, 'pw', expect.any(Function));

    withClient('embedded');
    prompted('pw2', true);
    vi.mocked(savePassword).mockRejectedValueOnce(new Error('keyring locked'));
    await initiateConnect(rdpConn);
    expect(reportError).toHaveBeenCalledWith('error.passwordStore');
    expect(openRdp).toHaveBeenLastCalledWith(typed, 'pw2', expect.any(Function));
  });

  it('starts nothing once the prompt is cancelled', async () => {
    withClient('embedded');
    vi.mocked(requestPassword).mockResolvedValueOnce({ cancelled: true });
    await initiateConnect(rdpConn);

    expect(openRdp).not.toHaveBeenCalled();
    expect(openConnection).not.toHaveBeenCalled();
    expect(upsert).not.toHaveBeenCalled();
  });

  // The end of the tab, as the last RDP tab heard it.
  const rdpTabEnd = (): (() => void) => vi.mocked(openRdp).mock.calls.at(-1)![2]!;

  it('the end of the tab ends its session in the local history once (R-1273)', async () => {
    withClient('embedded');
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });
    await initiateConnect(rdpConn);
    expect(startSession).toHaveBeenCalledWith('r1');
    expect(endSession).not.toHaveBeenCalled();
    rdpTabEnd()();
    await vi.waitFor(() => expect(endSession).toHaveBeenCalledWith('local-r1'));
    rdpTabEnd()();
    await settleAll();
    expect(endSession).toHaveBeenCalledTimes(1);
    expect(sessionsChanged).toHaveBeenCalledTimes(2);
  });

  it('the end of the tab ends its session on the server (R-1273)', async () => {
    const session = { token: 't' };
    state.setSession({
      settings: { mode: 'server', storePasswords: true, rdpClient: 'embedded' },
      session,
    });
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });
    (connectionsApi.touch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'r1',
      sessionId: 's-5',
    });
    await initiateConnect(rdpConn);
    rdpTabEnd()();
    await vi.waitFor(() =>
      expect(connectionsApi.endSession).toHaveBeenCalledWith(session, 'r1', 's-5'),
    );
    expect(endSession).not.toHaveBeenCalled();
  });

  it('marks nothing used and keeps the editor when the tab did not start', async () => {
    withClient('embedded');
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });
    vi.mocked(openRdp).mockResolvedValueOnce('failed');
    await initiateConnect(rdpConn);

    expect(upsert).not.toHaveBeenCalled();
    expect(closeEditor).not.toHaveBeenCalled();
    expect(openConnection).not.toHaveBeenCalled();
  });

  it('starts one only the OS client opens there with the typed password and says so', async () => {
    vi.useFakeTimers();
    withClient('embedded');
    prompted('pw');
    const resolvedTyped: Connection = { ...typed, port: 23004 };
    // Resolved once before the prompt and once after it, with the user it returned.
    vi.mocked(resolveConnection)
      .mockResolvedValueOnce({ connection: rdpConn, viaTunnel: false })
      .mockResolvedValueOnce({ connection: resolvedTyped, viaTunnel: true });
    vi.mocked(openRdp).mockResolvedValueOnce('os-client');

    await initiateConnect(rdpConn);
    vi.advanceTimersByTime(800);

    expect(openConnection).toHaveBeenCalledExactlyOnceWith(
      resolvedTyped,
      'pw',
      JSDOM_CLIENT,
      expect.any(String),
    );
    expect(showStatus).toHaveBeenCalledWith('status.rdpOsClient');
    expect(showStatus).not.toHaveBeenCalledWith('status.rdpStarting');
  });

  it('starts one only the OS client opens there the stored way with a stored password', async () => {
    withClient('embedded');
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });
    vi.mocked(openRdp).mockResolvedValueOnce('os-client');
    await initiateConnect(rdpConn);

    expect(openConnectionStored).toHaveBeenCalledExactlyOnceWith(
      rdpConn,
      rdpConn,
      JSDOM_CLIENT,
      expect.any(String),
    );
    expect(openConnection).not.toHaveBeenCalled();
  });
});

describe('reconnect of an RDP tab (R-1196)', () => {
  const KEY = 'terminal-7';
  const listed: Connection = {
    id: 'r7',
    name: 'rdp',
    kind: 'rdp',
    host: 'win.example',
    port: 3389,
    username: 'admin',
    tags: [],
    trustCert: false,
  };
  const typed: Connection = { ...listed, username: 'alice', domain: 'CORP' };

  const tabEnded = (code: string) =>
    state.setTerminals({
      sessions: [{ key: KEY, connection: listed, rdp: { phase: 'failed', code } }],
      active: KEY,
    });

  it('asks again after a refused login, past the stored password, and starts with the typed one', async () => {
    state.setSession({ settings: { mode: 'local', storePasswords: true }, session: null });
    vi.mocked(passwordState).mockResolvedValueOnce({ canStore: true, stored: true });
    vi.mocked(requestPassword).mockResolvedValueOnce({
      cancelled: false,
      updated: typed,
      password: 'new',
      remember: false,
    });
    tabEnded('auth');

    expect(await reconnectRdpTab(KEY)).toBe(true);

    expect(requestPassword).toHaveBeenCalledWith(listed, true, true);
    expect(savePassword).not.toHaveBeenCalled();
    expect(reconnectRdp).toHaveBeenCalledWith(KEY, { connection: typed, password: 'new' });
  });

  it('saves a remembered password and starts with the stored one', async () => {
    state.setSession({ settings: { mode: 'local', storePasswords: true }, session: null });
    vi.mocked(requestPassword).mockResolvedValueOnce({
      cancelled: false,
      updated: typed,
      password: 'new',
      remember: true,
    });
    tabEnded('auth');

    expect(await reconnectRdpTab(KEY)).toBe(true);

    expect(savePassword).toHaveBeenCalledWith(typed, 'new');
    expect(reconnectRdp).toHaveBeenCalledWith(KEY, { connection: typed, password: undefined });
  });

  it('starts nothing when the prompt is cancelled', async () => {
    vi.mocked(requestPassword).mockResolvedValueOnce({ cancelled: true });
    tabEnded('auth');

    expect(await reconnectRdpTab(KEY)).toBe(false);

    expect(reconnectRdp).not.toHaveBeenCalled();
  });

  it('starts with the login the tab has when the session did not end on a refused login', async () => {
    tabEnded('network');

    expect(await reconnectRdpTab(KEY)).toBe(true);

    expect(requestPassword).not.toHaveBeenCalled();
    expect(reconnectRdp).toHaveBeenCalledWith(KEY);
  });

  it('asks nothing in a detached window, which shows no prompt', async () => {
    state.setTerminals({
      sessions: [
        { key: KEY, connection: listed, detached: true, rdp: { phase: 'failed', code: 'auth' } },
      ],
      active: KEY,
    });

    expect(await reconnectRdpTab(KEY)).toBe(true);

    expect(requestPassword).not.toHaveBeenCalled();
    expect(reconnectRdp).toHaveBeenCalledWith(KEY);
  });
});
