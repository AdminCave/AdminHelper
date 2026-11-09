// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Ansible store: 3-step wizard (playbook -> targets -> run).
// Loads playbooks + servers from the server API and starts the run: in a tab of the embedded
// terminal when SSH opens there, else in the terminal of the OS (R-1073); either as a dry run
// (`--check`) when chosen. Each server is reached like Verbinden reaches it: over its SSH
// connection, resolved through the tunnel (R-1202).

import { errMsg } from '$lib/utils/errors';
import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { currentSession, sessionStore } from './session';
import { openAnsible } from './terminals';
import { connections } from './connections';
import { getMappings } from './tunnel';
import { SSH_CONSOLE_DEFAULT } from '$lib/models/settings';
import { reportError, showStatus } from './statusBar';
import { ansibleApi } from '$lib/api/ansible';
import {
  ansibleConnectionOf,
  buildAnsibleTargets,
  groupServersByTag,
  sshConnectionsOf,
  visitorMissing,
} from '$lib/models/ansible';
import { tNow } from '$lib/i18n';
import type { Playbook, Server } from '$lib/api/types';
import type { Connection } from '$lib/bridge/types';

export type AnsibleTargetMode = 'servers' | 'tags';

interface AnsibleState {
  playbooks: Playbook[];
  servers: Server[];
  selectedPlaybookId: string | null;
  selectedServerIds: Set<string>;
  targetMode: AnsibleTargetMode;
  loading: boolean;
  running: boolean;
  /** Run as a dry run (`--check`). */
  check: boolean;
  loadError: string | null;
  /** The SSH connection chosen per server id, for a server with more than one. */
  connectionChoice: Record<string, string>;
}

const initial: AnsibleState = {
  playbooks: [],
  servers: [],
  selectedPlaybookId: null,
  selectedServerIds: new Set<string>(),
  targetMode: 'servers',
  loading: false,
  running: false,
  check: false,
  loadError: null,
  connectionChoice: {},
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
export const ansibleCheck = derived(_state, ($s) => $s.check);

export const ansibleTagGroups = derived(_state, ($s) => groupServersByTag($s.servers));

/** Per server id its SSH connections (by name) and the one Ansible takes, `null` without one. */
export const ansibleServerConnections = derived([_state, connections], ([$s, $connections]) => {
  const byServer: Record<string, { options: Connection[]; chosen: Connection | null }> = {};
  for (const server of $s.servers) {
    byServer[server.id] = {
      options: sshConnectionsOf(server, $connections),
      chosen: ansibleConnectionOf(server, $connections, $s.connectionChoice),
    };
  }
  return byServer;
});
export const ansibleSelectedPlaybook = derived(
  _state,
  ($s) => $s.playbooks.find((p) => p.id === $s.selectedPlaybookId) ?? null,
);
export const ansibleCanRun = derived(
  _state,
  ($s) => $s.selectedPlaybookId !== null && $s.selectedServerIds.size > 0 && !$s.running,
);

export async function loadAnsibleData(): Promise<void> {
  const session = currentSession();
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
    const msg = errMsg(err);
    _state.update((s) => ({ ...s, loading: false, loadError: msg }));
  }
}

/** Refreshes only the playbook list (after authoring), leaving the wizard's
 * selection and the server list untouched. */
export async function reloadPlaybooks(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const playbooks = await ansibleApi.fetchPlaybooks(session);
    _state.update((s) => ({ ...s, playbooks: Array.isArray(playbooks) ? playbooks : [] }));
  } catch (err) {
    reportError(errMsg(err));
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

export function chooseConnection(serverId: string, connectionId: string): void {
  _state.update((s) => ({
    ...s,
    connectionChoice: { ...s.connectionChoice, [serverId]: connectionId },
  }));
}

/**
 * The resolved SSH connection per id of `servers` that has one; `null` once the status bar says
 * why a server cannot be reached: Rust refused the target, or its tunnel visitor does not run.
 * No fallback to the hostname there, it may lead elsewhere (R-1202).
 */
async function reachServers(
  servers: Server[],
  choice: Record<string, string>,
): Promise<Map<string, Connection> | null> {
  const all = get(connections);
  const mappings = getMappings();
  const reached = new Map<string, Connection>();
  for (const server of servers) {
    const connection = ansibleConnectionOf(server, all, choice);
    if (!connection) continue;
    try {
      const resolved = await bridge.resolveConnection(connection, mappings);
      if (visitorMissing(connection, resolved, mappings)) {
        reportError(tNow('ansible.run.noVisitor', { name: server.name }));
        return null;
      }
      reached.set(server.id, resolved.connection);
    } catch (err) {
      reportError(tNow('ansible.run.unreachable', { name: server.name, message: errMsg(err) }));
      return null;
    }
  }
  return reached;
}

export function setCheck(check: boolean): void {
  _state.update((s) => ({ ...s, check }));
}

export function clearSelection(): void {
  _state.set({ ...initial, selectedServerIds: new Set() });
}

export async function runPlaybook(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  const state = get(_state);
  const playbook = state.playbooks.find((p) => p.id === state.selectedPlaybookId);
  if (!playbook) return;
  if (state.selectedServerIds.size === 0) return;

  if (state.running) return;

  // Set before the first await: resolving the targets takes an IPC per server, and a second
  // click meanwhile would start a second run against the same servers.
  _state.update((s) => ({ ...s, running: true }));
  try {
    const selectedServers = state.servers.filter((s) => state.selectedServerIds.has(s.id));
    const reached = await reachServers(selectedServers, state.connectionChoice);
    if (!reached) return;
    const targets = buildAnsibleTargets(selectedServers, reached);

    const { check } = state;
    const sshConsole = get(sessionStore).settings?.sshConsole ?? SSH_CONSOLE_DEFAULT;
    if (sshConsole === 'embedded') {
      // The tab shows how the start goes; a failure is in the status bar already.
      await openAnsible(playbook.id, playbook.name, targets, check);
      return;
    }

    try {
      await bridge.ansibleRun(playbook.id, targets, check);
      showStatus(tNow('status.ansibleStarted', { name: playbook.name }));
    } catch (err) {
      reportError(errMsg(err));
    }
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
