// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Workspace store (R-0431): which process this window talks to, the launcher or the process
// of one workspace, and in the launcher the workspaces the picker lists. Every workspace runs
// in a process of its own; the launcher makes, edits, deletes and opens them, and a
// workspace window brings the launcher back ("Workspaces…").

import { get, writable } from 'svelte/store';
import * as bridge from '$lib/bridge';
import { errMsg } from '$lib/utils/errors';
import type {
  ResetOutcome,
  WorkspaceContext,
  WorkspaceDraft,
  WorkspaceList,
} from '$lib/bridge/types';

const _context = writable<WorkspaceContext | null>(null);
const _list = writable<WorkspaceList | null>(null);
const _listError = writable<string | null>(null);

/** The launcher, or the workspace of this window; null until loadContext succeeds. */
export const context = { subscribe: _context.subscribe };
/** Launcher only: the workspaces as the last refresh listed them; null before the first. */
export const list = { subscribe: _list.subscribe };
/** Launcher only: why the last refresh failed, as the user reads it; null once one succeeds. */
export const listError = { subscribe: _listError.subscribe };

/** Asks Rust which process this window talks to; hydrate (session.ts) calls it at start. */
export async function loadContext(): Promise<void> {
  _context.set(await bridge.workspaceContext());
}

/**
 * Workspace only: loads the context anew while its workspace has no URL. A sign-in saved or a
 * registration of this device may just have given it its first, and the context names it only
 * once loaded anew. Never rejects: what fails here is a URL the window shows from the next
 * start on.
 */
export async function reloadContextForUrl(): Promise<void> {
  const workspace = get(_context)?.workspace;
  if (!workspace || workspace.url) return;
  try {
    await loadContext();
  } catch (err) {
    console.error('workspace context failed', err);
  }
}

/**
 * Launcher only: lists the workspaces anew. Never rejects: a failure goes to listError and the
 * list stays as it was, so a save or a delete that went through does not read as failed when
 * only the listing after it does (a second click would make the workspace twice).
 */
export async function refresh(): Promise<void> {
  try {
    _list.set(await bridge.listWorkspaces());
    _listError.set(null);
  } catch (err) {
    _listError.set(errMsg(err));
  }
}

/**
 * Launcher only: makes the workspace (no id) or edits the closed one; resolves to its id. Rejects
 * only when Rust does not save it; the listing after it reports to listError.
 */
export async function save(draft: WorkspaceDraft): Promise<string> {
  const id = await bridge.saveWorkspace(draft);
  await refresh();
  return id;
}

/**
 * Launcher only: deletes the closed workspace; resolves to how revoking its device went. Rejects
 * only when Rust does not delete it; the listing after it reports to listError.
 */
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
