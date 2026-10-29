// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Typed wrappers around tauri.invoke() for all backend commands.
//
// Each function maps 1:1 to a #[tauri::command] in
// apps/desktop/src-tauri/src/commands.rs. The signature types come from ./types.
//
// When adding/changing a command:
//   1. Adjust commands.rs + models.rs
//   2. Extend the main.rs invoke_handler list
//   3. Update ./types.ts if the payload changes
//   4. Add/adjust the function here

import { invoke as tauriInvoke, type InvokeArgs } from '@tauri-apps/api/core';
import { fromIpc } from '$lib/utils/errors';
import type {
  AnsibleTarget,
  AuthSession,
  ClientInfo,
  Connection,
  DeviceIdentity,
  HttpMethod,
  PasswordState,
  ResetOutcome,
  ResolvedConnection,
  Settings,
  TunnelMapping,
  TunnelRefresh,
  TunnelStatus,
  WorkspaceContext,
  WorkspaceDraft,
  WorkspaceList,
} from './types';

// Every refusal reaches the UI as an Error (R-0709): Tauri rejects with whatever the command
// serialised, an object or a string, and a raw object showed as "[object Object]".
async function invoke<T>(cmd: string, args?: InvokeArgs): Promise<T> {
  try {
    return await tauriInvoke<T>(cmd, args);
  } catch (raw) {
    throw fromIpc(raw);
  }
}

// ─────────────────────────── Persistence ──────────────────────────

export function loadConnections(): Promise<Connection[]> {
  return invoke<Connection[]>('load_connections');
}

export function saveConnections(connections: Connection[]): Promise<void> {
  return invoke('save_connections', { connections });
}

export function loadSettings(): Promise<Settings> {
  return invoke<Settings>('load_settings');
}

export function saveSettings(settings: Settings): Promise<void> {
  return invoke('save_settings', { settings });
}

// ─────────────────────────── Workspaces ───────────────────────────
// The launcher manages the workspaces; each one runs in a process of its own. A command
// for the launcher rejects in a workspace process and the other way round.

/** Which process this webview talks to: the launcher, or the workspace it serves. */
export function workspaceContext(): Promise<WorkspaceContext> {
  return invoke<WorkspaceContext>('workspace_context');
}

/** Launcher only: the workspaces, whether each is open, and the one used last. */
export function listWorkspaces(): Promise<WorkspaceList> {
  return invoke<WorkspaceList>('list_workspaces');
}

/** Launcher only: makes the workspace (no id) or edits the closed one; resolves to its id. */
export function saveWorkspace(draft: WorkspaceDraft): Promise<string> {
  return invoke<string>('save_workspace', { draft });
}

/**
 * Launcher only: deletes the closed workspace. A server workspace revokes its device first;
 * the outcome says how that went (as resetDeviceIdentity). Takes up to two minutes.
 */
export function deleteWorkspace(id: string): Promise<ResetOutcome> {
  return invoke<ResetOutcome>('delete_workspace', { id });
}

/**
 * Launcher only: opens the workspace in a process of its own and waits up to 10 s until it
 * runs; then the launcher ends, so on success the promise may never settle.
 */
export function openWorkspace(id: string): Promise<void> {
  return invoke('open_workspace', { id });
}

/** Workspace only: "Workspaces…" starts the launcher or brings up the one that runs. */
export function openLauncher(): Promise<void> {
  return invoke('open_launcher');
}

// ─────────────────────────── Diagnostics ──────────────────────────

/** Build a redacted diagnostics report and return the path of the written file. */
export function generateDiagnostics(): Promise<string> {
  return invoke<string>('generate_diagnostics');
}

// ─────────────────────────── Auth ─────────────────────────────────

// Starts the session in the Rust process: server, tokens and the certificate choice stay
// there. Every command that talks to the server as the user (api_proxy, the tunnel, the
// notification stream, …) acts for that session and fails with "Keine aktive Sitzung"
// without one.
export function login(
  serverUrl: string,
  username: string,
  password: string,
  allowSelfSigned?: boolean,
): Promise<AuthSession> {
  return invoke<AuthSession>('login', {
    serverUrl,
    username,
    password,
    allowSelfSigned,
  });
}

export function logout(): Promise<void> {
  return invoke('logout');
}

export function checkServerCert(serverUrl: string): Promise<boolean> {
  return invoke<boolean>('check_server_cert', { serverUrl });
}

// Forget the pinned (TOFU) certificate for a server so the next connection
// re-pins on first use — for recovering from a legitimate certificate rotation.
export function resetServerCertPin(serverUrl: string): Promise<void> {
  return invoke('reset_server_cert_pin', { serverUrl });
}

// Whether this device holds an enrolled mTLS identity — gates the
// "reset device identity" action in the settings UI.
export function isDeviceEnrolled(): Promise<boolean> {
  return invoke<boolean>('is_device_enrolled');
}

// Reset the enrolled mTLS identity AND the TOFU pin for a server — the recovery
// path after a server reinstall / PKI re-creation. The identity is revoked at the
// server first where it can be. The user must re-enroll after.
export function resetDeviceIdentity(serverUrl: string): Promise<ResetOutcome> {
  return invoke<ResetOutcome>('reset_device_identity', { serverUrl });
}

// SHA-256 fingerprint of the CA pinned at enrollment (access intermediate) —
// embedded as the agent's --ca-fp by the provisioning tab. Null until enrolled.
export function pinnedCaFingerprint(): Promise<string | null> {
  return invoke<string | null>('pinned_ca_fingerprint');
}

// Name (CN) and expiry of this device's enrolled certificate — the identity line in
// the settings. Null until enrolled; rejects when the stored certificate is unreadable.
export function deviceIdentity(): Promise<DeviceIdentity | null> {
  return invoke<DeviceIdentity | null>('device_identity');
}

// Decoupled enrollment (ADR 0003): enroll this device with a one-time token an
// admin minted out-of-band — without a prior login. Lets a brand-new client get
// its mTLS cert under enforced mTLS, where it can't reach the login on :443.
export function enrollWithToken(
  serverUrl: string,
  token: string,
  allowSelfSigned?: boolean,
): Promise<void> {
  return invoke('enroll_with_token', { serverUrl, token, allowSelfSigned });
}

// Enroll a long-lived browser certificate at the signed-in server and write it as a
// password-protected .p12 to `destPath` (chosen via the save dialog); resolves to the
// absolute path the user imports into their browser's certificate store (needed once
// mTLS is enforced).
export function exportBrowserP12(password: string, destPath: string): Promise<string> {
  return invoke<string>('export_browser_p12', { password, destPath });
}

// ─────────────────────────── Server API proxy ────────────────────

export function apiProxy<T = unknown>(method: HttpMethod, path: string, body?: string): Promise<T> {
  return invoke<T>('api_proxy', { method, path, body });
}

export function fetchConnectionsJwt(): Promise<Connection[]> {
  return invoke<Connection[]>('fetch_connections_jwt');
}

export function syncConnections(url: string): Promise<Connection[]> {
  return invoke<Connection[]>('sync_connections', { url });
}

// ─────────────────────────── Connect-Flow ─────────────────────────

export function openConnection(
  connection: Connection,
  password?: string,
  client?: ClientInfo,
  correlationId?: string,
): Promise<void> {
  return invoke('open_connection', { connection, password, client, correlationId });
}

// credentialConnection: the connection as listed, before a tunnel resolved it to
// 127.0.0.1:<visitor port>. The stored password is keyed by its host and port.
export function openConnectionStored(
  connection: Connection,
  credentialConnection?: Connection,
  client?: ClientInfo,
  correlationId?: string,
): Promise<void> {
  return invoke('open_connection_stored', {
    connection,
    credentialConnection,
    client,
    correlationId,
  });
}

export function resolveConnection(
  connection: Connection,
  tunnels: TunnelMapping[],
): Promise<ResolvedConnection> {
  return invoke<ResolvedConnection>('resolve_connection', { connection, tunnels });
}

// ─────────────────────────── Password keychain ───────────────────

export function passwordState(connection: Connection): Promise<PasswordState> {
  return invoke<PasswordState>('password_state', { connection });
}

export function savePassword(connection: Connection, password: string): Promise<void> {
  return invoke('save_password', { connection, password });
}

export function deletePassword(connection: Connection): Promise<void> {
  return invoke('delete_password', { connection });
}

// ─────────────────────────── Tunnel (frpc) ────────────────────────

export function startTunnel(): Promise<TunnelStatus> {
  return invoke<TunnelStatus>('start_tunnel');
}

export function refreshTunnel(): Promise<TunnelRefresh> {
  return invoke<TunnelRefresh>('refresh_tunnel');
}

export function stopTunnel(): Promise<void> {
  return invoke('stop_tunnel');
}

export function tunnelStatus(): Promise<TunnelStatus> {
  return invoke<TunnelStatus>('tunnel_status');
}

export function fetchTunnels(): Promise<TunnelMapping[]> {
  return invoke<TunnelMapping[]>('fetch_tunnels');
}

// ─────────────────────────── Ansible ──────────────────────────────

// The backend loads file name and content of the playbook from the signed-in server itself.
export function ansibleRun(playbookId: string, targets: AnsibleTarget[]): Promise<void> {
  return invoke('ansible_run', { playbookId, targets });
}

// ─────────────────────────── Notifications (SSE) ──────────────────

// Open the long-lived SSE notification stream (tunnelled through Rust because the
// WebView can't EventSource against the self-signed server). The Rust side emits
// a `notification` Tauri event whenever a new notification arrives.
export function startNotificationStream(): Promise<void> {
  return invoke('start_notification_stream');
}

export function stopNotificationStream(): Promise<void> {
  return invoke('stop_notification_stream');
}

export type { Connection, Settings, AuthSession, TunnelStatus, TunnelMapping, ResetOutcome };
