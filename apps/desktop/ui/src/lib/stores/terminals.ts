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
// An embedded RDP session (R-1098) is a tab of its own kind: Rust runs it, its phases come as
// `rdp-session` events, and its picture goes over a WebSocket of its own. Detached (R-1101), its
// window logs in at that WebSocket and the tab lets go of it; docked, the tab logs in again.

import { get, readable, writable, type Readable } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import * as bridge from '$lib/bridge';
import type { TerminalMessage } from '$lib/bridge';
import type {
  AnsibleTarget,
  Connection,
  RdpEndCode,
  RdpDisplay,
  RdpPerformanceProfile,
  RdpPhase,
  RdpPhaseEvent,
  RdpScalingMode,
  RdpStarted,
  RdpWindowMode,
  Settings,
} from '$lib/bridge/types';
import { errMsg, IpcError } from '$lib/utils/errors';
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
  /** An embedded RDP session (R-1098) instead of a program of a terminal. */
  rdp?: RdpView;
}

/** What the tab of an embedded RDP session shows; its picture comes over the WebSocket. */
export interface RdpView {
  /** The session in Rust while it runs; null before the start answered and once it ended. */
  sessionId: string | null;
  /** Where its picture is fetched, with which token; null without a session. */
  wsPort: number | null;
  token: string | null;
  phase: RdpPhase;
  /** Why it ended, with `disconnected` and `failed`. */
  code: RdpEndCode | null;
  /** The certificate to confirm, with the `certificate` phase. */
  certificate: { identity: string; fingerprint: string; reason: 'unknown' | 'changed' } | null;
  /** The profile this tab starts with, chosen in the tab; null: as the connection says. */
  performance: RdpPerformanceProfile | null;
  /** The window mode and scaling chosen in the tab (R-1100); null: as the settings say. */
  window: RdpWindowMode | null;
  scaling: RdpScalingMode | null;
  notice: RdpStarted['notice'] | null;
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

// What an RDP tab holds besides what it shows. `attempt` counts the starts: the events and the
// answer of an earlier start, one a reconnect or the close replaced, are not heard any more.
interface RdpRun {
  attempt: number;
  sessionId: string | null;
  unlisten: UnlistenFn | null;
  /** The password typed for this tab, for its starts anew (a trusted certificate, a
   * reconnect); kept nowhere else and gone with the tab. */
  password: string | undefined;
  /** The desktop the tab last asked for, for each start (R-1100); unset until it measured. */
  display?: RdpDisplay;
  /** The session shown in a window of its own (R-1101), also once it ended there. */
  window?: string;
}

/** How the start of an RDP tab went: `os-client` when Rust leaves the connection to the client
 * of the operating system (a gateway, printers), and the tab is gone again. */
export type RdpOpen = 'started' | 'failed' | 'os-client';

const rdpRuns = new Map<string, RdpRun>();

/** Ends the RDP session `id`; its `disconnected` phase still comes, unheard once the tab moved on. */
function stopRdp(id: string): void {
  bridge.rdpSessionStop(id).catch((err: unknown) => reportError(errMsg(err)));
}

/** Lets go of what an RDP tab listens to and ends its session if it still runs. */
function releaseRdp(run: RdpRun): void {
  run.attempt += 1;
  run.unlisten?.();
  run.unlisten = null;
  if (run.sessionId !== null) stopRdp(run.sessionId);
  run.sessionId = null;
}

function updateRdp(key: string, change: Partial<RdpView>, more: Partial<TerminalSession> = {}) {
  state.update((s) => ({
    ...s,
    sessions: s.sessions.map((session) =>
      session.key === key && session.rdp
        ? { ...session, ...more, rdp: { ...session.rdp, ...change } }
        : session,
    ),
  }));
}

const ENDING: RdpPhase[] = ['certificate', 'disconnected', 'failed'];

function rdpStatus(phase: RdpPhase): TerminalStatus {
  if (phase === 'connected') return 'connected';
  return ENDING.includes(phase) ? 'disconnected' : 'connecting';
}

function onRdpPhase(key: string, run: RdpRun, event: RdpPhaseEvent): void {
  const ended = ENDING.includes(event.phase);
  if (ended) {
    run.sessionId = null;
    run.unlisten?.();
    run.unlisten = null;
  }
  const certificate =
    event.phase === 'certificate' && event.identity && event.fingerprint && event.reason
      ? { identity: event.identity, fingerprint: event.fingerprint, reason: event.reason }
      : null;
  const more: Partial<TerminalSession> = { status: rdpStatus(event.phase) };
  if (event.phase === 'connected' && find(key)?.connectedAt == null) more.connectedAt = Date.now();
  updateRdp(
    key,
    {
      phase: event.phase,
      code: event.code ?? null,
      certificate,
      ...(ended ? { sessionId: null, wsPort: null, token: null } : {}),
    },
    more,
  );
}

/** The connection as listed, with the profile chosen in the tab. */
function withProfile(connection: Connection, profile: RdpPerformanceProfile | null): Connection {
  if (profile === null) return connection;
  const options = connection.options ?? {};
  return {
    ...connection,
    options: { ...options, rdp: { ...options.rdp, performanceProfile: profile } },
  };
}

/**
 * Starts the RDP session of tab `key`. It listens to the phases before it starts: the first one
 * may come before the start answers with the id, so what comes before is kept and sorted after.
 * False when it did not start: the tab then shows it failed, the status bar why.
 */
async function startRdp(key: string, run: RdpRun, first = false): Promise<RdpOpen> {
  const session = find(key);
  if (!session?.rdp) return 'failed';
  releaseRdp(run);
  const attempt = run.attempt;
  const current = () => rdpRuns.get(key) === run && run.attempt === attempt;
  updateRdp(
    key,
    {
      sessionId: null,
      wsPort: null,
      token: null,
      phase: 'connecting',
      code: null,
      certificate: null,
      notice: null,
    },
    { status: 'connecting', connectedAt: null },
  );
  let sessionId: string | null = null;
  const early: RdpPhaseEvent[] = [];
  const failed = (err: unknown): RdpOpen => {
    if (first && current() && err instanceof IpcError && err.code === 'ERR_RDP_OS_CLIENT') {
      closeTerminal(key);
      return 'os-client';
    }
    if (current()) {
      run.unlisten?.();
      run.unlisten = null;
      updateRdp(key, { phase: 'failed' }, { status: 'disconnected' });
    }
    reportError(errMsg(err));
    return 'failed';
  };
  try {
    const unlisten = await listen<RdpPhaseEvent>('rdp-session', (e) => {
      if (!current()) return;
      if (sessionId === null) early.push(e.payload);
      else if (e.payload.session_id === sessionId) onRdpPhase(key, run, e.payload);
    });
    if (!current()) {
      unlisten();
      return 'failed';
    }
    run.unlisten = unlisten;
  } catch (err) {
    return failed(err);
  }
  let started: RdpStarted;
  try {
    started = await bridge.rdpSessionStart(
      withProfile(session.connection, session.rdp.performance),
      run.password,
      run.display,
    );
  } catch (err) {
    return failed(err);
  }
  if (!current()) {
    // Closed or started anew while it started: no tab shows this session.
    stopRdp(started.session_id);
    return 'started';
  }
  sessionId = started.session_id;
  run.sessionId = sessionId;
  updateRdp(key, {
    sessionId,
    wsPort: started.ws_port,
    token: started.token,
    notice: started.notice ?? null,
  });
  for (const event of early.splice(0)) {
    if (event.session_id === sessionId && current()) onRdpPhase(key, run, event);
  }
  return 'started';
}

/**
 * Opens `connection`, an RDP connection as listed, as an embedded session in a new tab in front,
 * with `password` when the user typed one, else the stored one. Rust resolves and checks it.
 */
export function openRdp(connection: Connection, password?: string): Promise<RdpOpen> {
  opened += 1;
  const key = `terminal-${opened}`;
  const run: RdpRun = { attempt: 0, sessionId: null, unlisten: null, password };
  rdpRuns.set(key, run);
  const session: TerminalSession = {
    key,
    connection,
    resolved: connection,
    status: 'connecting',
    exitCode: null,
    connectedAt: null,
    backendId: null,
    rdp: {
      sessionId: null,
      wsPort: null,
      token: null,
      phase: 'connecting',
      code: null,
      certificate: null,
      performance: null,
      window: null,
      scaling: null,
      notice: null,
    },
  };
  state.update((s) => ({ sessions: [...s.sessions, session], active: key }));
  return startRdp(key, run, true);
}

/** Starts the RDP session of tab `key` anew; one still running ends first. */
export function reconnectRdp(key: string): Promise<boolean> {
  const run = rdpRuns.get(key);
  return run ? startRdp(key, run).then((open) => open === 'started') : Promise.resolve(false);
}

/** Ends the RDP session of tab `key`; the tab stays and shows it disconnected. */
export function disconnectRdp(key: string): void {
  const run = rdpRuns.get(key);
  if (run?.sessionId) stopRdp(run.sessionId);
}

/** Starts tab `key` anew with `profile`, for this tab only: the settings stay as they are. */
export function setRdpPerformance(key: string, profile: RdpPerformanceProfile): Promise<boolean> {
  updateRdp(key, { performance: profile });
  return reconnectRdp(key);
}

/** Chooses how tab `key` lays its desktop out, for this tab only; the session follows its size. */
export function setRdpWindow(key: string, mode: RdpWindowMode): void {
  updateRdp(key, { window: mode });
}

/** Chooses the scaling of tab `key`, for this tab only. */
export function setRdpScaling(key: string, scaling: RdpScalingMode): void {
  updateRdp(key, { scaling });
}

/**
 * Keeps the desktop tab `key` asks for: each start of its session asks for it first, so a
 * reconnect starts with the size the tab has, not with the size it had once.
 */
export function setRdpDisplay(key: string, display: RdpDisplay): void {
  const run = rdpRuns.get(key);
  if (run) run.display = display;
}

/**
 * Pins the certificate tab `key` was refused for, as the user confirmed it, and starts the
 * session anew. False when the pin was not saved: the status bar says why.
 */
export async function trustRdpCertificate(key: string): Promise<boolean> {
  const certificate = find(key)?.rdp?.certificate;
  if (!certificate) return false;
  try {
    await bridge.rdpTrustCertificate(certificate.identity, certificate.fingerprint);
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
  return reconnectRdp(key);
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
  const run = rdpRuns.get(key);
  if (run) {
    rdpRuns.delete(key);
    releaseRdp(run);
    if (run.window) closeRdpWindow(run.window);
  }
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
  if (session?.rdp) return detachRdp(key, session);
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

function closeRdpWindow(sessionId: string): void {
  bridge.rdpDock(sessionId).catch((err: unknown) => reportError(errMsg(err)));
}

/** Moves the running RDP session of tab `key` into a window of its own, as `detachTerminal`. */
async function detachRdp(key: string, session: TerminalSession): Promise<void> {
  const run = rdpRuns.get(key);
  const id = run?.sessionId;
  // Rust knows where a session listens once it connected.
  if (!run || !id || session.rdp?.phase !== 'connected') return;
  // `rdp_dock` closes the windows of both screens: the second one goes before the first opens.
  await closeRdpMonitor(id);
  try {
    await bridge.rdpDetach(id, session.connection.name);
  } catch (err) {
    reportError(errMsg(err));
    return;
  }
  if (find(key)?.detached || rdpRuns.get(key) !== run || run.sessionId !== id) return;
  // The window logs in at the session's WebSocket; the tab's picture goes with its view.
  run.window = id;
  state.update((s) => ({
    sessions: s.sessions.map((x) => (x.key === key ? { ...x, detached: true } : x)),
    active: before(s, key),
  }));
}

/**
 * Logs tab `key` in anew at the WebSocket of its running session `sessionId`: the window that
 * showed it before loses the picture. Its phases come as `rdp-session` events; a tab that does
 * not hear them yet starts to. A session that ended meanwhile shows disconnected.
 */
async function attachRdp(
  key: string,
  run: RdpRun,
  sessionId: string,
  screen = 0,
): Promise<boolean> {
  const attempt = run.attempt;
  const current = () => rdpRuns.get(key) === run && run.attempt === attempt;
  try {
    if (!run.unlisten) {
      const unlisten = await listen<RdpPhaseEvent>('rdp-session', (e) => {
        if (current() && e.payload.session_id === sessionId) onRdpPhase(key, run, e.payload);
      });
      if (!current()) {
        unlisten();
        return false;
      }
      run.unlisten = unlisten;
    }
    const attached = await bridge.rdpSessionAttach(sessionId, screen);
    if (!current() || run.sessionId !== sessionId) return false;
    updateRdp(key, { sessionId, wsPort: attached.ws_port, token: attached.token });
    return true;
  } catch (err) {
    if (current()) {
      run.sessionId = null;
      updateRdp(
        key,
        { sessionId: null, wsPort: null, token: null, phase: 'disconnected' },
        { status: 'disconnected' },
      );
    }
    reportError(errMsg(err));
    return false;
  }
}

/**
 * Takes the detached RDP session `sessionId` back into its tab, in front, as `dockTerminal`. A
 * session no tab knows, detached before this window loaded again, ends: nothing would show it.
 */
async function dockRdp(sessionId: string): Promise<void> {
  // Main closed the second monitor's window itself: the tab stays where it is.
  const docking = rdpDocking.get(sessionId) ?? 0;
  if (docking > 0) {
    if (docking === 1) rdpDocking.delete(sessionId);
    else rdpDocking.set(sessionId, docking - 1);
    return;
  }
  const key = [...rdpRuns].find(([, run]) => run.window === sessionId)?.[0];
  const run = key === undefined ? undefined : rdpRuns.get(key);
  if (key === undefined || !run || !find(key)?.detached) {
    // Silent: a tab closed while detached has ended it already, and its window docks after.
    if (![...rdpRuns.values()].some((r) => r.sessionId === sessionId || r.window === sessionId)) {
      bridge.rdpSessionStop(sessionId).catch(() => {});
    }
    return;
  }
  run.window = undefined;
  // Logged in first, so the tab's view opens with the token it may use.
  if (run.sessionId === sessionId) await attachRdp(key, run, sessionId);
  if (rdpRuns.get(key) !== run) return;
  state.update((s) => ({
    sessions: s.sessions.map((x) => (x.key === key ? { ...x, detached: false } : x)),
    active: key,
  }));
}

/**
 * Takes screen `screen` of the running RDP session `sessionId` as the only session of this
 * window, the window it is detached into; its key. The window's title bar names it, so the
 * connection is a stand-in.
 */
export function adoptRdp(sessionId: string, screen = 0): string {
  opened += 1;
  const key = `terminal-${opened}`;
  const run: RdpRun = { attempt: 0, sessionId, unlisten: null, password: undefined };
  rdpRuns.set(key, run);
  const connection = { id: '', name: '', kind: 'rdp' } as Connection;
  const session: TerminalSession = {
    key,
    connection,
    resolved: connection,
    status: 'connected',
    exitCode: null,
    connectedAt: null,
    backendId: null,
    detached: true,
    rdp: {
      sessionId,
      wsPort: null,
      token: null,
      phase: 'connected',
      code: null,
      certificate: null,
      performance: null,
      window: null,
      scaling: null,
      notice: null,
    },
  };
  state.set({ sessions: [session], active: key });
  void attachRdp(key, run, sessionId, screen);
  return key;
}

/**
 * The RDP session and its screen the route `hash` of a detached window shows
 * (`#/detached-rdp/<id>`, the second monitor's `#/detached-rdp/<id>/1`).
 */
export function detachedRdpRoute(hash: string): { sessionId: string; screen: number } | null {
  const match = /^#\/detached-rdp\/(rdp-[0-9]+)(\/1)?$/.exec(hash);
  return match ? { sessionId: match[1], screen: match[2] ? 1 : 0 } : null;
}

// Sessions across two monitors whose second one main shows in a window of its own (R-1101),
// and how many `rdp-docked` main has asked for to close one: those are no dock of a tab.
const rdpMonitors = new Set<string>();
const rdpDocking = new Map<string, number>();

function dockMonitor(sessionId: string): Promise<void> {
  rdpDocking.set(sessionId, (rdpDocking.get(sessionId) ?? 0) + 1);
  return bridge.rdpDock(sessionId).catch((err: unknown) => {
    const docking = (rdpDocking.get(sessionId) ?? 1) - 1;
    if (docking > 0) rdpDocking.set(sessionId, docking);
    else rdpDocking.delete(sessionId);
    reportError(errMsg(err));
  });
}

/**
 * Shows the second monitor of the session of tab `key` in a window of its own, on another monitor
 * of the system. One that cannot open leaves the tab on one monitor, fitted.
 */
export async function openRdpMonitor(key: string): Promise<void> {
  const session = find(key);
  const id = rdpRuns.get(key)?.sessionId;
  if (!session || !id || rdpMonitors.has(id)) return;
  rdpMonitors.add(id);
  try {
    await bridge.rdpDetach(id, session.connection.name, 1);
  } catch (err) {
    rdpMonitors.delete(id);
    reportError(errMsg(err));
    if (rdpRuns.get(key)?.sessionId === id) setRdpWindow(key, 'fit');
    return;
  }
  // Closed again while it opened: it goes now.
  if (!rdpMonitors.has(id)) await dockMonitor(id);
}

/** Closes the second monitor's window of session `sessionId`, if main opened one. */
export function closeRdpMonitor(sessionId: string): Promise<void> {
  return rdpMonitors.delete(sessionId) ? dockMonitor(sessionId) : Promise.resolve();
}

/** The second monitor's window was closed from its title bar: the tab shows one monitor again. */
function monitorClosed(sessionId: string): void {
  if (!rdpMonitors.delete(sessionId)) return;
  const key = [...rdpRuns].find(([, run]) => run.sessionId === sessionId)?.[0];
  if (key !== undefined) setRdpWindow(key, 'fit');
}

/** The session the route `hash` of a detached window shows (`#/detached/<id>`); else null. */
export function detachedRoute(hash: string): number | null {
  const match = /^#\/detached\/([0-9]+)$/.exec(hash);
  return match ? Number(match[1]) : null;
}

/**
 * Docks a session when its window says so (`terminal-docked`, `rdp-docked`) and when it is closed
 * from its title bar (`terminal-window-closed`, `rdp-window-closed`; Kevin 2026-11-06: docking
 * keeps the program). A second monitor's window closed so shows the session on one monitor
 * again (`rdp-monitor-closed`).
 */
export async function listenForDocking(): Promise<UnlistenFn> {
  const dock = (e: { payload: { id: number } }) => void dockTerminal(e.payload.id);
  const dockRdpEvent = (e: { payload: { session_id: string } }) =>
    void dockRdp(e.payload.session_id);
  const fns = await Promise.all([
    listen<{ id: number }>('terminal-docked', dock),
    listen<{ id: number }>('terminal-window-closed', dock),
    listen<{ session_id: string }>('rdp-docked', dockRdpEvent),
    listen<{ session_id: string }>('rdp-window-closed', dockRdpEvent),
    listen<{ session_id: string }>('rdp-monitor-closed', (e) =>
      monitorClosed(e.payload.session_id),
    ),
  ]);
  return () => fns.forEach((fn) => fn());
}

/**
 * Ends every session of this window, those of an earlier load of it among them, and removes
 * their tabs: as the UI starts and before the logout reloads it. RDP sessions end with their
 * tabs; one an earlier load started ends with the app, as nothing shows it.
 */
export async function closeAllTerminals(): Promise<void> {
  // The logout ends the tabs, not the run: what was open is opened again after the next sign-in.
  stopKeeping?.();
  runtimes.clear();
  for (const run of rdpRuns.values()) {
    releaseRdp(run);
    if (run.window) closeRdpWindow(run.window);
  }
  rdpRuns.clear();
  for (const id of rdpMonitors) closeRdpWindow(id);
  rdpMonitors.clear();
  // What these docks announce finds no tab any more and ends a session that ended already.
  rdpDocking.clear();
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
