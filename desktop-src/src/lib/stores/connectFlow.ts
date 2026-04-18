// Connect-Flow: orchestriert das Starten einer Verbindung.
// Bei RDP wird ggf. der Password-Store befragt oder ein Prompt gezeigt.
// Das Pattern mit monotonem rdpConnectId-Zaehler schuetzt vor Race-Conditions,
// wenn ein spaeter eintreffendes rdp-error-Event eine bereits laufende
// zweite Verbindung faelschlicherweise als fehlgeschlagen markieren wuerde.

import { get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { Connection } from '$lib/bridge/types';
import { validateConnection } from '$lib/models/connection';
import { sessionStore } from './session';
import { connections as connectionsStore, upsert } from './connections';
import { reportError, showStatus } from './statusBar';
import { getMappings } from './tunnel';
import { requestPassword } from './passwordPrompt';
import { closeEditor } from './editor';
import { tNow } from '$lib/i18n';

const isLinux = typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('linux');
const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

let rdpConnectId = 0;
let rdpPendingId: number | null = null;
let rdpErroredId: number | null = null;
let rdpStatusTimer: ReturnType<typeof setTimeout> | null = null;

function clearRdpStatusTimer(): void {
  if (rdpStatusTimer) {
    clearTimeout(rdpStatusTimer);
    rdpStatusTimer = null;
  }
}

function startRdpStatus(): number {
  rdpConnectId += 1;
  rdpPendingId = rdpConnectId;
  rdpErroredId = null;
  clearRdpStatusTimer();
  return rdpConnectId;
}

function scheduleRdpStatus(connectId: number): void {
  clearRdpStatusTimer();
  rdpStatusTimer = setTimeout(() => {
    if (rdpPendingId !== connectId || rdpErroredId === connectId) return;
    showStatus(tNow('status.rdpStarting'));
    rdpStatusTimer = null;
  }, 800);
}

/** Wird vom rdp-error Tauri-Event aufgerufen. */
export function markRdpError(message: string): void {
  clearRdpStatusTimer();
  if (rdpPendingId !== null) {
    rdpErroredId = rdpPendingId;
    rdpPendingId = null;
  }
  reportError(message);
}

function passwordStoreEnabled(): boolean {
  const { settings } = get(sessionStore);
  return Boolean(settings?.storePasswords);
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
          reportError(tNow('error.passwordStore', { message: err instanceof Error ? err.message : String(err) }));
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

export async function initiateConnect(connection: Connection, keepEditorOpen = false): Promise<void> {
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

    let rdpId: number | null = null;
    if (resolved.kind === 'rdp') {
      rdpId = startRdpStatus();
      const promise = useStoredPassword
        ? bridge.openConnectionStored(resolved)
        : bridge.openConnection(resolved, password);
      promise.catch((err: unknown) => {
        if (rdpId !== null) {
          clearRdpStatusTimer();
          if (rdpPendingId === rdpId) {
            rdpErroredId = rdpId;
            rdpPendingId = null;
          }
        }
        reportError(err instanceof Error ? err.message : String(err));
      });
    } else if (useStoredPassword) {
      await bridge.openConnectionStored(resolved);
    } else {
      await bridge.openConnection(resolved, password);
    }

    const items = get(connectionsStore);
    const existing = items.find((c) => c.id === connection.id);
    const updated: Connection = {
      ...(existing ?? connection),
      lastUsed: new Date().toISOString(),
    };
    await upsert(updated);

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
