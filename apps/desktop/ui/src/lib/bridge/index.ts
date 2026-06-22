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

import { invoke } from '@tauri-apps/api/core';
import type {
  AnsibleTarget,
  AuthSession,
  ClientInfo,
  Connection,
  HttpMethod,
  PasswordState,
  ResolvedConnection,
  Settings,
  TunnelMapping,
  TunnelStatus,
} from './types';

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

// ─────────────────────────── Diagnostics ──────────────────────────

/** Build a redacted diagnostics report and return the path of the written file. */
export function generateDiagnostics(): Promise<string> {
  return invoke<string>('generate_diagnostics');
}

// ─────────────────────────── Auth ─────────────────────────────────

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
// path after a server reinstall / PKI re-creation. The user must re-enroll after.
export function resetDeviceIdentity(serverUrl: string): Promise<void> {
  return invoke('reset_device_identity', { serverUrl });
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

// Enroll a long-lived browser certificate and write it as a password-protected
// .p12 to `destPath` (chosen via the save dialog); resolves to the absolute path
// the user imports into their browser's certificate store (needed once mTLS is
// enforced).
export function exportBrowserP12(
  serverUrl: string,
  token: string,
  password: string,
  destPath: string,
  allowSelfSigned?: boolean,
): Promise<string> {
  return invoke<string>('export_browser_p12', {
    serverUrl,
    token,
    password,
    destPath,
    allowSelfSigned,
  });
}

// ─────────────────────────── Server API proxy ────────────────────

export function apiProxy<T = unknown>(
  serverUrl: string,
  token: string,
  method: HttpMethod,
  path: string,
  body?: string,
  allowSelfSigned?: boolean,
): Promise<T> {
  return invoke<T>('api_proxy', {
    serverUrl,
    token,
    method,
    path,
    body,
    allowSelfSigned,
  });
}

export function fetchConnectionsJwt(serverUrl: string, token: string): Promise<Connection[]> {
  return invoke<Connection[]>('fetch_connections_jwt', { serverUrl, token });
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

export function openConnectionStored(
  connection: Connection,
  client?: ClientInfo,
  correlationId?: string,
): Promise<void> {
  return invoke('open_connection_stored', { connection, client, correlationId });
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

export function startTunnel(
  serverUrl: string,
  token: string,
  username: string,
): Promise<TunnelStatus> {
  return invoke<TunnelStatus>('start_tunnel', { serverUrl, token, username });
}

export function stopTunnel(): Promise<void> {
  return invoke('stop_tunnel');
}

export function tunnelStatus(): Promise<TunnelStatus> {
  return invoke<TunnelStatus>('tunnel_status');
}

export function fetchTunnels(serverUrl: string, token: string): Promise<TunnelMapping[]> {
  return invoke<TunnelMapping[]>('fetch_tunnels', { serverUrl, token });
}

// ─────────────────────────── Ansible ──────────────────────────────

export function ansibleGenerateInventory(servers: AnsibleTarget[]): Promise<string> {
  return invoke<string>('ansible_generate_inventory', { servers });
}

export function ansibleWritePlaybook(filename: string, content: string): Promise<string> {
  return invoke<string>('ansible_write_playbook', { filename, content });
}

export function ansibleLaunch(inventoryPath: string, playbookPath: string): Promise<void> {
  return invoke('ansible_launch', { inventoryPath, playbookPath });
}

// ─────────────────────────── Notifications (SSE) ──────────────────

// Open the long-lived SSE notification stream (tunnelled through Rust because the
// WebView can't EventSource against the self-signed server). The Rust side emits
// a `notification` Tauri event whenever a new notification arrives.
export function startNotificationStream(serverUrl: string, token: string): Promise<void> {
  return invoke('start_notification_stream', { serverUrl, token });
}

export function stopNotificationStream(): Promise<void> {
  return invoke('stop_notification_stream');
}

export type { Connection, Settings, AuthSession, TunnelStatus, TunnelMapping };
