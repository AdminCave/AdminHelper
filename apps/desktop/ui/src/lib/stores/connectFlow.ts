// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Connect flow: orchestrates starting a connection.
// For RDP the password store may be queried or a prompt shown.
//
// Race-condition protection: each RDP attempt gets a UUID that is passed to the
// Tauri bridge and sent along in every rdp-error event.
// markRdpError filters by the UUID so that late errors of an aborted
// connection do not mark a concurrently running new connection as failed.

import { get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { Connection } from '$lib/bridge/types';
import { validateConnection } from '$lib/models/connection';
import { sessionStore } from './session';
import { connections as connectionsStore, upsert, patchInMemory } from './connections';
import { reportError, showStatus } from './statusBar';
import { getMappings } from './tunnel';
import { requestPassword } from './passwordPrompt';
import { closeEditor } from './editor';
import { tNow } from '$lib/i18n';

const isLinux =
  typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('linux');
const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

interface RdpAttempt {
  id: string;
  timer: ReturnType<typeof setTimeout> | null;
  errored: boolean;
}

const rdpAttempts = new Map<string, RdpAttempt>();

function newCorrelationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `rdp-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function startRdpAttempt(): string {
  const id = newCorrelationId();
  rdpAttempts.set(id, { id, timer: null, errored: false });
  return id;
}

function scheduleRdpStatus(id: string): void {
  const attempt = rdpAttempts.get(id);
  if (!attempt) return;
  if (attempt.timer) clearTimeout(attempt.timer);
  attempt.timer = setTimeout(() => {
    const a = rdpAttempts.get(id);
    if (!a || a.errored) return;
    showStatus(tNow('status.rdpStarting'));
    rdpAttempts.delete(id);
  }, 800);
}

function clearRdpAttempt(id: string): void {
  const attempt = rdpAttempts.get(id);
  if (attempt?.timer) clearTimeout(attempt.timer);
  rdpAttempts.delete(id);
}

/**
 * Called from the rdp-error Tauri event. correlationId == null for legacy
 * events without an ID -> all running attempts are marked as errored (old
 * semantics). With an ID only the corresponding attempt is affected.
 */
export function markRdpError(correlationId: string | null, message: string): void {
  if (correlationId) {
    const attempt = rdpAttempts.get(correlationId);
    if (attempt) {
      if (attempt.timer) clearTimeout(attempt.timer);
      attempt.errored = true;
      rdpAttempts.delete(correlationId);
    }
  } else {
    for (const attempt of rdpAttempts.values()) {
      if (attempt.timer) clearTimeout(attempt.timer);
      attempt.errored = true;
    }
    rdpAttempts.clear();
  }
  reportError(message);
}

function passwordStoreEnabled(): boolean {
  const { settings } = get(sessionStore);
  return Boolean(settings?.storePasswords);
}

/**
 * Updates lastUsed in a mode-specific way:
 *  - local:  upsert into local SQLite (persistent).
 *  - server: POST /api/connections/{id}/touch -> memory patch with server response.
 *  - sync:   memory patch only (sync URL is read-only, does not survive the next sync).
 */
async function markConnectionUsed(connection: Connection): Promise<void> {
  const { settings, session } = get(sessionStore);
  const mode = settings?.mode ?? 'local';

  if (mode === 'server' && session) {
    try {
      const updated = await bridge.apiProxy<Connection>(
        session.serverUrl,
        session.token,
        'POST',
        `/api/connections/${encodeURIComponent(connection.id)}/touch`,
        undefined,
        settings?.allowSelfSignedCerts,
      );
      patchInMemory(updated);
    } catch {
      patchInMemory({ ...connection, lastUsed: new Date().toISOString() });
    }
    return;
  }

  if (mode === 'sync') {
    patchInMemory({ ...connection, lastUsed: new Date().toISOString() });
    return;
  }

  const items = get(connectionsStore);
  const existing = items.find((c) => c.id === connection.id);
  const updated: Connection = {
    ...(existing ?? connection),
    lastUsed: new Date().toISOString(),
  };
  await upsert(updated);
}

async function handleRdpAuth(connection: Connection, keepEditorOpen: boolean): Promise<boolean> {
  if (!isTauri) return false;

  if (passwordStoreEnabled()) {
    try {
      const pwState = await bridge.passwordState(connection);
      if (!pwState.canStore) return false;
      if (pwState.stored) {
        await performConnect(connection, keepEditorOpen, { useStoredPassword: true });
        return true;
      }
      const outcome = await requestPassword(connection, keepEditorOpen, true);
      if (outcome.cancelled) return true;
      const updated = outcome.updated ?? connection;
      if (outcome.remember && outcome.password) {
        try {
          await bridge.savePassword(updated, outcome.password);
        } catch (err) {
          reportError(
            tNow('error.passwordStore', {
              message: err instanceof Error ? err.message : String(err),
            }),
          );
        }
      }
      await performConnect(updated, keepEditorOpen, { password: outcome.password });
      return true;
    } catch (err) {
      reportError(`Password-Store: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (isLinux) {
    const outcome = await requestPassword(connection, keepEditorOpen, false);
    if (outcome.cancelled) return true;
    const updated = outcome.updated ?? connection;
    await performConnect(updated, keepEditorOpen, { password: outcome.password });
    return true;
  }

  return false;
}

export async function initiateConnect(
  connection: Connection,
  keepEditorOpen = false,
): Promise<void> {
  const validation = validateConnection(connection);
  if (!validation.ok) {
    reportError(validation.message ?? tNow('error.invalidConnection'));
    return;
  }

  if (connection.kind === 'rdp') {
    const handled = await handleRdpAuth(connection, keepEditorOpen);
    if (handled) return;
  }

  await performConnect(connection, keepEditorOpen);
}

interface PerformOptions {
  password?: string;
  useStoredPassword?: boolean;
}

export async function performConnect(
  connection: Connection,
  keepEditorOpen: boolean,
  options: PerformOptions = {},
): Promise<void> {
  const { password, useStoredPassword = false } = options;
  try {
    let resolved: Connection = connection;
    const mappings = getMappings();
    if (mappings.length > 0) {
      try {
        const res = await bridge.resolveConnection(connection, mappings);
        resolved = res.connection;
      } catch {
        // fallback to unresolved
      }
    }

    let rdpId: string | null = null;
    if (resolved.kind === 'rdp') {
      rdpId = startRdpAttempt();
      const cid = rdpId;
      const promise = useStoredPassword
        ? bridge.openConnectionStored(resolved, undefined, cid)
        : bridge.openConnection(resolved, password, undefined, cid);
      promise.catch((err: unknown) => {
        clearRdpAttempt(cid);
        reportError(err instanceof Error ? err.message : String(err));
      });
    } else if (useStoredPassword) {
      await bridge.openConnectionStored(resolved);
    } else {
      await bridge.openConnection(resolved, password);
    }

    await markConnectionUsed(connection);

    if (connection.kind === 'rdp') {
      if (rdpId !== null) scheduleRdpStatus(rdpId);
    } else {
      showStatus(tNow('status.connectionStarted'));
    }

    if (!keepEditorOpen) closeEditor();
  } catch (err) {
    reportError(err instanceof Error ? err.message : String(err));
  }
}
