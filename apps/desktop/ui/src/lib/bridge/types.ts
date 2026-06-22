// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Rust backend mirror types.
// Correspond 1:1 to the structs/enums in apps/desktop/src-tauri/src/models.rs
// and to the command signatures in apps/desktop/src-tauri/src/commands.rs.
//
// These types are DELIBERATELY separate from src/lib/api/types.ts (web API).
// The Rust backend connection type is narrower (only ssh/rdp/web) than the
// server API type (ssh/rdp/vnc/web/custom).
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

export interface AuthSession {
  serverUrl: string;
  token: string;
  refreshToken: string;
  username: string;
  isAdmin: boolean;
}

export interface TunnelStatus {
  running: boolean;
  visitorName?: string | null;
  connectedSince?: string | null;
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
}

export interface AnsibleTarget {
  hostname: string;
  groups: string[];
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';
