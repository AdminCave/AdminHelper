// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Workspace store (R-0431): which process this window talks to, the launcher or the process
// of one workspace, and in the launcher the workspaces the picker lists. Every workspace runs
// in a process of its own; the launcher makes, edits, deletes and opens them, and a
// workspace window brings the launcher back ("Workspaces…").

import { writable } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type {
  ResetOutcome,
  WorkspaceContext,
  WorkspaceDraft,
  WorkspaceList,
} from '$lib/bridge/types';

const _context = writable<WorkspaceContext | null>(null);
const _list = writable<WorkspaceList | null>(null);

/** The launcher, or the workspace of this window; null until loadContext succeeds. */
export const context = { subscribe: _context.subscribe };
/** Launcher only: the workspaces as the last refresh listed them; null before the first. */
export const list = { subscribe: _list.subscribe };

/** Asks Rust which process this window talks to; hydrate (session.ts) calls it at start. */
export async function loadContext(): Promise<void> {
  _context.set(await bridge.workspaceContext());
}

/** Launcher only: lists the workspaces anew. */
export async function refresh(): Promise<void> {
  _list.set(await bridge.listWorkspaces());
}

/** Launcher only: makes the workspace (no id) or edits the closed one; resolves to its id. */
export async function save(draft: WorkspaceDraft): Promise<string> {
  const id = await bridge.saveWorkspace(draft);
  await refresh();
  return id;
}

/** Launcher only: deletes the closed workspace; resolves to how revoking its device went. */
export async function remove(id: string): Promise<ResetOutcome> {
  const outcome = await bridge.deleteWorkspace(id);
  await refresh();
  return outcome;
}

/**
 * Launcher only: opens the workspace in a process of its own. Once it runs the launcher
 * ends, so on success the promise may never settle.
 */
export function open(id: string): Promise<void> {
  return bridge.openWorkspace(id);
}

/** Workspace only: brings up the launcher ("Workspaces…"). */
export function openLauncher(): Promise<void> {
  return bridge.openLauncher();
}
