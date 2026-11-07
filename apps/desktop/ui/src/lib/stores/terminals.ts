// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Sessions of the embedded terminal (R-1069): one tab each, after the tab of the page. The
// status follows the program: connecting until its first output, connected while it runs after
// that, disconnected with its exit code once it ends or when it did not start. A session keeps
// its output until its terminal attaches, so nothing the program sends first is lost, a cursor
// query of the Windows pseudo console among it. A session detached into a window of its own
// (R-1070) keeps its tab, without a terminal; docked again, it attaches anew and the terminal
// gets the output Rust kept first. The window it is detached into holds it as its only session.

import { get, readable, writable, type Readable } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import * as bridge from '$lib/bridge';
import type { TerminalMessage } from '$lib/bridge';
import type { AnsibleTarget, Connection, Settings } from '$lib/bridge/types';
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
  /**
   * A run of a playbook (R-1073) instead of an SSH session: `connection` then only carries its
   * name. It is not reconnected and not kept for the next run.
   */
  ansible?: { check: boolean };
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

/** Starts the program of a session: in cols×rows, its output to `onMessage`; resolves to its id. */
type Launch = (
  cols: number,
  rows: number,
  onMessage: (message: TerminalMessage) => void,
) => Promise<number>;

/** Starts the program of session `key` with `launch`; false when it did not start. */
async function start(
  key: string,
  runtime: Runtime,
  attempt: number,
  launch: Launch,
): Promise<boolean> {
  const current = () => runtimes.get(key) === runtime && runtime.attempt === attempt;
  const { cols, rows } = runtime;
  let id: number;
  try {
    id = await launch(cols, rows, (message) => {
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

function newRuntime(key: string): Runtime {
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
  return runtime;
}

/**
 * Opens `resolved`, the target of `connection`, in a new tab in front. False when the program did
 * not start: the tab then shows the session disconnected, the status bar why.
 */
export function openTerminal(connection: Connection, resolved: Connection): Promise<boolean> {
  opened += 1;
  const key = `terminal-${opened}`;
  const runtime = newRuntime(key);
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
  return start(key, runtime, begin(runtime), sshLaunch(resolved));
}

function sshLaunch(resolved: Connection): Launch {
  return (cols, rows, onMessage) => bridge.terminalOpenSsh(resolved, cols, rows, onMessage);
}

/**
 * Runs the playbook `playbookId`, named `name`, on `targets` in a new tab in front, as a dry run
 * with `check`. False when it did not start: the tab then shows it disconnected, the status bar
 * why.
 */
export function openAnsible(
  playbookId: string,
  name: string,
  targets: AnsibleTarget[],
  check: boolean,
): Promise<boolean> {
  opened += 1;
  const key = `terminal-${opened}`;
  const runtime = newRuntime(key);
  // The tab shows the name of the playbook; there is no connection behind it.
  const connection = { id: '', name, kind: 'ssh', tags: [], trustCert: false } as Connection;
  const session: TerminalSession = {
    key,
    connection,
    resolved: connection,
    status: 'connecting',
    exitCode: null,
    connectedAt: null,
    backendId: null,
    ansible: { check },
  };
  state.update((s) => ({ sessions: [...s.sessions, session], active: key }));
  return start(key, runtime, begin(runtime), (cols, rows, onMessage) =>
    bridge.terminalOpenAnsible(playbookId, targets, check, cols, rows, onMessage),
  );
}

/**
 * Starts the program of session `key` anew in its tab, the connection resolved again: a visitor
 * port may have moved since. A program still running ends first.
 */
export async function reconnectTerminal(key: string): Promise<boolean> {
  const session = find(key);
  const runtime = runtimes.get(key);
  // A playbook runs again from the Ansible page.
  if (!session || !runtime || session.ansible) return false;
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
  return start(key, runtime, attempt, sshLaunch(resolved));
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
 * Moves session `id` to the channel of `runtime`: the terminal of `key` gets the output Rust kept
 * first. A session that ended meanwhile shows disconnected.
 */
async function attachBackend(key: string, runtime: Runtime, id: number): Promise<void> {
  const attempt = (runtime.attempt += 1);
  const current = () => runtimes.get(key) === runtime && runtime.attempt === attempt;
  runtime.pending = [];
  runtime.replaying = true;
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
 * Takes the detached session `id` back into its tab, in front: the window docked it or was
 * closed. Its terminal starts anew and gets the output Rust kept first. A session no tab knows,
 * detached before this window loaded again, ends: nothing would show it.
 */
export async function dockTerminal(id: number): Promise<void> {
  const session = get(state).sessions.find((s) => s.detached && s.backendId === id);
  const runtime = session && runtimes.get(session.key);
  if (!session || !runtime) {
    // Silent: a tab closed while detached has ended it already, and its window docks after.
    if (!get(state).sessions.some((s) => s.backendId === id)) {
      bridge.terminalClose(id).catch(() => {});
    }
    return;
  }
  const { key } = session;
  state.update((s) => ({
    sessions: s.sessions.map((x) => (x.key === key ? { ...x, detached: false } : x)),
    active: key,
  }));
  await attachBackend(key, runtime, id);
}

/**
 * Takes the running session `id` as the only one of this window, the window it is detached
 * into; its key. The window's title bar names it, so the connection is a stand-in.
 */
export function adoptTerminal(id: number): string {
  opened += 1;
  const key = `terminal-${opened}`;
  const runtime = newRuntime(key);
  // It has run before: its first output here is no news of a connection.
  runtime.output = true;
  const connection = { id: '', name: '', kind: 'ssh' } as Connection;
  const session: TerminalSession = {
    key,
    connection,
    resolved: connection,
    status: 'connected',
    exitCode: null,
    connectedAt: null,
    backendId: id,
  };
  state.set({ sessions: [session], active: key });
  void attachBackend(key, runtime, id);
  return key;
}

/** The session the route `hash` of a detached window shows (`#/detached/<id>`); else null. */
export function detachedRoute(hash: string): number | null {
  const match = /^#\/detached\/([0-9]+)$/.exec(hash);
  return match ? Number(match[1]) : null;
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
  // The logout ends the tabs, not the run: what was open is opened again after the next sign-in.
  stopKeeping?.();
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

const encoder = new TextEncoder();

/**
 * Whether a snippet goes to every running SSH session (R-1071) instead of the one it was chosen
 * in. Rust holds it, not saved and off at every start of the app, so that a detached window
 * shows the warning as main does: the store listens to `terminal-broadcast`, then asks once; an
 * event heard before the answer is newer than it.
 */
export const snippetBroadcast: Readable<boolean> = readable(false, (set) => {
  let heard = false;
  let gone = false;
  let stop: UnlistenFn | null = null;
  void listen<boolean>('terminal-broadcast', (e) => {
    heard = true;
    set(e.payload);
  })
    .then(async (unlisten) => {
      if (gone) return unlisten();
      stop = unlisten;
      const on = await bridge.terminalBroadcastState();
      if (!heard && !gone) set(on);
    })
    .catch((err) => reportError(errMsg(err)));
  return () => {
    gone = true;
    stop?.();
    // Unheard, the store would keep its last state for the next reader: off is the safe one.
    set(false);
  };
});

/** Switches the broadcast; the store follows once Rust reports it to every window. */
export async function setSnippetBroadcast(on: boolean): Promise<void> {
  try {
    await bridge.terminalSetBroadcast(on);
  } catch (err) {
    reportError(errMsg(err));
  }
}

/** A snippet as typed: each line with Enter, the last one too, and no empty lines at the end. */
export function snippetInput(command: string): Uint8Array {
  return encoder.encode(command.replace(/\n+$/, '').split('\n').join('\r') + '\r');
}

/**
 * Runs `command` in the session of `key`; with the broadcast on in every running SSH session of
 * the workspace instead, whichever window shows it (Rust holds them all).
 */
export async function runSnippet(key: string, command: string): Promise<void> {
  const data = snippetInput(command);
  if (!get(snippetBroadcast)) {
    writeTerminal(key, data);
    return;
  }
  try {
    await bridge.terminalBroadcast(data);
  } catch (err) {
    reportError(errMsg(err));
  }
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

/** What keepOpenSessions works with; passed in, as connectFlow.ts imports this store. */
export interface SessionKeeping {
  settings: Readable<Settings | null>;
  connections: Readable<{ items: Connection[]; loading: boolean }>;
  /** Saves the ids of the open SSH tabs. */
  save: (ids: string[]) => Promise<void>;
  /** Opens `connection` the way a click on connect does. */
  connect: (connection: Connection) => Promise<void>;
}

let stopKeeping: (() => void) | null = null;

/** The ids of the connections with an SSH tab, in tab order, each once. */
export function openSessionIds(sessions: TerminalSession[]): string[] {
  const ids: string[] = [];
  for (const s of sessions) {
    if (
      !s.ansible &&
      s.connection.kind === 'ssh' &&
      s.connection.id &&
      !ids.includes(s.connection.id)
    ) {
      ids.push(s.connection.id);
    }
  }
  return ids;
}

/**
 * Keeps the open SSH tabs in the settings (R-1070). Once the connections are there it opens the
 * tabs of the last run again if restoreSessions is on, one after the other in their order, and
 * passes over a connection that is gone; then it saves the ids whenever the tabs change. Nothing
 * is saved before, so a list that is still loading does not wipe the last run. The function it
 * returns stops it.
 */
export function keepOpenSessions(k: SessionKeeping): () => void {
  let stopped = false;
  let stopTabs: (() => void) | null = null;
  const stop = () => {
    stopped = true;
    stopConnections?.();
    stopTabs?.();
    if (stopKeeping === stop) stopKeeping = null;
  };
  stopKeeping = stop;

  async function start(items: Connection[]): Promise<void> {
    const current = get(k.settings);
    const saved = current?.openSessions ?? [];
    if (current?.restoreSessions) {
      for (const id of [...new Set(saved)]) {
        const connection = items.find((c) => c.id === id && c.kind === 'ssh');
        if (stopped) return;
        if (connection) await k.connect(connection);
      }
    }
    if (stopped) return;
    let last = saved.join('\n');
    let saving = Promise.resolve();
    stopTabs = state.subscribe(({ sessions }) => {
      const ids = openSessionIds(sessions);
      if (ids.join('\n') === last) return;
      last = ids.join('\n');
      saving = saving.then(() => k.save(ids)).catch((err) => reportError(errMsg(err)));
    });
  }

  let started = false;
  let stopConnections: (() => void) | null = null;
  stopConnections = k.connections.subscribe(({ items, loading }) => {
    if (started || loading || items.length === 0) return;
    started = true;
    queueMicrotask(() => stopConnections?.());
    void start(items);
  });
  return stop;
}
