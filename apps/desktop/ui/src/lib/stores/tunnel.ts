// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tunnel store: holds TunnelStatus + tunnel mappings and keeps frpc in step with
// the visitor bundle. While a server session is active it reconciles right away and
// then every 60 s (refresh_tunnel starts, reloads, restarts or stops frpc) and
// reloads the mappings after each run. Activated by AppShell on login/mode switch,
// ended by stop(); reacts to the Tauri events frpc-terminated / frpc-error.

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
let inFlight: { gen: number; done: Promise<void>; next: Promise<void> | null } | null = null;
// One status-bar message per series of failed reconciliations; a success ends the series.
let errorReported = false;

function serverSession() {
  const { session, settings } = get(sessionStore);
  return session && settings?.mode === 'server' ? session : null;
}

function stopPolling(): void {
  activationGen++;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

export async function startIfServerMode(): Promise<void> {
  stopPolling();
  if (!serverSession()) {
    _state.set({ ui: 'idle', status: null, mappings: [] });
    return;
  }
  const gen = activationGen;
  errorReported = false;
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

function reconcile(gen: number): Promise<void> {
  if (inFlight?.gen === gen) return inFlight.done;
  const done: Promise<void> = reconcileOnce(gen).finally(() => {
    if (inFlight?.done === done) inFlight = null;
  });
  inFlight = { gen, done, next: null };
  return done;
}

async function reconcileOnce(gen: number): Promise<void> {
  const session = serverSession();
  if (!session) {
    // The logout button drops the session without stop(): end the polling here.
    if (gen === activationGen) stopPolling();
    return;
  }
  let refresh: TunnelRefresh;
  try {
    refresh = await bridge.refreshTunnel(session.serverUrl, session.token, session.username);
  } catch (err) {
    if (gen !== activationGen) return;
    // The backend leaves a running frpc untouched; only a first start that failed
    // leaves "connecting" behind.
    _state.update((s) =>
      s.ui === 'connecting' ? { ...s, ui: 'disconnected', status: { running: false } } : s,
    );
    if (!errorReported) {
      errorReported = true;
      reportError(tNow('error.tunnel', { message: errMsg(err) }));
    }
    return;
  }
  if (gen !== activationGen) {
    // Overtaken by stop() or a logout while in flight: a frpc started now belongs to no
    // activation. A newer activation, if any, owns the running frpc.
    if (!pollTimer && refresh.status.running) void bridge.stopTunnel().catch(() => {});
    return;
  }
  errorReported = false;
  if (refresh.outcome === 'stopped') {
    _state.set({ ui: 'idle', status: refresh.status, mappings: [] });
    return;
  }
  let mappings: TunnelMapping[];
  try {
    mappings = await bridge.fetchTunnels(session.serverUrl, session.token);
  } catch {
    mappings = get(_state).mappings;
  }
  if (gen !== activationGen) return;
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
}

export function markError(message: string): void {
  _state.update((s) => ({ ...s, ui: 'disconnected', status: { running: false } }));
  reportError(tNow('error.tunnel', { message }));
}
