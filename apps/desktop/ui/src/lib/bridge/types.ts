// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Rust backend mirror types.
// Correspond 1:1 to the structs/enums in apps/desktop/src-tauri/src/models.rs
// and to the command signatures in apps/desktop/src-tauri/src/commands.rs.
//
// These types are DELIBERATELY separate from src/lib/api/types.ts (web API):
// this file mirrors the Rust backend structs, api/types.ts mirrors the server
// HTTP API. Both use the same connection kinds (ssh/rdp/web).
//
// When models.rs changes, update this file manually.

export type ConnectionKind = 'ssh' | 'rdp' | 'web';
export type SyncMode = 'local' | 'sync' | 'server';
export type RdpScalingMode = 'auto' | 'normal' | 'hdpi';
export type RdpWindowMode = 'fit' | 'fullscreen' | 'multimon' | 'custom';
export type RdpPerformanceProfile = 'auto' | 'lan' | 'broadband' | 'low';

export interface Connection {
  id: string;
  name: string;
  kind: ConnectionKind;
  host?: string | null;
  port?: number | null;
  username?: string | null;
  domain?: string | null;
  keyPath?: string | null;
  url?: string | null;
  notes?: string | null;
  tags: string[];
  trustCert: boolean;
  lastUsed?: string | null;
  // Set for server-owned connections (server mode). The launcher does not edit
  // it but round-trips it so a server-mode edit keeps the server association.
  serverId?: string | null;
}

export interface Settings {
  mode: SyncMode;
  url?: string | null;
  intervalMinutes: number;
  language?: string | null;
  storePasswords: boolean;
  rdpScalingMode: RdpScalingMode;
  rdpWindowMode: RdpWindowMode;
  rdpCustomSize?: string | null;
  rdpPerformanceProfile: RdpPerformanceProfile;
  allowSelfSignedCerts: boolean;
  serverUrl?: string | null;
  // Last username used for a successful server login; pre-filled on the login
  // screen so only the password has to be entered on each start.
  lastUsername?: string | null;
  // Show native OS notifications for new bell-feed entries (opt-in).
  osNotifications: boolean;
}

// Who signed in where. The tokens stay in the Rust process (session.rs), never here.
export interface AuthSession {
  serverUrl: string;
  username: string;
  isAdmin: boolean;
}

export interface TunnelStatus {
  running: boolean;
  visitorName?: string | null;
  connectedSince?: string | null;
  /** Names of the visitors the running frpc applied. */
  visitors?: string[];
  /** Where each visitor of the running frpc listens. */
  bindings?: VisitorBinding[];
}

/** Where a visitor listens: the server's port and the local port on 127.0.0.1 it got instead. */
export interface VisitorBinding {
  name: string;
  serverPort: number;
  localPort: number;
}

/** What a tunnel reconciliation did with the visitor bundle; `stopped`: no tunnels. */
export type RefreshOutcome = 'started' | 'restarted' | 'reloaded' | 'unchanged' | 'stopped';

export interface TunnelRefresh {
  status: TunnelStatus;
  outcome: RefreshOutcome;
  /** The HTTP code with which the server refused the tunnels (403); frpc is stopped then. */
  refused: number | null;
}

export interface ClientInfo {
  screenWidth?: number | null;
  screenHeight?: number | null;
  scaleFactor?: number | null;
}

export interface PasswordState {
  stored: boolean;
  canStore: boolean;
}

// The enrolled device certificate (models.rs DeviceIdentity, R-0240): the leaf's CN and
// its expiry as RFC 3339 in UTC.
export interface DeviceIdentity {
  name: string;
  notAfter: string;
}

export interface TunnelMapping {
  id: string;
  serverId: string;
  tunnelType: string;
  protocol: string;
  localPort: number;
  visitorPort: number | null;
  customDomains: string | null;
  connectionId: string | null;
  enabled: boolean;
  name: string;
}

export interface ResolvedConnection {
  connection: Connection;
  viaTunnel: boolean;
  tunnelName?: string | null;
  tunnelType?: string | null;
}

export interface AnsibleTarget {
  hostname: string;
  groups: string[];
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

// How resetting the device identity went (enrollment.rs ResetOutcome, R-0224): revoked
// at the server, deleted only here because the server did not revoke it (not reachable,
// or it declined), or there was no identity at all.
export type ResetOutcome = 'revoked' | 'localOnly' | 'notEnrolled';

// ─────────────────────────── Workspaces (R-0431) ───────────────────────────

// A workspace as the picker lists it and as its window knows itself (models.rs WorkspaceInfo).
export interface WorkspaceInfo {
  id: string;
  name: string;
  /** One of the palette (workspace.rs PALETTE). */
  color: string;
  kind: SyncMode;
  /**
   * Its URL with user and password masked as one (`***@`), the query values and the fragment
   * masked (`?token=***`, `#***`), in the spelling of the Rust URL parser; a URL with nothing
   * to mask as kept (workspace.rs shown_url). Null without a URL or for one that does not
   * parse.
   */
  url?: string | null;
  /** The host of its URL; null without a URL. */
  host?: string | null;
  /** A process holds the workspace. */
  open: boolean;
}

// What the picker shows: `lastUsed` is selected first; `migratedNotice` comes true once, and
// so does `unreadableSettings`, the name (no path) the migration set an unreadable
// settings.json aside under in the app data dir.
export interface WorkspaceList {
  workspaces: WorkspaceInfo[];
  lastUsed?: string | null;
  migratedNotice: boolean;
  unreadableSettings?: string | null;
}

// Makes a workspace (no id) or edits the closed one `id` names. The kind of a workspace
// never changes. In an edit, the `url` of its WorkspaceInfo sent back as it came keeps the
// URL it has (user, query and fragment with it); another url replaces it, and a missing or
// blank url takes it away, unless the WorkspaceInfo had none.
export interface WorkspaceDraft {
  id?: string | null;
  kind: SyncMode;
  name: string;
  color: string;
  url?: string | null;
}

// Which process the webview talks to: the launcher, or the process of `workspace`.
export interface WorkspaceContext {
  launcher: boolean;
  workspace?: WorkspaceInfo | null;
}
