// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The sessions of the embedded terminal (R-1069) over a mocked bridge: the status follows the
// program (connecting, connected with its first output, disconnected with its exit code), output
// waits for the terminal, a reconnect resolves anew in the same tab and no longer hears the
// program it replaced, closing ends what still runs, and what is typed reaches the program in
// order, what came before the start answered once it has.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { TerminalMessage } from '$lib/bridge';
import type { Connection, TunnelMapping } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  terminalOpenSsh: vi.fn(),
  terminalClose: vi.fn(async () => {}),
  terminalCloseAll: vi.fn(async () => {}),
  terminalWrite: vi.fn(async () => {}),
  terminalResize: vi.fn(async () => {}),
  resolveConnection: vi.fn(async (connection: unknown) => ({ connection })),
  reportError: vi.fn(),
  mappings: [] as unknown[],
}));

vi.mock('$lib/bridge', () => ({
  terminalOpenSsh: h.terminalOpenSsh,
  terminalClose: h.terminalClose,
  terminalCloseAll: h.terminalCloseAll,
  terminalWrite: h.terminalWrite,
  terminalResize: h.terminalResize,
  resolveConnection: h.resolveConnection,
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError }));
vi.mock('./tunnel', () => ({ getMappings: () => h.mappings }));

import {
  PAGE_TAB,
  attachTerminal,
  closeAllTerminals,
  closeTerminal,
  openTerminal,
  reconnectTerminal,
  resizeTerminal,
  showTab,
  terminals,
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
