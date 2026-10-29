// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tunnel store: holds TunnelStatus + tunnel mappings and keeps frpc in step with
// the visitor bundle. While a server session is active it reconciles right away and
// then every 60 s (refresh_tunnel starts, reloads, restarts or stops frpc) and
// reloads the mappings after each run. Activated by AppShell on login/mode switch,
// ended by stop(). The Tauri events frpc-terminated / frpc-error (the running frpc
// ended) bring a reconciliation that restarts it after 5 s, doubled up to 60 s for
// every restart that fails or does not hold for a tick. reconnectNow() (the reconnect
// button) brings that restart forward and lets the pauses begin at 5 s again.

import { errMsg } from '$lib/utils/errors';
import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { TunnelMapping, TunnelRefresh, TunnelStatus } from '$lib/bridge/types';
import { sessionStore } from './session';
import { reportError } from './statusBar';
import { tNow } from '$lib/i18n';

export type TunnelUiState = 'idle' | 'connecting' | 'connected' | 'disconnected';

interface TunnelStoreState {
  ui: TunnelUiState;
  status: TunnelStatus | null;
  mappings: TunnelMapping[];
}

const REFRESH_INTERVAL_MS = 60_000;
const RESTART_FIRST_MS = 5_000;
const RESTART_MAX_MS = 60_000;
// A frpc that has run this long since its start ends a restart series: one tick.
const RESTART_HELD_MS = REFRESH_INTERVAL_MS;

const initial: TunnelStoreState = { ui: 'idle', status: null, mappings: [] };
const _state = writable<TunnelStoreState>(initial);
export const tunnel = { subscribe: _state.subscribe };
export const tunnelMappings = derived(_state, ($s) => $s.mappings);
export const tunnelStatus = derived(_state, ($s) => $s.status);
export const tunnelUi = derived(_state, ($s) => $s.ui);

export function getMappings(): TunnelMapping[] {
  return get(_state).mappings;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
// Bumped by every activation and every stop, so a reconciliation an earlier activation
// started can tell it was overtaken and must not write its result (as notifications.ts, 4.41).
let activationGen = 0;
// The reconciliation in flight: a tick skips while it runs; refreshNow() queues one
// follow-up after it (`next`), as the running one may have fetched the bundle before the change.
// `restart`: frpc ended while it ran, and the restart planned for that is the follow-up.
let inFlight: {
  gen: number;
  done: Promise<void>;
  next: Promise<void> | null;
  restart: boolean;
} | null = null;
// One status-bar message per series of failures (failed reconciliations, frpc-error); a
// successful reconciliation ends the series, inside a restart series only its end does.
let errorReported = false;
// One status-bar message per refusal of the tunnels: the ticks after it find it again.
let refusalReported = false;
// A frpc that ended unexpectedly waits for the restart planned in `restartTimer`; the next
// pause is `restartDelay`, null outside a restart series. Any reconciliation that starts in
// the meantime is that restart and drops the timer. `startedAt` is when the running frpc
// was started: only one that held for RESTART_HELD_MS ends the series, so a frpc that dies
// right after each start keeps backing off.
let restartTimer: ReturnType<typeof setTimeout> | null = null;
let restartDelay: number | null = null;
let startedAt: number | null = null;

function serverSession() {
  const { session, settings } = get(sessionStore);
  return session && settings?.mode === 'server' ? session : null;
}

function stopPolling(): void {
  activationGen++;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  cancelRestart();
  endRestarts();
  refusalReported = false;
}

function cancelRestart(): void {
  if (restartTimer) clearTimeout(restartTimer);
  restartTimer = null;
}

/** End the restart series and, with it, its series of failures. */
function endRestarts(): void {
  restartDelay = null;
  startedAt = null;
  errorReported = false;
}

/** A frpc that has held for a tick since it was started ends an open restart series. */
function settleRestarts(): void {
  // Only an open one: outside it, a tick passing must not split a series of failed runs.
  if (restartDelay === null || startedAt === null) return;
  if (Date.now() - startedAt >= RESTART_HELD_MS) endRestarts();
}

function frpcEnded(): void {
  settleRestarts();
  startedAt = null;
  scheduleRestart();
}

/**
 * A restart is planned or queued behind the run in flight: frpc ended while it ran, so that
 * run is not the restart. A refreshNow() queued behind it says nothing about frpc.
 */
function restartDue(): boolean {
  return restartTimer !== null || !!inFlight?.restart;
}

/** Plan the restart of a frpc that ended, unless one is planned or nothing polls. */
function scheduleRestart(): void {
  if (!pollTimer || restartTimer) return;
  const delay = restartDelay ?? RESTART_FIRST_MS;
  restartDelay = Math.min(delay * 2, RESTART_MAX_MS);
  restartTimer = setTimeout(() => {
    restartTimer = null;
    // A reconciliation still in flight may have looked at frpc before it ended: queue after it.
    if (inFlight) inFlight.restart = true;
    void refreshNow();
  }, delay);
}

export async function startIfServerMode(): Promise<void> {
  stopPolling();
  if (!serverSession()) {
    _state.set({ ui: 'idle', status: null, mappings: [] });
    return;
  }
  const gen = activationGen;
  _state.update((s) => ({ ...s, ui: 'connecting' }));
  pollTimer = setInterval(() => void reconcile(gen), REFRESH_INTERVAL_MS);
  await reconcile(gen);
}

/** Reconcile now; while a reconciliation runs, once more after it. Never rejects. */
export function refreshNow(): Promise<void> {
  if (!pollTimer) return Promise.resolve();
  const gen = activationGen;
  const running = inFlight;
  if (running?.gen !== gen) return reconcile(gen);
  // stop() or a newer activation drops the follow-up.
  running.next ??= running.done.then(() => (gen === activationGen ? reconcile(gen) : undefined));
  return running.next;
}

/**
 * Reconnect now: the run this starts, or queues behind the one in flight, is the restart and
 * drops the planned one; should it fail, the next pause is 5 s. An open restart series stays
 * open, so its failures bring no second message. Without polling, nothing.
 */
export function reconnectNow(): Promise<void> {
  if (restartDelay !== null) restartDelay = RESTART_FIRST_MS;
  return refreshNow();
}

function reconcile(gen: number): Promise<void> {
  if (inFlight?.gen === gen) return inFlight.done;
  cancelRestart();
  const done: Promise<void> = reconcileOnce(gen).finally(() => {
    if (inFlight?.done === done) inFlight = null;
  });
  inFlight = { gen, done, next: null, restart: false };
  return done;
}

async function reconcileOnce(gen: number): Promise<void> {
  if (!serverSession()) {
    // A session that ended without stop() (a logout that bypasses it): end the polling here.
    if (gen === activationGen) stopPolling();
    return;
  }
  let refresh: TunnelRefresh;
  try {
    refresh = await bridge.refreshTunnel();
  } catch (err) {
    if (gen !== activationGen) return;
    // The backend leaves a running frpc untouched; only a first start that failed
    // leaves "connecting" behind.
    _state.update((s) =>
      s.ui === 'connecting' ? { ...s, ui: 'disconnected', status: { running: false } } : s,
    );
    // A failed tick while the restarted frpc holds is a new series and plans no restart; a
    // failed restart plans the next one after a longer pause, unless one already waits: a
    // planned one, or any run queued behind this one, which is then the restart.
    settleRestarts();
    if (!errorReported) {
      errorReported = true;
      reportError(tNow('error.tunnel', { message: errMsg(err) }));
    }
    if (restartDelay !== null && !inFlight?.next) scheduleRestart();
    return;
  }
  if (gen !== activationGen) {
    // Overtaken by stop() or a logout while in flight: a frpc started now belongs to no
    // activation. A newer activation, if any, owns the running frpc.
    if (!pollTimer && refresh.status.running) void bridge.stopTunnel().catch(() => {});
    return;
  }
  // A frpc that dies right after each start is one series, with one message.
  if (restartDelay === null) errorReported = false;
  // A run that sees frpc running starts its hold time: a new process always, any other only
  // without a known start (it survived a frpc-error). Not with a restart still due: then this
  // run may have seen frpc before it ended.
  const fresh = refresh.outcome === 'started' || refresh.outcome === 'restarted';
  if (refresh.status.running && !restartDue() && (fresh || startedAt === null)) {
    startedAt = Date.now();
  }
  const stopped = refresh.outcome === 'stopped';
  if (stopped) endRestarts(); // no STCP tunnel wants frpc: nothing left to restart
  if (refresh.refused == null) {
    refusalReported = false;
  } else if (!refusalReported) {
    refusalReported = true;
    reportError(tNow('error.tunnel.refused', { code: refresh.refused }));
  }
  let mappings: TunnelMapping[];
  try {
    mappings = await bridge.fetchTunnels();
  } catch {
    mappings = get(_state).mappings;
  }
  if (gen !== activationGen) return;
  if (stopped) {
    // An HTTPS tunnel runs without frpc: the connect flow resolves it through the mappings.
    _state.set({ ui: 'idle', status: refresh.status, mappings });
    return;
  }
  if (restartDue()) {
    // Its status may predate an end of frpc: the run due next brings the current one, and
    // until then "disconnected" stays.
    _state.update((s) => ({ ...s, mappings }));
    return;
  }
  _state.set({
    ui: refresh.status.running ? 'connected' : 'disconnected',
    status: refresh.status,
    mappings,
  });
}

export async function stop(): Promise<void> {
  stopPolling();
  try {
    await bridge.stopTunnel();
  } finally {
    _state.set({ ui: 'idle', status: null, mappings: [] });
  }
}

export function markTerminated(): void {
  _state.update((s) => ({ ...s, ui: 'disconnected', status: { running: false } }));
  frpcEnded();
}

// Taken as an end, too: should frpc run on after it, the restart finds it `unchanged`.
export function markError(message: string): void {
  _state.update((s) => ({ ...s, ui: 'disconnected', status: { running: false } }));
  frpcEnded(); // first: a frpc that held starts a new series, with a message of its own
  if (!errorReported) {
    errorReported = true;
    reportError(tNow('error.tunnel', { message }));
  }
}
