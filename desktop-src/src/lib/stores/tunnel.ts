// Tunnel-Store: haelt TunnelStatus + Tunnel-Mappings, startet frpc auf Bedarf.
// Wird vom AppShell beim Login/Mode-Wechsel angestossen und reagiert auf
// Tauri-Events frpc-terminated / frpc-error.

import { writable, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { TunnelMapping, TunnelStatus } from '$lib/bridge/types';
import { sessionStore } from './session';
import { reportError } from './statusBar';

export type TunnelUiState = 'idle' | 'connecting' | 'connected' | 'disconnected';

interface TunnelStoreState {
  ui: TunnelUiState;
  status: TunnelStatus | null;
  mappings: TunnelMapping[];
}

const initial: TunnelStoreState = { ui: 'idle', status: null, mappings: [] };
const _state = writable<TunnelStoreState>(initial);
export const tunnel = { subscribe: _state.subscribe };

export function getMappings(): TunnelMapping[] {
  return get(_state).mappings;
}

export async function startIfServerMode(): Promise<void> {
  const { session, settings } = get(sessionStore);
  if (!session || !settings || settings.mode !== 'server') {
    _state.set({ ui: 'idle', status: null, mappings: [] });
    return;
  }

  _state.update((s) => ({ ...s, ui: 'connecting' }));
  try {
    const status = await bridge.startTunnel(
      session.serverUrl,
      session.token,
      session.username,
    );
    let mappings: TunnelMapping[] = [];
    try {
      mappings = await bridge.fetchTunnels(session.serverUrl, session.token);
    } catch {
      mappings = [];
    }
    _state.set({
      ui: status.running ? 'connected' : 'disconnected',
      status,
      mappings,
    });
  } catch (err) {
    _state.set({ ui: 'disconnected', status: { running: false }, mappings: [] });
    const msg = err instanceof Error ? err.message : String(err);
    reportError(`Tunnel: ${msg}`);
  }
}

export async function stop(): Promise<void> {
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
  reportError(`Tunnel: ${message}`);
}
