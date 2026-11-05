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

import { errMsg } from '$lib/utils/errors';
import { get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { ClientInfo, Connection } from '$lib/bridge/types';
import { connectionsApi } from '$lib/api/connections';
import { validateConnection } from '$lib/models/connection';
import { sessionStore } from './session';
import {
  connections as connectionsStore,
  upsert,
  patchInMemory,
  sessionsChanged,
} from './connections';
import { reportError, showStatus } from './statusBar';
import { getMappings } from './tunnel';
import { requestPassword } from './passwordPrompt';
import { closeEditor } from './editor';
import { tNow } from '$lib/i18n';

const isLinux =
  typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('linux');
const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

// Delay before showing the "RDP starting" status: a fast connection error cancels
// this timer, so waiting lets its real message surface instead of a stale "starting".
const RDP_STARTING_DELAY_MS = 800;

interface RdpAttempt {
  id: string;
  timer: ReturnType<typeof setTimeout> | null;
  errored: boolean;
}

const rdpAttempts = new Map<string, RdpAttempt>();

/** A session begun by a connect, to be ended where it was begun. */
interface OpenSession {
  mode: 'server' | 'local';
  connectionId: string;
  id: string;
}

// The session of each running RDP start by its correlationId, until its rdp-exit. A promise: a
// start that ends at once may report its exit before the session is written.
const rdpSessions = new Map<string, Promise<OpenSession | null>>();

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
  }, RDP_STARTING_DELAY_MS);
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

/** Ends the session of the RDP start `correlationId`; called from the rdp-exit Tauri event. */
export async function markRdpExit(correlationId: string): Promise<void> {
  const pending = rdpSessions.get(correlationId);
  if (!pending) return;
  rdpSessions.delete(correlationId);
  const open = await pending.catch(() => null);
  if (!open) return;
  try {
    if (open.mode === 'server') {
      const { session } = get(sessionStore);
      if (session) await connectionsApi.endSession(session, open.connectionId, open.id);
    } else {
      await bridge.endSession(open.id);
    }
    sessionsChanged();
  } catch {
    // The history then shows the session without an end; nothing the user could act on.
  }
}

let deviceCache: Promise<string | undefined> | null = null;

/**
 * This computer's name as the device of a server session: without control characters (the
 * server refuses them, and every connect would fail its touch) and at most 255 characters.
 */
function deviceName(): Promise<string | undefined> {
  deviceCache ??= bridge
    .deviceName()
    .then((name) => {
      const clean = [...(name ?? '')]
        .filter((ch) => ch.charCodeAt(0) > 0x1f && ch.charCodeAt(0) !== 0x7f)
        .join('')
        .trim()
        .slice(0, 255);
      return clean || undefined;
    })
    .catch(() => undefined);
  return deviceCache;
}

function passwordStoreEnabled(): boolean {
  const { settings } = get(sessionStore);
  return Boolean(settings?.storePasswords);
}

/**
 * Whether the prompt may offer "remember password" for `connection`. The keyring key holds the
 * connection's id; in server mode one the list does not hold yet (the editor's "Connect" before
 * "Save") has a client id the server replaces on save, so a password stored under it would
 * belong to no connection.
 */
function rememberAllowed(connection: Connection): boolean {
  const { settings } = get(sessionStore);
  if (settings?.mode !== 'server') return true;
  return get(connectionsStore).some((c) => c.id === connection.id);
}

/** Begins a session in the workspace's local history; `null` when it could not be written. */
async function startLocalSession(connectionId: string): Promise<OpenSession | null> {
  try {
    const started = await bridge.startSession(connectionId);
    return { mode: 'local', connectionId, id: started.id };
  } catch {
    return null;
  }
}

/**
 * Updates lastUsed and begins a session in a mode-specific way:
 *  - local:  upsert into local SQLite (persistent), session in the local history.
 *  - server: POST /api/connections/{id}/touch with this device -> memory patch with server
 *            response, session on the server.
 *  - sync:   memory patch only (sync URL is read-only, does not survive the next sync),
 *            session in the local history.
 * Returns the session begun, `null` when none could be.
 */
async function markConnectionUsed(connection: Connection): Promise<OpenSession | null> {
  const { settings, session } = get(sessionStore);
  const mode = settings?.mode ?? 'local';

  if (mode === 'server' && session) {
    try {
      const { sessionId, ...updated } = await connectionsApi.touch(
        session,
        connection.id,
        await deviceName(),
      );
      patchInMemory(updated);
      return sessionId ? { mode: 'server', connectionId: connection.id, id: sessionId } : null;
    } catch {
      patchInMemory({ ...connection, lastUsed: new Date().toISOString() });
      return null;
    }
  }

  if (mode === 'sync') {
    patchInMemory({ ...connection, lastUsed: new Date().toISOString() });
    return startLocalSession(connection.id);
  }

  const items = get(connectionsStore);
  const existing = items.find((c) => c.id === connection.id);
  const updated: Connection = {
    ...(existing ?? connection),
    lastUsed: new Date().toISOString(),
  };
  await upsert(updated);
  return startLocalSession(connection.id);
}

/**
 * Where `connection` is reached: Rust resolves it through a tunnel mapping (an admin's, or one on
 * a server assigned to the user) or, at 127.0.0.1/localhost and the server port of a visitor, to
 * the local port that visitor got.
 * `null` once the status bar shows why Rust refused it (a loopback port of another workspace's
 * tunnel, say): open_connection would refuse the same target, so nothing may ask for a password
 * or check the URL first.
 */
async function resolveTarget(connection: Connection): Promise<Connection | null> {
  try {
    return (await bridge.resolveConnection(connection, getMappings())).connection;
  } catch (err) {
    reportError(errMsg(err));
    return null;
  }
}

async function handleRdpAuth(
  connection: Connection,
  resolved: Connection,
  keepEditorOpen: boolean,
): Promise<boolean> {
  if (!isTauri) return false;

  if (passwordStoreEnabled()) {
    try {
      const pwState = await bridge.passwordState(connection);
      if (!pwState.canStore) return false;
      if (pwState.stored) {
        await performConnect(connection, resolved, keepEditorOpen, { useStoredPassword: true });
        return true;
      }
      const allowRemember = rememberAllowed(connection);
      const outcome = await requestPassword(connection, keepEditorOpen, allowRemember);
      if (outcome.cancelled) return true;
      const updated = outcome.updated ?? connection;
      let saved = false;
      if (allowRemember && outcome.remember && outcome.password) {
        try {
          await bridge.savePassword(updated, outcome.password);
          saved = true;
        } catch (err) {
          reportError(
            tNow('error.passwordStore', {
              message: errMsg(err),
            }),
          );
        }
      }
      // Resolve what the prompt returns: it carries the user and domain typed there, and the
      // visitors may have moved while the prompt waited. A saved password starts the stored way:
      // on Windows only that way hands it to mstsc (TERMSRV for the start); Rust drops a typed one
      // there and mstsc would ask a second time.
      const target = await resolveTarget(updated);
      if (target) {
        await performConnect(
          updated,
          target,
          keepEditorOpen,
          saved ? { useStoredPassword: true } : { password: outcome.password },
        );
      }
      return true;
    } catch (err) {
      reportError(`Password-Store: ${errMsg(err)}`);
    }
  }

  if (isLinux) {
    const outcome = await requestPassword(connection, keepEditorOpen, false);
    if (outcome.cancelled) return true;
    const updated = outcome.updated ?? connection;
    const target = await resolveTarget(updated);
    if (target) {
      await performConnect(updated, target, keepEditorOpen, { password: outcome.password });
    }
    return true;
  }

  return false;
}

export async function initiateConnect(
  connection: Connection,
  keepEditorOpen = false,
): Promise<void> {
  // Resolve before validating: the server's automatic web connections have no URL until a
  // visitor gives them one.
  const resolved = await resolveTarget(connection);
  if (!resolved) return;
  const validation = validateConnection(resolved);
  if (!validation.ok) {
    reportError(validation.message ?? tNow('error.invalidConnection'));
    return;
  }

  if (connection.kind === 'rdp') {
    const handled = await handleRdpAuth(connection, resolved, keepEditorOpen);
    if (handled) return;
  }

  await performConnect(connection, resolved, keepEditorOpen);
}

interface PerformOptions {
  password?: string;
  useStoredPassword?: boolean;
}

/**
 * The screen an RDP start hands to Rust, which sizes "Fit" and picks the HiDPI scale from it.
 * Read at each start, not once: the window may have moved to another screen since.
 */
function clientInfo(): ClientInfo {
  return {
    screenWidth: window.screen.width,
    screenHeight: window.screen.height,
    scaleFactor: window.devicePixelRatio || 1,
  };
}

/** Open `resolved`, the target of `connection`, the connection as listed. */
async function performConnect(
  connection: Connection,
  resolved: Connection,
  keepEditorOpen: boolean,
  options: PerformOptions = {},
): Promise<void> {
  const { password, useStoredPassword = false } = options;
  try {
    let rdpId: string | null = null;
    if (resolved.kind === 'rdp') {
      rdpId = startRdpAttempt();
      const cid = rdpId;
      const client = clientInfo();
      const promise = useStoredPassword
        ? bridge.openConnectionStored(resolved, connection, client, cid)
        : bridge.openConnection(resolved, password, client, cid);
      promise.catch((err: unknown) => {
        clearRdpAttempt(cid);
        // No client ran, so no rdp-exit comes: the session ends here.
        void markRdpExit(cid);
        reportError(errMsg(err));
      });
    } else if (useStoredPassword) {
      await bridge.openConnectionStored(resolved, connection);
    } else {
      await bridge.openConnection(resolved, password);
    }

    const used = markConnectionUsed(connection).then((open) => {
      if (open) sessionsChanged();
      return open;
    });
    if (rdpId !== null) rdpSessions.set(rdpId, used);
    await used;

    if (connection.kind === 'rdp') {
      if (rdpId !== null) scheduleRdpStatus(rdpId);
    } else {
      showStatus(tNow('status.connectionStarted'));
    }

    if (!keepEditorOpen) closeEditor();
  } catch (err) {
    reportError(errMsg(err));
  }
}
