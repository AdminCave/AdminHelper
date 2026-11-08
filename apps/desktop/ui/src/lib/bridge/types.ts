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

/** The desktop an embedded session asks for (R-1100): pixels and the scale factor in percent. */
export interface RdpDisplay {
  width: number;
  height: number;
  scale: number;
}
export type RdpPerformanceProfile = 'auto' | 'lan' | 'broadband' | 'low';
export type SshConsole = 'embedded' | 'external';
export type RdpClient = 'embedded' | 'os';
export type TerminalTheme = 'cave' | 'contrast' | 'light';
export type TerminalCursor = 'block' | 'bar' | 'underline';

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
  options?: ConnectionOptions | null;
}

export type SshForwardKind = 'L' | 'R' | 'D';
export type SshAuthMethod = 'key' | 'agent' | 'password';

export interface SshForward {
  type: SshForwardKind;
  listen: string;
  target?: string | null;
}

export interface SshOptions {
  jumpHost?: string | null;
  forwards?: SshForward[];
  agentForwarding?: boolean | null;
  compression?: boolean | null;
  keepalive?: number | null;
  authMethod?: SshAuthMethod | null;
}

export type RdpAudio = 'local' | 'remote' | 'off';

export interface RdpConnectionOptions {
  scalingMode?: RdpScalingMode | null;
  windowMode?: RdpWindowMode | null;
  customSize?: string | null;
  performanceProfile?: RdpPerformanceProfile | null;
  drives?: boolean | null;
  audio?: RdpAudio | null;
  printers?: boolean | null;
  gateway?: string | null;
  nla?: boolean | null;
}

// Per-connection overrides (R-1066); a field left out means the global default.
export interface ConnectionOptions {
  ssh?: SshOptions | null;
  rdp?: RdpConnectionOptions | null;
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
  // Ids of the starred connections; kept in the workspace, not on a server.
  favoriteConnections?: string[];
  // Where an SSH connection opens: a tab of the app or the terminal of the OS.
  sshConsole: SshConsole;
  // Which client an RDP connection opens in; 'os' when absent.
  rdpClient?: RdpClient;
  terminal: TerminalPrefs;
  // Open the SSH tabs of the last run again after sign-in; off unless chosen.
  restoreSessions?: boolean;
  // Ids of the connections whose SSH tabs were open, in tab order; kept in the workspace.
  openSessions?: string[];
  // The snippets of the terminal, kept in the workspace; null: never changed, the panel shows
  // its default list. An empty list stays empty.
  snippets?: Snippet[] | null;
}

// A command of the snippet panel of the terminal.
export interface Snippet {
  name: string;
  command: string;
}

// Options of the embedded terminal, kept per device like the RDP options.
export interface TerminalPrefs {
  fontSize: number;
  theme: TerminalTheme;
  cursor: TerminalCursor;
  scrollback: number;
  copyOnSelect: boolean;
  rightClickPaste: boolean;
  confirmClose: boolean;
}

// One reachability probe: probe_targets answers with the connect time in ms or null per target.
export interface ProbeTarget {
  host: string;
  port: number;
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

/** One connect of a connection (R-1068), as the server lists it and as the local history keeps it. */
export interface ConnectionSession {
  id: string;
  device: string | null;
  startedAt: string;
  endedAt: string | null;
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

// ─────────────────────────── Embedded terminal (R-1069) ───────────────────

// The last message of a terminal session, after all of its output (models.rs TerminalExit):
// the program ended, with its exit code when waiting for it worked.
export interface TerminalExit {
  exitCode: number | null;
}

// ─────────────────────────── SFTP of a terminal session (R-1072) ───────────

// What a directory entry is (sftp.rs SftpKind); a symlink is not followed.
export type SftpKind = 'dir' | 'file' | 'link' | 'other';

export interface SftpEntry {
  name: string;
  kind: SftpKind;
  size: number;
}

// A directory: its resolved path and its entries, folders first, `..` on top below `/`.
export interface SftpListing {
  path: string;
  entries: SftpEntry[];
}

// Files dropped on the main window (event `sftp-drop`): their number for sftpUploadDropped and
// their names. An upload names no path, only the number: Rust uploads what it holds under it.
export interface SftpDrop {
  drop: number;
  names: string[];
}

// What an upload did: the files it wrote, and the names of those it left as they existed.
export interface SftpUploaded {
  drop: number;
  uploaded: number;
  existing: string[];
}

// A step of a transfer: bytes done of all bytes of the file `name`.
export interface SftpTransfer {
  name: string;
  done: number;
  total: number;
}

// ─────────────────────────── Embedded RDP ─────────────────────────
// The session types are pub(crate) in rdp_embedded/ and outside the parity scan; their fields
// stay snake_case on the wire, as Rust names them.

// Where the picture of a started session comes from: the session's local WebSocket and the
// token it wants as the first message. `drive_unavailable`: the options ask for a drive, the
// session shares none.
export interface RdpStarted {
  session_id: string;
  ws_port: number;
  token: string;
  notice?: 'drive_unavailable';
}

export type RdpPhase =
  'connecting' | 'connected' | 'reconnecting' | 'certificate' | 'disconnected' | 'failed';

// Why a session ended, with the `disconnected` and `failed` phases.
export type RdpEndCode =
  | 'tls'
  | 'auth'
  | 'logon'
  | 'watchdog'
  | 'redirect'
  | 'panic'
  | 'connect'
  | 'closed'
  | 'server'
  | 'network';

// The event `rdp-session`. `certificate` carries the pin identity, the server's fingerprint and
// whether no pin exists yet (`unknown`) or the pin differs (`changed`).
export interface RdpPhaseEvent {
  session_id: string;
  phase: RdpPhase;
  code?: RdpEndCode;
  identity?: string;
  fingerprint?: string;
  reason?: 'unknown' | 'changed';
}

// What a running session connected to: the stored `host:port`, the tunnel that carries it and
// how the certificate is checked.
export interface RdpSessionInfo {
  target: string;
  via_tunnel: boolean;
  tunnel?: string;
  credssp: boolean;
  certificate: 'pinned' | 'trust_all';
  fingerprint?: string;
}
