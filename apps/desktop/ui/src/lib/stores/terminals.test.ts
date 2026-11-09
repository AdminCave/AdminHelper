// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The sessions of the embedded terminal (R-1069) over a mocked bridge: the status follows the
// program (connecting, connected with its first output, disconnected with its exit code), output
// waits for the terminal, a reconnect resolves anew in the same tab and no longer hears the
// program it replaced, closing ends what still runs, and what is typed reaches the program in
// order, what came before the start answered once it has. A session detached into its own
// window (R-1070) keeps its tab and hears nothing more here; docked, it attaches anew, the
// terminal gets the kept output first and what it answers to that goes nowhere. The SSH tabs of
// a run are kept for the next (R-1070): opened again only when chosen, saved only once the
// connections are there, and not wiped by the logout. An RDP tab (R-1098) follows the phases of
// its own session, also one that came before the start answered, and closing, a reconnect, a new
// profile or a pinned certificate end the session it had. Detached (R-1101), its window logs in
// at the session anew and the tab lets go of it; docked or closed there, the tab logs in again.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import type { TerminalMessage } from '$lib/bridge';
import { IpcError } from '$lib/utils/errors';
import type {
  Connection,
  RdpPhaseEvent,
  RdpStarted,
  Settings,
  TunnelMapping,
} from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  terminalOpenSsh: vi.fn(),
  terminalOpenAnsible: vi.fn(async (..._a: unknown[]) => 99),
  terminalClose: vi.fn(async () => {}),
  terminalCloseAll: vi.fn(async () => {}),
  terminalWrite: vi.fn(async () => {}),
  terminalBroadcast: vi.fn(async (_data: Uint8Array) => 2),
  terminalSetBroadcast: vi.fn(async (_on: boolean) => {}),
  terminalBroadcastState: vi.fn(async () => false),
  terminalResize: vi.fn(async () => {}),
  resolveConnection: vi.fn(async (connection: unknown) => ({ connection })),
  terminalAttach: vi.fn(),
  terminalDetach: vi.fn(async () => {}),
  terminalDock: vi.fn(async () => {}),
  rdpSessionStart: vi.fn(),
  rdpSessionStop: vi.fn(async (_id: string) => {}),
  rdpTrustCertificate: vi.fn(async (_identity: string, _fingerprint: string) => {}),
  rdpSessionAttach: vi.fn(),
  rdpDetach: vi.fn(async (_id: string, _title: string, _screen?: number) => {}),
  rdpDock: vi.fn(async (_id: string) => {}),
  listeners: new Map<string, (e: { payload: { id: number } }) => void>(),
  reportError: vi.fn(),
  mappings: [] as unknown[],
}));

vi.mock('$lib/bridge', () => ({
  terminalOpenSsh: h.terminalOpenSsh,
  terminalOpenAnsible: h.terminalOpenAnsible,
  terminalClose: h.terminalClose,
  terminalCloseAll: h.terminalCloseAll,
  terminalWrite: h.terminalWrite,
  terminalBroadcast: h.terminalBroadcast,
  terminalSetBroadcast: h.terminalSetBroadcast,
  terminalBroadcastState: h.terminalBroadcastState,
  terminalResize: h.terminalResize,
  resolveConnection: h.resolveConnection,
  terminalAttach: h.terminalAttach,
  terminalDetach: h.terminalDetach,
  terminalDock: h.terminalDock,
  rdpSessionStart: h.rdpSessionStart,
  rdpSessionStop: h.rdpSessionStop,
  rdpTrustCertificate: h.rdpTrustCertificate,
  rdpSessionAttach: h.rdpSessionAttach,
  rdpDetach: h.rdpDetach,
  rdpDock: h.rdpDock,
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async (name: string, handler: (e: { payload: { id: number } }) => void) => {
    h.listeners.set(name, handler);
    // A later listener of the same name replaced this one: its unlisten leaves that one.
    return () => {
      if (h.listeners.get(name) === handler) h.listeners.delete(name);
    };
  }),
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError }));
vi.mock('./tunnel', () => ({ getMappings: () => h.mappings }));

import {
  PAGE_TAB,
  attachTerminal,
  closeAllTerminals,
  closeRdpMonitor,
  adoptRdp,
  adoptTerminal,
  closeTerminal,
  detachedRdpRoute,
  detachedRoute,
  detachTerminal,
  disconnectRdp,
  keepOpenSessions,
  listenForDocking,
  openAnsible,
  openRdp,
  openRdpMonitor,
  openSessionIds,
  openTerminal,
  reconnectRdp,
  reconnectTerminal,
  resizeTerminal,
  runSnippet,
  setRdpDisplay,
  setRdpPerformance,
  setRdpScaling,
  setRdpWindow,
  setSnippetBroadcast,
  showTab,
  snippetBroadcast,
  terminals,
  trustRdpCertificate,
  writeTerminal,
  type TerminalSession,
} from './terminals';

const CONN = {
  id: 'c1',
  name: 'db',
  kind: 'ssh',
  host: 'db',
  port: 22,
  username: 'ops',
} as Connection;
const RESOLVED = { ...CONN, host: '127.0.0.1', port: 6000 } as Connection;
const MOVED = { ...CONN, host: '127.0.0.1', port: 6001 } as Connection;
const MAPPING = { id: 'm1', protocol: 'ssh', visitorPort: 6001 } as TunnelMapping;

// One program per start: what it was started for and its channel.
interface Program {
  connection: Connection;
  cols: number;
  rows: number;
  send: (message: TerminalMessage) => void;
}
let programs: Program[];

function record(connection: Connection, cols: number, rows: number, send: Program['send']): void {
  programs.push({ connection, cols, rows, send });
}

/** The next start answers only once `started` is called with the id of its session. */
function startLater(): (id: number) => void {
  let started!: (id: number) => void;
  h.terminalOpenSsh.mockImplementationOnce(
    (connection: Connection, cols: number, rows: number, send: Program['send']) => {
      record(connection, cols, rows, send);
      return new Promise<number>((resolve) => {
        started = resolve;
      });
    },
  );
  return (id) => started(id);
}

const bytes = (text: string) => Uint8Array.from(text, (c) => c.charCodeAt(0));
const out = (text: string) => bytes(text).buffer as ArrayBuffer;
const text = (data: Uint8Array) => String.fromCharCode(...data);
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function only(): TerminalSession {
  const { sessions } = get(terminals);
  expect(sessions).toHaveLength(1);
  return sessions[0];
}

beforeEach(async () => {
  vi.clearAllMocks();
  programs = [];
  h.mappings = [];
  // Session n of a test is id n in Rust.
  h.terminalOpenSsh.mockImplementation(
    async (connection: Connection, cols: number, rows: number, send: Program['send']) => {
      record(connection, cols, rows, send);
      return programs.length;
    },
  );
  await closeAllTerminals();
  h.terminalCloseAll.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('a session follows its program (R-1069)', () => {
  it('opens in a tab in front, connects with the first output and ends with the exit code', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-05T10:00:00Z'));
    expect(await openTerminal(CONN, RESOLVED)).toBe(true);
    expect(h.terminalOpenSsh).toHaveBeenCalledWith(RESOLVED, 80, 24, expect.any(Function));
    const { key } = only();
    expect(only()).toMatchObject({
      connection: CONN,
      resolved: RESOLVED,
      status: 'connecting',
      exitCode: null,
      connectedAt: null,
      backendId: 1,
    });
    expect(get(terminals).active).toBe(key);

    programs[0].send(out('ops@db password: '));
    expect(only()).toMatchObject({
      status: 'connected',
      connectedAt: Date.parse('2026-11-05T10:00:00Z'),
    });
    programs[0].send({ exitCode: 255 });
    expect(only()).toMatchObject({ status: 'disconnected', exitCode: 255 });
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('keeps output that comes before the start has answered', async () => {
    const started = startLater();
    const opening = openTerminal(CONN, RESOLVED);
    programs[0].send(out('banner'));
    expect(only()).toMatchObject({ status: 'connected', backendId: null });
    started(1);
    expect(await opening).toBe(true);
    expect(only()).toMatchObject({ status: 'connected', backendId: 1 });
  });

  it('a program that does not start leaves its tab disconnected and the status bar says why', async () => {
    h.terminalOpenSsh.mockRejectedValueOnce(new Error('ssh not found in PATH'));
    expect(await openTerminal(CONN, RESOLVED)).toBe(false);
    expect(only()).toMatchObject({ status: 'disconnected', backendId: null });
    expect(h.reportError).toHaveBeenCalledWith('ssh not found in PATH');
  });
});

describe('output waits for the terminal (R-1069)', () => {
  it('hands what came before to the terminal in order, then the rest as it comes', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    programs[0].send(out('a'));
    programs[0].send(out('b'));
    const seen: string[] = [];
    const detach = attachTerminal(key, (data) => seen.push(text(data)));
    expect(seen).toEqual(['a', 'b']);
    programs[0].send(out('c'));
    expect(seen).toEqual(['a', 'b', 'c']);

    // Detached, output waits again for the next terminal.
    detach();
    programs[0].send(out('d'));
    expect(seen).toEqual(['a', 'b', 'c']);
    attachTerminal(key, (data) => seen.push(text(data)));
    expect(seen).toEqual(['a', 'b', 'c', 'd']);
  });
});

describe('reconnect (R-1069)', () => {
  it('resolves the connection anew and starts a new program in the same tab with the last size', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    programs[0].send(out('x'));
    programs[0].send({ exitCode: 0 });
    resizeTerminal(key, 120, 40);
    expect(h.terminalResize).not.toHaveBeenCalled();

    h.mappings = [MAPPING];
    h.resolveConnection.mockResolvedValueOnce({ connection: MOVED });
    expect(await reconnectTerminal(key)).toBe(true);
    expect(h.resolveConnection).toHaveBeenCalledWith(CONN, [MAPPING]);
    expect(h.terminalOpenSsh).toHaveBeenLastCalledWith(MOVED, 120, 40, expect.any(Function));
    expect(only()).toMatchObject({
      key,
      connection: CONN,
      resolved: MOVED,
      status: 'connecting',
      exitCode: null,
      connectedAt: null,
      backendId: 2,
    });
    expect(get(terminals).active).toBe(key);
    // The first program had ended: nothing to close.
    expect(h.terminalClose).not.toHaveBeenCalled();
    programs[1].send(out('y'));
    expect(only().status).toBe('connected');
  });

  it('of a running session ends its program, which is not heard any more', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    const seen: string[] = [];
    attachTerminal(key, (data) => seen.push(text(data)));
    programs[0].send(out('old'));

    await reconnectTerminal(key);
    expect(h.terminalClose).toHaveBeenCalledWith(1);
    programs[0].send(out('late'));
    programs[0].send({ exitCode: 143 });
    expect(only()).toMatchObject({ status: 'connecting', exitCode: null, backendId: 2 });
    programs[1].send(out('new'));
    expect(seen).toEqual(['old', 'new']);
  });

  it('a refused resolution leaves the session disconnected and the status bar says why', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    programs[0].send({ exitCode: 0 });
    const refusal = 'port 6001 on this machine belongs to the tunnel of another workspace';
    h.resolveConnection.mockRejectedValueOnce(new Error(refusal));
    expect(await reconnectTerminal(key)).toBe(false);
    expect(only()).toMatchObject({ status: 'disconnected' });
    expect(h.reportError).toHaveBeenCalledWith(refusal);
    expect(h.terminalOpenSsh).toHaveBeenCalledTimes(1);
  });
});

describe('closing (R-1069)', () => {
  it('ends a running program; the tab before the closed one comes to the front', async () => {
    await openTerminal(CONN, RESOLVED);
    await openTerminal(CONN, RESOLVED);
    await openTerminal(CONN, RESOLVED);
    const [first, second, third] = get(terminals).sessions.map((s) => s.key);
    expect(get(terminals).active).toBe(third);

    showTab(second);
    closeTerminal(second);
    expect(h.terminalClose).toHaveBeenCalledWith(2);
    expect(get(terminals)).toMatchObject({ active: first });
    expect(get(terminals).sessions.map((s) => s.key)).toEqual([first, third]);

    // The first session is the leftmost: before it comes the page.
    closeTerminal(first);
    expect(get(terminals).active).toBe(PAGE_TAB);
    // A tab not in front leaves the front as it is.
    showTab(third);
    showTab(PAGE_TAB);
    closeTerminal(third);
    expect(get(terminals)).toEqual({ sessions: [], active: PAGE_TAB });
  });

  it('a disconnected session closes without ending anything', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    programs[0].send({ exitCode: 1 });
    closeTerminal(key);
    expect(get(terminals).sessions).toEqual([]);
    expect(h.terminalClose).not.toHaveBeenCalled();
  });

  it('a tab closed while its program starts ends the program once it has started', async () => {
    const started = startLater();
    const opening = openTerminal(CONN, RESOLVED);
    closeTerminal(only().key);
    expect(get(terminals).sessions).toEqual([]);
    expect(h.terminalClose).not.toHaveBeenCalled();
    started(7);
    await opening;
    expect(h.terminalClose).toHaveBeenCalledWith(7);
    programs[0].send(out('x'));
    expect(get(terminals).sessions).toEqual([]);
  });

  it('closeAllTerminals ends every program of the window and leaves the page in front', async () => {
    await openTerminal(CONN, RESOLVED);
    await openTerminal(CONN, RESOLVED);
    await closeAllTerminals();
    expect(h.terminalCloseAll).toHaveBeenCalledOnce();
    expect(get(terminals)).toEqual({ sessions: [], active: PAGE_TAB });
    programs[0].send(out('x'));
    programs[1].send({ exitCode: 0 });
    expect(get(terminals).sessions).toEqual([]);
  });
});

describe('tabs (R-1069)', () => {
  it('showTab brings a session or the page to the front, not a key no session has', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    showTab(PAGE_TAB);
    expect(get(terminals).active).toBe(PAGE_TAB);
    showTab('terminal-unknown');
    expect(get(terminals).active).toBe(PAGE_TAB);
    showTab(key);
    expect(get(terminals).active).toBe(key);
  });
});

describe('input and size (R-1069)', () => {
  it('what is typed reaches the program in the order typed, one write after the other', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    let release!: () => void;
    h.terminalWrite.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    writeTerminal(key, bytes('a'));
    writeTerminal(key, bytes('b'));
    await settle();
    expect(h.terminalWrite).toHaveBeenCalledTimes(1);
    expect(h.terminalWrite).toHaveBeenCalledWith(1, bytes('a'));
    release();
    await settle();
    expect(h.terminalWrite).toHaveBeenCalledTimes(2);
    expect(h.terminalWrite).toHaveBeenLastCalledWith(1, bytes('b'));

    // A refused write does not hold up the next.
    h.terminalWrite.mockRejectedValueOnce(new Error('the terminal session has ended'));
    writeTerminal(key, bytes('c'));
    writeTerminal(key, bytes('d'));
    await settle();
    expect(h.terminalWrite).toHaveBeenLastCalledWith(1, bytes('d'));
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('what is typed before the start answers reaches the program once it has, in order', async () => {
    const started = startLater();
    const opening = openTerminal(CONN, RESOLVED);
    const { key } = only();
    // The Windows pseudo console asks for the cursor before the start has answered.
    programs[0].send(out('\x1b[6n'));
    writeTerminal(key, bytes('\x1b[1;1R'));
    writeTerminal(key, bytes('a'));
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();

    started(1);
    await opening;
    writeTerminal(key, bytes('b'));
    await settle();
    expect(h.terminalWrite.mock.calls).toEqual([
      [1, bytes('\x1b[1;1R')],
      [1, bytes('a')],
      [1, bytes('b')],
    ]);
  });

  it('what is typed while a reconnect starts reaches the new program, not the one it replaced', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    const started = startLater();
    const reconnecting = reconnectTerminal(key);
    writeTerminal(key, bytes('x'));
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();

    started(2);
    await reconnecting;
    await settle();
    expect(h.terminalWrite.mock.calls).toEqual([[2, bytes('x')]]);
  });

  it('what is typed before a start that fails goes nowhere, a later start among it', async () => {
    let fail!: (err: Error) => void;
    h.terminalOpenSsh.mockImplementationOnce(
      () =>
        new Promise<number>((_, reject) => {
          fail = reject;
        }),
    );
    const opening = openTerminal(CONN, RESOLVED);
    const { key } = only();
    writeTerminal(key, bytes('a'));
    fail(new Error('ssh not found in PATH'));
    expect(await opening).toBe(false);
    writeTerminal(key, bytes('b'));

    expect(await reconnectTerminal(key)).toBe(true);
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();
  });

  it('a write waiting behind another does not reach the program a reconnect started', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    let release!: () => void;
    h.terminalWrite.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    writeTerminal(key, bytes('a'));
    writeTerminal(key, bytes('b'));
    await settle();
    await reconnectTerminal(key);
    release();
    await settle();
    expect(h.terminalWrite.mock.calls).toEqual([[1, bytes('a')]]);
  });

  it('nothing is written to or resized for a program that has ended', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    programs[0].send({ exitCode: 0 });
    writeTerminal(key, bytes('a'));
    resizeTerminal(key, 100, 30);
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();
    expect(h.terminalResize).not.toHaveBeenCalled();
  });

  it('a size measured while the program starts reaches it once it has started', async () => {
    const started = startLater();
    const opening = openTerminal(CONN, RESOLVED);
    const { key } = only();
    resizeTerminal(key, 132, 43);
    expect(h.terminalResize).not.toHaveBeenCalled();
    started(1);
    await opening;
    expect(h.terminalResize).toHaveBeenCalledWith(1, 132, 43);
    // A running program gets a new size right away.
    resizeTerminal(key, 100, 30);
    expect(h.terminalResize).toHaveBeenLastCalledWith(1, 100, 30);
  });
});

describe('detach and dock (R-1070)', () => {
  // The channels of terminalAttach, in the order attached.
  let attached: Program['send'][];

  beforeEach(() => {
    attached = [];
    h.terminalAttach.mockImplementation(async (_id: number, send: Program['send']) => {
      attached.push(send);
    });
  });

  async function detached(): Promise<string> {
    await openTerminal(CONN, RESOLVED);
    programs[0].send(out('$ '));
    const { key } = only();
    await detachTerminal(key);
    return key;
  }

  function event(name: string, id: number): void {
    h.listeners.get(name)!({ payload: { id } });
  }

  it('moves a running session into its window; the tab stays, leaves the front and hears nothing more', async () => {
    const key = await detached();
    expect(h.terminalDetach).toHaveBeenCalledWith(1, 'db');
    expect(only()).toMatchObject({ key, detached: true, status: 'connected' });
    expect(get(terminals).active).toBe(PAGE_TAB);

    // What this window's channel still brings, and what is typed here, go nowhere.
    programs[0].send(out('late'));
    const got: string[] = [];
    attachTerminal(key, (data) => got.push(text(data)));
    writeTerminal(key, bytes('a'));
    await settle();
    expect(got).toEqual([]);
    expect(h.terminalWrite).not.toHaveBeenCalled();

    // Detached already: its window comes to the front, nothing else changes.
    await detachTerminal(key);
    expect(h.terminalDetach).toHaveBeenCalledTimes(2);
    expect(only()).toMatchObject({ detached: true });
  });

  it('detaches nothing that does not run, and stays when the window could not open', async () => {
    const started = startLater();
    void openTerminal(CONN, RESOLVED);
    await detachTerminal(only().key);
    expect(h.terminalDetach).not.toHaveBeenCalled();
    started(1);
    await settle();

    h.terminalDetach.mockRejectedValueOnce(new Error('no window'));
    await detachTerminal(only().key);
    expect(only().detached).toBeFalsy();
    expect(h.reportError).toHaveBeenCalledWith('no window');
    expect(get(terminals).active).toBe(only().key);

    programs[0].send({ exitCode: 0 });
    h.terminalDetach.mockClear();
    await detachTerminal(only().key);
    expect(h.terminalDetach).not.toHaveBeenCalled();
  });

  it('docks on terminal-docked: the tab comes to the front, the kept output first, then the live one', async () => {
    const stop = await listenForDocking();
    const key = await detached();
    event('terminal-docked', 1);
    await settle();
    expect(h.terminalAttach).toHaveBeenCalledWith(1, expect.any(Function));
    expect(only()).toMatchObject({ detached: false });
    expect(get(terminals).active).toBe(key);

    // Replay before the new terminal attached; the end of it waits in order.
    attached[0](out('$ ls\r\n'));
    attached[0](out('\x1b[6n'));
    attached[0]({ replayed: true });
    attached[0](out('live'));
    const got: string[] = [];
    let parsed: (() => void) | undefined;
    attachTerminal(key, (data, done) => {
      got.push(text(data));
      if (done) parsed = done;
    });
    expect(got).toEqual(['$ ls\r\n', '\x1b[6n', '', 'live']);

    // What the terminal answers while it works through the replay goes nowhere; after it, all.
    writeTerminal(key, bytes('\x1b[1;1R'));
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();
    parsed!();
    writeTerminal(key, bytes('a'));
    await settle();
    expect(h.terminalWrite.mock.calls).toEqual([[1, bytes('a')]]);

    // The channel of the window before is not heard any more, the new one is.
    programs[0].send(out('old'));
    attached[0](out('new'));
    expect(got.slice(4)).toEqual(['new']);
    stop();
    expect(h.listeners.size).toBe(0);
  });

  it('docks when the window is closed from its title bar, once, and not a session never detached', async () => {
    await listenForDocking();
    await openTerminal(CONN, RESOLVED);
    programs[0].send(out('$ '));
    const { key } = only();
    event('terminal-window-closed', 1);
    await settle();
    expect(h.terminalAttach).not.toHaveBeenCalled();
    expect(h.terminalClose).not.toHaveBeenCalled();

    await detachTerminal(key);
    const got: string[] = [];
    attachTerminal(key, (data, done) => {
      got.push(text(data));
      done?.();
    });
    event('terminal-window-closed', 1);
    event('terminal-docked', 1);
    await settle();
    expect(h.terminalAttach).toHaveBeenCalledTimes(1);
    // The second event finds the tab docked: it ends nothing.
    expect(h.terminalClose).not.toHaveBeenCalled();
    attached[0]({ replayed: true });
    expect(got).toEqual(['']);
    writeTerminal(key, bytes('a'));
    await settle();
    expect(h.terminalWrite).toHaveBeenCalledWith(1, bytes('a'));
  });

  it('a session that ended in its window shows disconnected once docked', async () => {
    await listenForDocking();
    await detached();
    h.terminalAttach.mockRejectedValueOnce(new Error('no terminal session 1'));
    event('terminal-docked', 1);
    await settle();
    expect(only()).toMatchObject({ detached: false, status: 'disconnected' });
    expect(h.reportError).toHaveBeenCalledWith('no terminal session 1');
  });

  it('closing a detached tab ends its program and closes its window', async () => {
    const key = await detached();
    closeTerminal(key);
    await settle();
    expect(h.terminalClose).toHaveBeenCalledWith(1);
    expect(h.terminalDock).toHaveBeenCalledWith(1);
    expect(get(terminals).sessions).toEqual([]);

    // Its window docks after it: nothing to take back, and nothing to report.
    await listenForDocking();
    event('terminal-docked', 1);
    await settle();
    expect(h.terminalAttach).not.toHaveBeenCalled();
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('ends a session docked that no tab knows: detached before this window loaded again', async () => {
    await listenForDocking();
    h.terminalClose.mockRejectedValueOnce(new Error('no terminal session 7'));
    event('terminal-window-closed', 7);
    await settle();
    expect(h.terminalClose).toHaveBeenCalledExactlyOnceWith(7);
    expect(h.terminalAttach).not.toHaveBeenCalled();
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('a detached window takes its session as the only one: replay, then live, then the exit', async () => {
    await openTerminal(CONN, RESOLVED);
    const key = adoptTerminal(5);
    expect(get(terminals)).toEqual({ sessions: [only()], active: key });
    expect(only()).toMatchObject({ key, backendId: 5, status: 'connected', connectedAt: null });
    expect(h.terminalAttach).toHaveBeenCalledExactlyOnceWith(5, expect.any(Function));

    await settle();
    attached[0](out('kept'));
    attached[0]({ replayed: true });
    const got: string[] = [];
    let parsed: (() => void) | undefined;
    attachTerminal(key, (data, done) => {
      got.push(text(data));
      if (done) parsed = done;
    });
    writeTerminal(key, bytes('\x1b[1;1R'));
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();
    parsed!();
    attached[0](out('live'));
    writeTerminal(key, bytes('a'));
    resizeTerminal(key, 100, 30);
    await settle();
    expect(got).toEqual(['kept', '', 'live']);
    expect(h.terminalWrite.mock.calls).toEqual([[5, bytes('a')]]);
    expect(h.terminalResize).toHaveBeenCalledWith(5, 100, 30);
    // Its output since it was opened here is no new connection.
    expect(only().connectedAt).toBeNull();

    attached[0]({ exitCode: 0 });
    expect(only()).toMatchObject({ status: 'disconnected', exitCode: 0 });
  });

  it('reads the session of a detached window from its route', () => {
    expect(detachedRoute('#/detached/12')).toBe(12);
    for (const hash of ['', '#/connections', '#/detached/', '#/detached/+1', '#/detached/1x']) {
      expect(detachedRoute(hash)).toBeNull();
    }
  });
});

describe('keeping the SSH tabs for the next run (R-1070)', () => {
  const C2 = { ...CONN, id: 'c2', name: 'web' } as Connection;
  const RDP = { ...CONN, id: 'r1', kind: 'rdp' } as Connection;

  let settings: ReturnType<typeof writable<Settings | null>>;
  let list: ReturnType<typeof writable<{ items: Connection[]; loading: boolean }>>;
  let save: ReturnType<typeof vi.fn<(ids: string[]) => Promise<void>>>;
  let connect: ReturnType<typeof vi.fn<(c: Connection) => Promise<void>>>;
  let stop: (() => void) | null;

  function keep(restoreSessions: boolean | undefined, openSessions: string[] | undefined) {
    settings = writable({ restoreSessions, openSessions } as Settings);
    stop = keepOpenSessions({ settings, connections: list, save, connect });
  }

  beforeEach(() => {
    list = writable({ items: [], loading: true });
    save = vi.fn(async () => {});
    // A click on connect, as initiateConnect opens an embedded SSH tab.
    connect = vi.fn(async (c: Connection) => {
      await openTerminal(c, c);
    });
    stop = null;
  });

  afterEach(() => stop?.());

  it('opens the saved tabs in their order once the connections are there, a gone one passed over', async () => {
    keep(true, ['c2', 'gone', 'c1', 'c2', 'r1']);
    await settle();
    expect(connect).not.toHaveBeenCalled();

    list.set({ items: [CONN, C2, RDP], loading: false });
    await settle();
    expect(connect.mock.calls.map(([c]) => c.id)).toEqual(['c2', 'c1']);
    expect(get(terminals).sessions.map((s) => s.connection.id)).toEqual(['c2', 'c1']);
    // What was opened again is what was saved, minus what is gone: nothing new to save.
    expect(save).toHaveBeenCalledExactlyOnceWith(['c2', 'c1']);
  });

  it('opens nothing unless chosen, and saves the tabs of this run as they change', async () => {
    keep(undefined, ['c1']);
    list.set({ items: [CONN, C2], loading: false });
    await settle();
    expect(connect).not.toHaveBeenCalled();
    expect(save).toHaveBeenCalledExactlyOnceWith([]);

    await openTerminal(C2, C2);
    await openTerminal(CONN, CONN);
    await openTerminal(C2, C2);
    await settle();
    expect(save.mock.calls.map(([ids]) => ids)).toEqual([[], ['c2'], ['c2', 'c1']]);

    closeTerminal(get(terminals).sessions[0].key);
    await settle();
    expect(save).toHaveBeenLastCalledWith(['c1', 'c2']);
  });

  it('saves nothing while the connections load or did not load', async () => {
    keep(true, ['c1']);
    await openTerminal(C2, C2);
    list.set({ items: [], loading: false });
    await settle();
    expect(save).not.toHaveBeenCalled();
    expect(connect).not.toHaveBeenCalled();
  });

  it('keeps the list through the logout, and stops when told to', async () => {
    keep(true, []);
    list.set({ items: [CONN], loading: false });
    await settle();
    await openTerminal(CONN, CONN);
    await settle();
    expect(save).toHaveBeenLastCalledWith(['c1']);

    await closeAllTerminals();
    await openTerminal(CONN, CONN);
    await settle();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('reports a save that failed and saves the next change', async () => {
    keep(false, []);
    list.set({ items: [CONN, C2], loading: false });
    save.mockRejectedValueOnce(new Error('disk full'));
    await openTerminal(CONN, CONN);
    await settle();
    expect(h.reportError).toHaveBeenCalledWith('disk full');
    await openTerminal(C2, C2);
    await settle();
    expect(save).toHaveBeenLastCalledWith(['c1', 'c2']);
  });

  it('lists each SSH connection with a tab once, in tab order', () => {
    const tab = (connection: Connection) => ({ connection }) as TerminalSession;
    expect(
      openSessionIds([tab(C2), tab(RDP), tab(CONN), tab(C2), tab({ ...CONN, id: '' })]),
    ).toEqual(['c2', 'c1']);
  });
});

describe('snippets (R-1071)', () => {
  // As the store encodes: a Uint8Array of this realm.
  const encoded = (text: string) => new TextEncoder().encode(text);
  // What Rust reports to every window.
  const report = (on: boolean) =>
    (h.listeners.get('terminal-broadcast') as unknown as (e: { payload: boolean }) => void)({
      payload: on,
    });
  let unsubscribe: (() => void) | null = null;
  /** A window that shows the store, as the foot of a session does. */
  async function watch(): Promise<() => boolean> {
    let now = false;
    unsubscribe = snippetBroadcast.subscribe((on) => (now = on));
    await settle();
    return () => now;
  }

  afterEach(() => {
    unsubscribe?.();
    unsubscribe = null;
  });

  it('a window starts with the state Rust holds and then follows it', async () => {
    h.terminalBroadcastState.mockResolvedValueOnce(true);
    const now = await watch();
    expect(now()).toBe(true);
    report(false);
    expect(now()).toBe(false);
    report(true);
    expect(now()).toBe(true);
    unsubscribe?.();
    unsubscribe = null;
    expect(h.listeners.has('terminal-broadcast')).toBe(false);
  });

  it('a report heard before the answer is newer than it', async () => {
    let answer!: (on: boolean) => void;
    h.terminalBroadcastState.mockImplementationOnce(
      () => new Promise<boolean>((resolve) => (answer = resolve)),
    );
    const now = await watch();
    report(true);
    answer(false);
    await settle();
    expect(now()).toBe(true);
  });

  it('switches the broadcast through Rust and reports a refusal', async () => {
    await setSnippetBroadcast(true);
    expect(h.terminalSetBroadcast).toHaveBeenCalledWith(true);
    h.terminalSetBroadcast.mockRejectedValueOnce(
      new Error('only the main window switches the broadcast'),
    );
    await setSnippetBroadcast(false);
    expect(h.reportError).toHaveBeenCalledWith('only the main window switches the broadcast');
  });

  it('a snippet goes to its session line by line, each with Enter', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    await runSnippet(key, 'cd /tmp\nls -la\n\n');
    await settle();
    expect(h.terminalWrite).toHaveBeenCalledTimes(1);
    expect(h.terminalWrite).toHaveBeenCalledWith(1, encoded('cd /tmp\rls -la\r'));
    expect(h.terminalBroadcast).not.toHaveBeenCalled();
  });

  it('with the broadcast on it goes to Rust for every session, not to its own', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    await watch();
    report(true);
    await runSnippet(key, 'uptime');
    await settle();
    expect(h.terminalBroadcast).toHaveBeenCalledTimes(1);
    expect(h.terminalBroadcast).toHaveBeenCalledWith(encoded('uptime\r'));
    expect(h.terminalWrite).not.toHaveBeenCalled();

    h.terminalBroadcast.mockRejectedValueOnce(new Error('only the main window broadcasts'));
    await runSnippet(key, 'uptime');
    expect(h.reportError).toHaveBeenCalledWith('only the main window broadcasts');
  });

  it('a snippet reaches no session that has ended', async () => {
    await openTerminal(CONN, RESOLVED);
    const { key } = only();
    programs[0].send({ exitCode: 0 });
    await settle();
    expect(only().status).toBe('disconnected');
    await runSnippet(key, 'uptime');
    await settle();
    expect(h.terminalWrite).not.toHaveBeenCalled();
  });
});

describe('a playbook in a tab (R-1073)', () => {
  const TARGETS = [{ hostname: 'web.lan', groups: ['web'] }];

  it('opens a tab named after the playbook and starts the run with its dry run', async () => {
    expect(await openAnsible('pb1', 'Deploy', TARGETS, true)).toBe(true);
    const s = only();
    expect(s.connection.name).toBe('Deploy');
    expect(s.ansible).toEqual({ check: true });
    expect(s.backendId).toBe(99);
    expect(get(terminals).active).toBe(s.key);
    expect(h.terminalOpenAnsible).toHaveBeenCalledExactlyOnceWith(
      'pb1',
      TARGETS,
      true,
      80,
      24,
      expect.any(Function),
    );
    expect(h.terminalOpenSsh).not.toHaveBeenCalled();
  });

  it('is neither reconnected nor kept for the next run', async () => {
    await openAnsible('pb1', 'Deploy', TARGETS, false);
    const s = only();
    expect(await reconnectTerminal(s.key)).toBe(false);
    expect(h.terminalOpenAnsible).toHaveBeenCalledTimes(1);
    expect(h.terminalClose).not.toHaveBeenCalled();
    expect(openSessionIds([s, { ...s, ansible: undefined, connection: CONN }])).toEqual(['c1']);
  });
});

describe('an RDP session in a tab (R-1098)', () => {
  const RDP = { ...CONN, id: 'r1', kind: 'rdp', host: 'win', port: 3389 } as Connection;
  let started: number;

  const phase = (event: RdpPhaseEvent) =>
    (h.listeners.get('rdp-session') as unknown as (e: { payload: RdpPhaseEvent }) => void)({
      payload: event,
    });
  const rdp = () => only().rdp!;

  beforeEach(() => {
    started = 0;
    h.rdpSessionStart.mockImplementation(async () => {
      started += 1;
      return { session_id: `s${started}`, ws_port: 7000 + started, token: `t${started}` };
    });
  });

  it('opens in a tab in front and follows the phases of its own session only', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-08T10:00:00Z'));
    expect(await openRdp(RDP)).toBe('started');
    expect(h.rdpSessionStart).toHaveBeenCalledWith(RDP, undefined, undefined);
    expect(get(terminals).active).toBe(only().key);
    expect(only()).toMatchObject({ status: 'connecting', connectedAt: null });
    expect(rdp()).toMatchObject({
      sessionId: 's1',
      wsPort: 7001,
      token: 't1',
      phase: 'connecting',
    });

    phase({ session_id: 'other', phase: 'connected' });
    expect(only().status).toBe('connecting');
    phase({ session_id: 's1', phase: 'connected' });
    expect(only()).toMatchObject({ status: 'connected', connectedAt: Date.now() });
    phase({ session_id: 's1', phase: 'reconnecting' });
    expect(only().status).toBe('connecting');
    phase({ session_id: 's1', phase: 'disconnected', code: 'network' });
    expect(only().status).toBe('disconnected');
    expect(rdp()).toMatchObject({
      phase: 'disconnected',
      code: 'network',
      sessionId: null,
      wsPort: null,
      token: null,
    });
    // Ended: nothing listens any more.
    expect(h.listeners.has('rdp-session')).toBe(false);
  });

  it('keeps a phase that came before the start answered and plays it after', async () => {
    let answer!: (s: RdpStarted) => void;
    h.rdpSessionStart.mockImplementationOnce(
      () => new Promise<RdpStarted>((resolve) => (answer = resolve)),
    );
    const opened = openRdp(RDP);
    await settle();
    phase({ session_id: 'old', phase: 'connected' });
    phase({ session_id: 's9', phase: 'connected' });
    answer({ session_id: 's9', ws_port: 7009, token: 't9', notice: 'drive_unavailable' });
    expect(await opened).toBe('started');
    expect(only().status).toBe('connected');
    expect(rdp()).toMatchObject({
      sessionId: 's9',
      phase: 'connected',
      notice: 'drive_unavailable',
    });
  });

  it('shows the start failing and says why', async () => {
    h.rdpSessionStart.mockRejectedValueOnce(new Error('no password'));
    expect(await openRdp(RDP)).toBe('failed');
    expect(only().status).toBe('disconnected');
    expect(rdp().phase).toBe('failed');
    expect(h.reportError).toHaveBeenCalledWith('no password');
    expect(h.listeners.has('rdp-session')).toBe(false);
  });

  it('ends the session when its tab closes, and every session on closing all', async () => {
    await openRdp(RDP);
    closeTerminal(only().key);
    expect(h.rdpSessionStop).toHaveBeenCalledWith('s1');
    expect(get(terminals).sessions).toEqual([]);
    expect(h.listeners.has('rdp-session')).toBe(false);

    await openRdp(RDP);
    await openRdp(RDP);
    await closeAllTerminals();
    expect(h.rdpSessionStop.mock.calls.map((c) => c[0])).toEqual(['s1', 's2', 's3']);
  });

  it('stops a session whose tab closed while it started', async () => {
    let answer!: (s: RdpStarted) => void;
    h.rdpSessionStart.mockImplementationOnce(
      () => new Promise<RdpStarted>((resolve) => (answer = resolve)),
    );
    const opened = openRdp(RDP);
    await settle();
    closeTerminal(only().key);
    answer({ session_id: 's7', ws_port: 7007, token: 't7' });
    await opened;
    expect(h.rdpSessionStop).toHaveBeenCalledWith('s7');
  });

  it('disconnects and keeps the tab, reconnects with a new session', async () => {
    await openRdp(RDP);
    const { key } = only();
    disconnectRdp(key);
    expect(h.rdpSessionStop).toHaveBeenCalledWith('s1');
    phase({ session_id: 's1', phase: 'disconnected', code: 'closed' });
    expect(only().key).toBe(key);
    expect(rdp().code).toBe('closed');

    expect(await reconnectRdp(key)).toBe(true);
    expect(rdp()).toMatchObject({ sessionId: 's2', phase: 'connecting', code: null });
    phase({ session_id: 's1', phase: 'connected' });
    expect(only().status).toBe('connecting');
  });

  it('starts anew with the profile chosen for this tab only', async () => {
    await openRdp(RDP);
    expect(await setRdpPerformance(only().key, 'low')).toBe(true);
    expect(h.rdpSessionStop).toHaveBeenCalledWith('s1');
    expect(h.rdpSessionStart).toHaveBeenLastCalledWith(
      { ...RDP, options: { rdp: { performanceProfile: 'low' } } },
      undefined,
      undefined,
    );
    expect(only().connection).toBe(RDP);
    expect(rdp()).toMatchObject({ performance: 'low', sessionId: 's2' });
  });

  it('starts with the desktop the tab asked for last, and keeps the modes of this tab', async () => {
    const opened = openRdp(RDP);
    // The tab measures itself once it is there, before the start goes out.
    setRdpDisplay(only().key, { width: 1600, height: 900, scale: 100 });
    await opened;
    expect(h.rdpSessionStart).toHaveBeenLastCalledWith(RDP, undefined, {
      width: 1600,
      height: 900,
      scale: 100,
    });
    expect(rdp()).toMatchObject({ window: null, scaling: null });

    setRdpWindow(only().key, 'custom');
    setRdpScaling(only().key, 'hdpi');
    setRdpDisplay(only().key, { width: 1920, height: 1080, scale: 175 });
    expect(rdp()).toMatchObject({ window: 'custom', scaling: 'hdpi', sessionId: 's1' });
    // Neither mode starts anew: the session follows the size over its socket.
    expect(h.rdpSessionStart).toHaveBeenCalledTimes(1);
    expect(await reconnectRdp(only().key)).toBe(true);
    expect(h.rdpSessionStart).toHaveBeenLastCalledWith(RDP, undefined, {
      width: 1920,
      height: 1080,
      scale: 175,
    });
  });

  it('pins the refused certificate and starts anew; a refused pin stays', async () => {
    await openRdp(RDP);
    phase({
      session_id: 's1',
      phase: 'certificate',
      identity: 'win:3389',
      fingerprint: 'ab:cd',
      reason: 'changed',
    });
    expect(only().status).toBe('disconnected');
    expect(rdp().certificate).toEqual({
      identity: 'win:3389',
      fingerprint: 'ab:cd',
      reason: 'changed',
    });

    h.rdpTrustCertificate.mockRejectedValueOnce(new Error('keyring locked'));
    expect(await trustRdpCertificate(only().key)).toBe(false);
    expect(h.reportError).toHaveBeenCalledWith('keyring locked');
    expect(h.rdpSessionStart).toHaveBeenCalledTimes(1);

    expect(await trustRdpCertificate(only().key)).toBe(true);
    expect(h.rdpTrustCertificate).toHaveBeenLastCalledWith('win:3389', 'ab:cd');
    expect(h.rdpSessionStart).toHaveBeenCalledTimes(2);
    expect(rdp()).toMatchObject({ sessionId: 's2', certificate: null, phase: 'connecting' });
  });

  it('hands a typed password to every start of its tab', async () => {
    await openRdp(RDP, 'typed');
    expect(h.rdpSessionStart).toHaveBeenLastCalledWith(RDP, 'typed', undefined);
    expect(JSON.stringify(get(terminals))).not.toContain('typed');
    expect(await reconnectRdp(only().key)).toBe(true);
    expect(h.rdpSessionStart).toHaveBeenLastCalledWith(RDP, 'typed', undefined);
    await openRdp(RDP);
    expect(h.rdpSessionStart).toHaveBeenLastCalledWith(RDP, undefined, undefined);
  });

  it('leaves a connection only the OS client can open to it, without a tab', async () => {
    const osClient = new IpcError('cannot share printers', 'ERR_RDP_OS_CLIENT');
    h.rdpSessionStart.mockRejectedValueOnce(osClient);
    expect(await openRdp(RDP)).toBe('os-client');
    expect(get(terminals).sessions).toEqual([]);
    expect(h.reportError).not.toHaveBeenCalled();
    expect(h.listeners.has('rdp-session')).toBe(false);

    // A tab that ran already stays and says why.
    await openRdp(RDP);
    h.rdpSessionStart.mockRejectedValueOnce(osClient);
    expect(await reconnectRdp(only().key)).toBe(false);
    expect(rdp().phase).toBe('failed');
    expect(h.reportError).toHaveBeenCalledWith('cannot share printers');
  });
});

describe('detaching an RDP tab (R-1101)', () => {
  const RDP = { ...CONN, id: 'r1', kind: 'rdp', host: 'win', port: 3389 } as Connection;
  let attached: number;

  const fire = <T>(name: string, payload: T) =>
    (h.listeners.get(name) as unknown as (e: { payload: T }) => void)({ payload });
  const phase = (event: RdpPhaseEvent) => fire('rdp-session', event);
  const rdp = () => only().rdp!;

  beforeEach(() => {
    attached = 0;
    h.rdpSessionStart.mockImplementation(async () => ({
      session_id: 's1',
      ws_port: 7001,
      token: 't1',
    }));
    h.rdpSessionAttach.mockImplementation(async () => {
      attached += 1;
      return { ws_port: 7001, token: `renewed${attached}` };
    });
  });

  async function detached(): Promise<string> {
    await listenForDocking();
    await openRdp(RDP);
    phase({ session_id: 's1', phase: 'connected' });
    await detachTerminal(only().key);
    // What the tab of the test before ended as this one started.
    h.rdpSessionStop.mockClear();
    return only().key;
  }

  it('moves a connected session into its window; the tab stays, out of the front', async () => {
    await openRdp(RDP);
    // Not connected yet: nothing to show in a window.
    await detachTerminal(only().key);
    expect(h.rdpDetach).not.toHaveBeenCalled();

    phase({ session_id: 's1', phase: 'connected' });
    await detachTerminal(only().key);
    expect(h.rdpDetach).toHaveBeenCalledWith('s1', 'db');
    expect(only().detached).toBe(true);
    expect(get(terminals).active).toBe(PAGE_TAB);
    // The tab still follows its session.
    phase({ session_id: 's1', phase: 'reconnecting' });
    expect(only().status).toBe('connecting');
  });

  it('stays in its tab when the window could not open', async () => {
    h.rdpDetach.mockRejectedValueOnce(new Error('no window'));
    await openRdp(RDP);
    phase({ session_id: 's1', phase: 'connected' });
    await detachTerminal(only().key);
    expect(only().detached).toBeFalsy();
    expect(h.reportError).toHaveBeenCalledWith('no window');
  });

  it('docks on rdp-docked: logged in anew first, then in front', async () => {
    const key = await detached();
    const seen: { detached?: boolean; token: string | null }[] = [];
    const stop = terminals.subscribe((s) => {
      const tab = s.sessions[0];
      if (tab) seen.push({ detached: tab.detached, token: tab.rdp!.token });
    });
    fire('rdp-docked', { session_id: 's1' });
    await settle();
    stop();
    expect(h.rdpSessionAttach).toHaveBeenCalledWith('s1', 0);
    expect(only().detached).toBe(false);
    expect(get(terminals).active).toBe(key);
    expect(rdp()).toMatchObject({ sessionId: 's1', wsPort: 7001, token: 'renewed1' });
    // The tab's view never opened with the token its window used up.
    expect(seen.filter((x) => !x.detached && x.token === 't1')).toEqual([]);
    expect(seen.at(-1)).toEqual({ detached: false, token: 'renewed1' });
  });

  it('docks when its window is closed from the title bar, once', async () => {
    await detached();
    fire('rdp-window-closed', { session_id: 's1' });
    await settle();
    expect(only().detached).toBe(false);
    fire('rdp-window-closed', { session_id: 's1' });
    await settle();
    expect(h.rdpSessionAttach).toHaveBeenCalledOnce();
    expect(h.rdpSessionStop).not.toHaveBeenCalled();
  });

  it('a session that ended in its window shows disconnected once docked', async () => {
    await detached();
    phase({ session_id: 's1', phase: 'disconnected', code: 'network' });
    fire('rdp-docked', { session_id: 's1' });
    await settle();
    expect(h.rdpSessionAttach).not.toHaveBeenCalled();
    expect(only()).toMatchObject({ detached: false, status: 'disconnected' });
    expect(rdp()).toMatchObject({ phase: 'disconnected', token: null });
  });

  it('closing a detached tab ends its session and closes its window', async () => {
    await detached();
    closeTerminal(only().key);
    expect(h.rdpSessionStop).toHaveBeenCalledWith('s1');
    expect(h.rdpDock).toHaveBeenCalledWith('s1');
    expect(get(terminals).sessions).toEqual([]);
  });

  it('ends a session docked that no tab knows: detached before this window loaded again', async () => {
    await listenForDocking();
    fire('rdp-window-closed', { session_id: 'rdp-7' });
    await settle();
    expect(h.rdpSessionStop).toHaveBeenCalledWith('rdp-7');
    expect(get(terminals).sessions).toEqual([]);
  });

  it('a detached window takes its session as the only one and follows its phases', async () => {
    const key = adoptRdp('rdp-3');
    expect(get(terminals).active).toBe(key);
    expect(only()).toMatchObject({ detached: true, status: 'connected' });
    await settle();
    expect(h.rdpSessionAttach).toHaveBeenCalledWith('rdp-3', 0);
    expect(rdp()).toMatchObject({ sessionId: 'rdp-3', wsPort: 7001, token: 'renewed1' });
    phase({ session_id: 'rdp-4', phase: 'disconnected' });
    expect(only().status).toBe('connected');
    phase({ session_id: 'rdp-3', phase: 'disconnected', code: 'closed' });
    expect(only().status).toBe('disconnected');
    expect(rdp()).toMatchObject({ sessionId: null, token: null });
  });

  it('a detached window whose session is gone shows it disconnected', async () => {
    h.rdpSessionAttach.mockRejectedValueOnce(new Error('the session ended'));
    adoptRdp('rdp-3');
    await settle();
    expect(only().status).toBe('disconnected');
    expect(rdp()).toMatchObject({ phase: 'disconnected', sessionId: null, token: null });
  });

  it('reads the session of a detached RDP window from its route', () => {
    expect(detachedRdpRoute('#/detached-rdp/rdp-12')).toEqual({ sessionId: 'rdp-12', screen: 0 });
    expect(detachedRdpRoute('#/detached-rdp/rdp-12/1')).toEqual({ sessionId: 'rdp-12', screen: 1 });
    expect(detachedRdpRoute('#/detached-rdp/12')).toBeNull();
    expect(detachedRdpRoute('#/detached-rdp/rdp-1/x')).toBeNull();
    expect(detachedRdpRoute('#/detached-rdp/rdp-1/2')).toBeNull();
    expect(detachedRdpRoute('#/detached-rdp/rdp-1/1/1')).toBeNull();
    expect(detachedRdpRoute('#/detached/3')).toBeNull();
    expect(detachedRoute('#/detached-rdp/rdp-1')).toBeNull();
  });

  describe('across two monitors', () => {
    async function connected(): Promise<string> {
      await listenForDocking();
      await openRdp(RDP);
      phase({ session_id: 's1', phase: 'connected' });
      setRdpWindow(only().key, 'multimon');
      return only().key;
    }

    it('opens the second monitor in a window of its own and closes it, the tab staying', async () => {
      const key = await connected();
      await openRdpMonitor(key);
      await openRdpMonitor(key);
      expect(h.rdpDetach).toHaveBeenCalledExactlyOnceWith('s1', 'db', 1);
      expect(only().detached).toBeFalsy();

      await closeRdpMonitor('s1');
      expect(h.rdpDock).toHaveBeenCalledExactlyOnceWith('s1');
      // The dock main asked for is no dock of the tab: it logs in nowhere anew.
      fire('rdp-docked', { session_id: 's1' });
      await settle();
      expect(h.rdpSessionAttach).not.toHaveBeenCalled();
      expect(h.rdpSessionStop).not.toHaveBeenCalled();
      expect(get(terminals).active).toBe(key);
      // Closed already: nothing more to close.
      await closeRdpMonitor('s1');
      expect(h.rdpDock).toHaveBeenCalledOnce();
    });

    it('shows one monitor again when the second window is closed from its title bar', async () => {
      const key = await connected();
      await openRdpMonitor(key);
      fire('rdp-monitor-closed', { session_id: 's1' });
      expect(rdp().window).toBe('fit');
      await closeRdpMonitor('s1');
      expect(h.rdpDock).not.toHaveBeenCalled();
      expect(only().detached).toBeFalsy();
    });

    it('stays on one monitor, fitted, when the second window cannot open', async () => {
      const key = await connected();
      h.rdpDetach.mockRejectedValueOnce(new Error('no window'));
      await openRdpMonitor(key);
      expect(h.reportError).toHaveBeenCalledWith('no window');
      expect(rdp().window).toBe('fit');
      await closeRdpMonitor('s1');
      expect(h.rdpDock).not.toHaveBeenCalled();
    });

    it('closes the second window that opened after it was closed already', async () => {
      const key = await connected();
      let opened!: () => void;
      h.rdpDetach.mockImplementationOnce(() => new Promise<void>((resolve) => (opened = resolve)));
      const opening = openRdpMonitor(key);
      await closeRdpMonitor('s1');
      opened();
      await opening;
      expect(h.rdpDock).toHaveBeenCalledTimes(2);
      fire('rdp-docked', { session_id: 's1' });
      fire('rdp-docked', { session_id: 's1' });
      await settle();
      expect(h.rdpSessionAttach).not.toHaveBeenCalled();
    });

    it('detaching the tab closes the second window first and keeps the tab detached', async () => {
      const key = await connected();
      await openRdpMonitor(key);
      await detachTerminal(key);
      expect(h.rdpDock).toHaveBeenCalledExactlyOnceWith('s1');
      expect(h.rdpDock.mock.invocationCallOrder[0]).toBeLessThan(
        h.rdpDetach.mock.invocationCallOrder[1],
      );
      expect(h.rdpDetach).toHaveBeenLastCalledWith('s1', 'db');
      // The dock that closed the second window, heard after the tab went: it stays detached.
      fire('rdp-docked', { session_id: 's1' });
      await settle();
      expect(only().detached).toBe(true);
      // Its own window's dock takes it back.
      fire('rdp-docked', { session_id: 's1' });
      await settle();
      expect(only().detached).toBe(false);
    });

    it('a second monitor window takes screen 1 of its session', async () => {
      adoptRdp('rdp-3', 1);
      await settle();
      expect(h.rdpSessionAttach).toHaveBeenCalledExactlyOnceWith('rdp-3', 1);
    });
  });
});
