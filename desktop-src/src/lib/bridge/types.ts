// Rust-Backend-Spiegeltypen.
// Entsprechen 1:1 den Structs/Enums in desktop/src-tauri/src/models.rs
// und den Command-Signaturen in desktop/src-tauri/src/commands.rs.
//
// Diese Types sind BEWUSST getrennt von src/lib/api/types.ts (Web-API).
// Der Rust-Backend-Connection-Typ ist enger (nur ssh/rdp/web) als der
// Server-API-Typ (ssh/rdp/vnc/web/custom).
//
// Bei Aenderungen in models.rs diese Datei manuell nachziehen.

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
  visitorName: string;
  proxyName: string;
  localPort: number;
  remoteHost: string;
  remotePort: number;
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
