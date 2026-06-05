// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Ansible store: 3-step wizard (playbook -> targets -> run).
// Loads playbooks + servers from the server API and starts the local terminal runner.

import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { sessionStore } from './session';
import { reportError, showStatus } from './statusBar';
import { ansibleApi } from '$lib/api/ansible';
import { buildAnsibleTargets, groupServersByTag } from '$lib/models/ansible';
import { tNow } from '$lib/i18n';
import type { Playbook, Server } from '$lib/api/types';

export type AnsibleTargetMode = 'servers' | 'tags';

interface AnsibleState {
  playbooks: Playbook[];
  servers: Server[];
  selectedPlaybookId: string | null;
  selectedServerIds: Set<string>;
  targetMode: AnsibleTargetMode;
  loading: boolean;
  running: boolean;
  loadError: string | null;
}

const initial: AnsibleState = {
  playbooks: [],
  servers: [],
  selectedPlaybookId: null,
  selectedServerIds: new Set<string>(),
  targetMode: 'servers',
  loading: false,
  running: false,
  loadError: null,
};

const _state = writable<AnsibleState>(initial);

export const ansibleState = { subscribe: _state.subscribe };
export const ansiblePlaybooks = derived(_state, ($s) => $s.playbooks);
export const ansibleServers = derived(_state, ($s) => $s.servers);
export const ansibleSelectedPlaybookId = derived(_state, ($s) => $s.selectedPlaybookId);
export const ansibleSelectedServerIds = derived(_state, ($s) => $s.selectedServerIds);
export const ansibleTargetMode = derived(_state, ($s) => $s.targetMode);
export const ansibleLoading = derived(_state, ($s) => $s.loading);
export const ansibleRunning = derived(_state, ($s) => $s.running);
export const ansibleLoadError = derived(_state, ($s) => $s.loadError);

export const ansibleTagGroups = derived(_state, ($s) => groupServersByTag($s.servers));
export const ansibleSelectedPlaybook = derived(
  _state,
  ($s) => $s.playbooks.find((p) => p.id === $s.selectedPlaybookId) ?? null,
);
export const ansibleCanRun = derived(
  _state,
  ($s) => $s.selectedPlaybookId !== null && $s.selectedServerIds.size > 0 && !$s.running,
);

function requireSession() {
  const { session } = get(sessionStore);
  return session;
}

export async function loadAnsibleData(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  _state.update((s) => ({ ...s, loading: true, loadError: null }));
  try {
    const [playbooks, servers] = await Promise.all([
      ansibleApi.fetchPlaybooks(session),
      ansibleApi.fetchServers(session),
    ]);
    _state.update((s) => ({
      ...s,
      playbooks: Array.isArray(playbooks) ? playbooks : [],
      servers: Array.isArray(servers) ? servers : [],
      loading: false,
    }));
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    _state.update((s) => ({ ...s, loading: false, loadError: msg }));
  }
}

export function selectPlaybook(id: string | null): void {
  _state.update((s) => ({ ...s, selectedPlaybookId: id }));
}

export function setTargetMode(mode: AnsibleTargetMode): void {
  _state.update((s) => ({ ...s, targetMode: mode }));
}

export function toggleServer(id: string): void {
  _state.update((s) => {
    const next = new Set(s.selectedServerIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return { ...s, selectedServerIds: next };
  });
}

export function toggleTag(tag: string): void {
  _state.update((s) => {
    const groups = groupServersByTag(s.servers);
    const ids = (groups[tag] ?? []).map((srv) => srv.id);
    const allSelected = ids.every((id) => s.selectedServerIds.has(id));
    const next = new Set(s.selectedServerIds);
    if (allSelected) ids.forEach((id) => next.delete(id));
    else ids.forEach((id) => next.add(id));
    return { ...s, selectedServerIds: next };
  });
}

export function clearSelection(): void {
  _state.set({ ...initial, selectedServerIds: new Set() });
}

export async function runPlaybook(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  const state = get(_state);
  const playbook = state.playbooks.find((p) => p.id === state.selectedPlaybookId);
  if (!playbook) return;
  if (state.selectedServerIds.size === 0) return;

  const selectedServers = state.servers.filter((s) => state.selectedServerIds.has(s.id));
  const targets = buildAnsibleTargets(selectedServers);

  _state.update((s) => ({ ...s, running: true }));
  try {
    const { content } = await ansibleApi.fetchContent(session, playbook.id);
    const inventoryPath = await bridge.ansibleGenerateInventory(targets);
    const playbookPath = await bridge.ansibleWritePlaybook(playbook.filename, content);
    await bridge.ansibleLaunch(inventoryPath, playbookPath);
    showStatus(tNow('status.ansibleStarted', { name: playbook.name }));
  } catch (err) {
    reportError(err instanceof Error ? err.message : String(err));
  } finally {
    _state.update((s) => ({ ...s, running: false }));
  }
}

export function activateAnsible(): void {
  _state.update((s) => ({
    ...s,
    selectedPlaybookId: null,
    selectedServerIds: new Set<string>(),
  }));
  void loadAnsibleData();
}
