// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Infrastructure store: the server inventory behind the server-centric hub.
// Loads servers via the server API, holds the list search + the selected server,
// and drives the create/edit/delete server modal. Server mode only — the page
// that uses it is gated like monitoring/ansible.

import { writable, derived, get } from 'svelte/store';
import { sessionStore } from './session';
import { reportError, showStatus } from './statusBar';
import { serversApi } from '$lib/api/servers';
import { tNow } from '$lib/i18n';
import type { Server, ServerInput } from '$lib/api/types';

interface InfraState {
  servers: Server[];
  loading: boolean;
  search: string;
  selectedServerId: string | null;
}

const initial: InfraState = {
  servers: [],
  loading: false,
  search: '',
  selectedServerId: null,
};

const _state = writable<InfraState>(initial);

export const infra = { subscribe: _state.subscribe };
export const infraServers = derived(_state, ($s) => $s.servers);
export const infraLoading = derived(_state, ($s) => $s.loading);
export const infraSearch = derived(_state, ($s) => $s.search);
export const infraSelectedId = derived(_state, ($s) => $s.selectedServerId);
export const infraSelectedServer = derived(
  _state,
  ($s) => $s.servers.find((srv) => srv.id === $s.selectedServerId) ?? null,
);

// ── Server editor modal state ────────────────────────────────────────────────
interface ServerEditorState {
  open: boolean;
  target: Server | null;
}
const _editor = writable<ServerEditorState>({ open: false, target: null });
export const serverEditor = { subscribe: _editor.subscribe };

export function openServerEditor(target: Server | null = null): void {
  _editor.set({ open: true, target });
}

export function closeServerEditor(): void {
  _editor.set({ open: false, target: null });
}

// ── List interaction ─────────────────────────────────────────────────────────
export function setInfraSearch(value: string): void {
  _state.update((s) => ({ ...s, search: value }));
}

export function setSelectedServer(id: string | null): void {
  _state.update((s) => ({ ...s, selectedServerId: id }));
}

function requireSession() {
  return get(sessionStore).session;
}

function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// ── Data + mutations ─────────────────────────────────────────────────────────
export async function loadServers(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  _state.update((s) => ({ ...s, loading: true }));
  try {
    const result = await serversApi.list(session);
    const servers = Array.isArray(result) ? result : [];
    _state.update((s) => ({
      ...s,
      servers,
      loading: false,
      // Drop a selection that no longer exists after the reload.
      selectedServerId: servers.some((srv) => srv.id === s.selectedServerId)
        ? s.selectedServerId
        : null,
    }));
  } catch (err) {
    _state.update((s) => ({ ...s, servers: [], loading: false }));
    reportError(tNow('infra.error.load', { message: errMsg(err) }));
  }
}

export async function saveServer(input: ServerInput, id: string | null): Promise<boolean> {
  const session = requireSession();
  if (!session) return false;
  try {
    if (id) {
      await serversApi.update(session, id, input);
      showStatus(tNow('infra.status.serverUpdated'));
    } else {
      const created = await serversApi.create(session, input);
      showStatus(tNow('infra.status.serverCreated'));
      if (created?.id) _state.update((s) => ({ ...s, selectedServerId: created.id }));
    }
    await loadServers();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export async function deleteServer(id: string): Promise<boolean> {
  const session = requireSession();
  if (!session) return false;
  try {
    await serversApi.remove(session, id);
    showStatus(tNow('infra.status.serverDeleted'));
    _state.update((s) => ({
      ...s,
      selectedServerId: s.selectedServerId === id ? null : s.selectedServerId,
    }));
    await loadServers();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export function activateInfra(): void {
  void loadServers();
}
