// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Sessions of the embedded terminal (R-1069): one tab each, after the tab of the page. The
// status follows the program: connecting until its first output, connected while it runs after
// that, disconnected with its exit code once it ends or when it did not start. A session keeps
// its output until its terminal attaches, so nothing the program sends first is lost, a cursor
// query of the Windows pseudo console among it. A session detached into a window of its own
// (R-1070) keeps its tab, without a terminal; docked again, it attaches anew and the terminal
// gets the output Rust kept first.

import { get, writable } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import * as bridge from '$lib/bridge';
import type { TerminalMessage } from '$lib/bridge';
import type { Connection } from '$lib/bridge/types';
import { errMsg } from '$lib/utils/errors';
import { reportError } from './statusBar';
import { getMappings } from './tunnel';

export type TerminalStatus = 'connecting' | 'connected' | 'disconnected';

export interface TerminalSession {
  key: string;
  /** The connection as listed. */
  connection: Connection;
  /** Where it is reached (resolve_connection): what the program was started for. */
  resolved: Connection;
  status: TerminalStatus;
  exitCode: number | null;
  /** When the first output of the program came, in ms since the epoch. */
  connectedAt: number | null;
  /** The session in Rust; null until it started. */
  backendId: number | null;
  /** Shown in a window of its own; its tab has no terminal meanwhile. */
  detached?: boolean;
}

/**
 * Takes the output of a session. `parsed`, given with the end of a replay, is called once the
 * terminal has worked through everything written before.
 */
export type TerminalSink = (data: Uint8Array, parsed?: () => void) => void;

/** The tab of the page the sidebar shows, always the first. */
export const PAGE_TAB = 'page';

interface TerminalsState {
  sessions: TerminalSession[];
  /** PAGE_TAB or the key of a session. */
  active: string;
}

const state = writable<TerminalsState>({ sessions: [], active: PAGE_TAB });

export const terminals = { subscribe: state.subscribe };

// The size a program starts with until its terminal has measured itself.
const START_COLS = 80;
const START_ROWS = 24;

// What a session holds besides what the tabs show. `attempt` counts the starts and the channels:
// the channel of an earlier program, one a reconnect replaced, or of this window before a detach
// is not heard any more. `input` is what was typed before the start answered with the id: the
// program may already have asked something, the Windows pseudo console its cursor position.
// `replaying` holds while the terminal works through output Rust kept: it would answer the
// queries in it again, so what it sends meanwhile is dropped. In `pending`, null marks the end
// of a replay.
interface Runtime {
  attempt: number;
  output: boolean;
  sink: TerminalSink | null;
  pending: (Uint8Array | null)[];
  replaying: boolean;
  input: Uint8Array[];
  cols: number;
  rows: number;
  writes: Promise<void>;
}

const runtimes = new Map<string, Runtime>();
let opened = 0;

function find(key: string): TerminalSession | undefined {
  return get(state).sessions.find((s) => s.key === key);
}

function update(key: string, change: Partial<TerminalSession>): void {
  state.update((s) => ({
    ...s,
    sessions: s.sessions.map((session) =>
      session.key === key ? { ...session, ...change } : session,
    ),
  }));
}

/**
 * The id of the program of `session` in Rust while it runs; null before it started and after it
 * ended.
 */
function runningId(session: TerminalSession): number | null {
  return session.status === 'disconnected' ? null : session.backendId;
}

/** Ends the program `id`; its exit still comes on its channel. */
function end(id: number): void {
  bridge.terminalClose(id).catch((err: unknown) => reportError(errMsg(err)));
}

const NOTHING = new Uint8Array(0);

/** Hands the end of a replay to `sink`: what the terminal sends after it is meant. */
function endReplay(runtime: Runtime, sink: TerminalSink): void {
  sink(NOTHING, () => {
    if (runtime.sink === sink) runtime.replaying = false;
  });
}

function receive(key: string, runtime: Runtime, message: TerminalMessage): void {
  if ('replayed' in message) {
    if (runtime.sink) endReplay(runtime, runtime.sink);
    else runtime.pending.push(null);
    return;
  }
  if (message instanceof ArrayBuffer) {
    const data = new Uint8Array(message);
    if (runtime.sink) runtime.sink(data);
    else runtime.pending.push(data);
    if (!runtime.output) {
      runtime.output = true;
      update(key, { status: 'connected', connectedAt: Date.now() });
    }
    return;
  }
  update(key, { status: 'disconnected', exitCode: message.exitCode });
}

function begin(runtime: Runtime): number {
  runtime.attempt += 1;
  runtime.output = false;
  runtime.input = [];
  runtime.replaying = false;
  return runtime.attempt;
}

/** Starts the program for `resolved` in session `key`; false when it did not start. */
async function start(
  key: string,
  runtime: Runtime,
  attempt: number,
  resolved: Connection,
): Promise<boolean> {
  const current = () => runtimes.get(key) === runtime && runtime.attempt === attempt;
  const { cols, rows } = runtime;
  let id: number;
  try {
    id = await bridge.terminalOpenSsh(resolved, cols, rows, (message) => {
      if (current()) receive(key, runtime, message);
    });
  } catch (err) {
    if (current()) {
      runtime.input = [];
      update(key, { status: 'disconnected', backendId: null });
    }
    reportError(errMsg(err));
    return false;
  }
  if (!current()) {
    // Closed or started anew while it started: no tab shows this program.
    end(id);
    return true;
  }
  update(key, { backendId: id });
  for (const data of runtime.input.splice(0)) send(key, runtime, id, data);
  if (runtime.cols !== cols || runtime.rows !== rows) resizeBackend(id, runtime.cols, runtime.rows);
  return true;
}

/**
 * Opens `resolved`, the target of `connection`, in a new tab in front. False when the program did
 * not start: the tab then shows the session disconnected, the status bar why.
 */
export function openTerminal(connection: Connection, resolved: Connection): Promise<boolean> {
  opened += 1;
  const key = `terminal-${opened}`;
  const runtime: Runtime = {
    attempt: 0,
    output: false,
    sink: null,
    pending: [],
    replaying: false,
    input: [],
    cols: START_COLS,
    rows: START_ROWS,
    writes: Promise.resolve(),
  };
  runtimes.set(key, runtime);
  const session: TerminalSession = {
    key,
    connection,
    resolved,
    status: 'connecting',
    exitCode: null,
    connectedAt: null,
    backendId: null,
  };
  state.update((s) => ({ sessions: [...s.sessions, session], active: key }));
  return start(key, runtime, begin(runtime), resolved);
}

/**
 * Starts the program of session `key` anew in its tab, the connection resolved again: a visitor
 * port may have moved since. A program still running ends first.
 */
export async function reconnectTerminal(key: string): Promise<boolean> {
  const session = find(key);
  const runtime = runtimes.get(key);
  if (!session || !runtime) return false;
  const attempt = begin(runtime);
  const id = runningId(session);
  if (id !== null) end(id);
  update(key, { status: 'connecting', exitCode: null, connectedAt: null, backendId: null });
  let resolved: Connection;
  try {
    resolved = (await bridge.resolveConnection(session.connection, getMappings())).connection;
  } catch (err) {
    if (runtimes.get(key) === runtime && runtime.attempt === attempt) {
      update(key, { status: 'disconnected' });
    }
    reportError(errMsg(err));
    return false;
  }
  if (runtimes.get(key) !== runtime || runtime.attempt !== attempt) return false;
  update(key, { resolved });
  return start(key, runtime, attempt, resolved);
}

/** The tab in front once `key` leaves the front: the one before it, a session or the page. */
function before(s: TerminalsState, key: string): string {
  if (s.active !== key) return s.active;
  const index = s.sessions.findIndex((x) => x.key === key);
  return s.sessions[index - 1]?.key ?? PAGE_TAB;
}

/**
 * Removes the tab of `key` and ends its program if it still runs, its window with it when it is
 * detached. Was it in front, the tab before it comes to the front: another session, or the page.
 */
export function closeTerminal(key: string): void {
  const session = find(key);
  if (!session) return;
  runtimes.delete(key);
  const id = runningId(session);
  if (id !== null) end(id);
  if (session.detached && session.backendId !== null) {
    bridge.terminalDock(session.backendId).catch((err: unknown) => reportError(errMsg(err)));
  }
  state.update((s) => ({
    sessions: s.sessions.filter((x) => x.key !== key),
    active: before(s, key),
  }));
}

/**
 * Moves the running session `key` into a window of its own; its tab stays, without a terminal,
 * and leaves the front. Detached already, its window comes to the front.
 */
export async function detachTerminal(key: string): Promise<void> {
  const session = find(key);
  const runtime = runtimes.get(key);
  const id = session ? runningId(session) : null;
  if (!session || !runtime || id === null) return;
  try {
    await bridge.terminalDetach(id, session.connection.name);
  } catch (err) {
    reportError(errMsg(err));
    return;
  }
  if (session.detached || runtimes.get(key) !== runtime) return;
  // The window attaches the session itself; this channel hears nothing more, and the terminal
  // of the tab goes with what it showed.
  runtime.attempt += 1;
  runtime.pending = [];
  runtime.input = [];
  state.update((s) => ({
    sessions: s.sessions.map((x) => (x.key === key ? { ...x, detached: true } : x)),
    active: before(s, key),
  }));
}

/**
 * Takes the detached session `id` back into its tab, in front: the window docked it or was
 * closed. Its terminal starts anew and gets the output Rust kept first. A session that ended
 * meanwhile shows disconnected.
 */
export async function dockTerminal(id: number): Promise<void> {
  const session = get(state).sessions.find((s) => s.detached && s.backendId === id);
  const runtime = session && runtimes.get(session.key);
  if (!session || !runtime) return;
  const { key } = session;
  const attempt = (runtime.attempt += 1);
  const current = () => runtimes.get(key) === runtime && runtime.attempt === attempt;
  runtime.pending = [];
  runtime.replaying = true;
  state.update((s) => ({
    sessions: s.sessions.map((x) => (x.key === key ? { ...x, detached: false } : x)),
    active: key,
  }));
  try {
    await bridge.terminalAttach(id, (message) => {
      if (current()) receive(key, runtime, message);
    });
  } catch (err) {
    if (current()) {
      runtime.replaying = false;
      update(key, { status: 'disconnected' });
    }
    reportError(errMsg(err));
  }
}

/**
 * Docks a session when its window says so (`terminal-docked`) and when it is closed from its
 * title bar (`terminal-window-closed`, Kevin 2026-11-06: docking keeps the program).
 */
export async function listenForDocking(): Promise<UnlistenFn> {
  const dock = (e: { payload: { id: number } }) => void dockTerminal(e.payload.id);
  const fns = await Promise.all([
    listen<{ id: number }>('terminal-docked', dock),
    listen<{ id: number }>('terminal-window-closed', dock),
  ]);
  return () => fns.forEach((fn) => fn());
}

/**
 * Ends every session of this window, those of an earlier load of it among them, and removes
 * their tabs: as the UI starts and before the logout reloads it.
 */
export async function closeAllTerminals(): Promise<void> {
  runtimes.clear();
  state.set({ sessions: [], active: PAGE_TAB });
  await bridge.terminalCloseAll();
}

/** Brings the tab `tab` (PAGE_TAB or the key of a session) to the front. */
export function showTab(tab: string): void {
  if (tab !== PAGE_TAB && !find(tab)) return;
  state.update((s) => ({ ...s, active: tab }));
}

/**
 * Hands the output of session `key` to its terminal, first what came before. The returned
 * function detaches it; output then waits again.
 */
export function attachTerminal(key: string, sink: TerminalSink): () => void {
  const runtime = runtimes.get(key);
  if (!runtime) return () => {};
  runtime.sink = sink;
  for (const data of runtime.pending.splice(0)) {
    if (data) sink(data);
    else endReplay(runtime, sink);
  }
  return () => {
    if (runtime.sink === sink) runtime.sink = null;
  };
}

/** Writes `data` to program `id` of session `key` after the writes before it have settled. */
function send(key: string, runtime: Runtime, id: number, data: Uint8Array): void {
  runtime.writes = runtime.writes.then(async () => {
    const session = find(key);
    // Ended, or replaced by a reconnect, while the writes before it went.
    if (!session || runningId(session) !== id) return;
    try {
      await bridge.terminalWrite(id, data);
    } catch {
      // The program has ended between the check and the write; its exit follows on the channel.
    }
  });
}

/**
 * Sends what was typed in the terminal of `key` to its program, in the order typed: one write
 * after the other has settled (bridge.terminalWrite), what came before the start answered once it
 * has. Nothing goes to a program that ended or did not start.
 */
export function writeTerminal(key: string, data: Uint8Array): void {
  const runtime = runtimes.get(key);
  const session = find(key);
  if (!runtime || !session || session.status === 'disconnected') return;
  if (runtime.replaying || session.detached) return;
  if (session.backendId === null) runtime.input.push(data);
  else send(key, runtime, session.backendId, data);
}

function resizeBackend(id: number, cols: number, rows: number): void {
  // A session that has just ended refuses the size; its exit follows on the channel.
  bridge.terminalResize(id, cols, rows).catch(() => {});
}

/** The size the terminal of `key` measured: its program gets it now, a reconnect starts with it. */
export function resizeTerminal(key: string, cols: number, rows: number): void {
  const runtime = runtimes.get(key);
  const session = find(key);
  if (!runtime || !session) return;
  runtime.cols = cols;
  runtime.rows = rows;
  const id = runningId(session);
  if (id !== null) resizeBackend(id, cols, rows);
}
