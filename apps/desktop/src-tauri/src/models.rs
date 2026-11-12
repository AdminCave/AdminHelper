// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::{Deserialize, Serialize};

use crate::workspace::WorkspaceId;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ConnectionKind {
    Ssh,
    Rdp,
    Web,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum SyncMode {
    Local,
    Sync,
    Server,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum RdpScalingMode {
    #[default]
    Auto,
    Normal,
    Hdpi,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum RdpWindowMode {
    #[default]
    Fit,
    Fullscreen,
    Multimon,
    Custom,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum RdpPerformanceProfile {
    #[default]
    Auto,
    Lan,
    Broadband,
    Low,
}

/// Which client an RDP connection opens in: a tab of the app or the RDP client of the OS.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum RdpClient {
    Embedded,
    // The OS client stays the default until the embedded one has passed its Windows checks
    // (docs/features/kern-rdp-1.md, R-1090).
    #[default]
    Os,
}

/// Where an SSH connection opens: in a tab of the app or in the terminal of the OS.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum SshConsole {
    #[default]
    Embedded,
    External,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum TerminalTheme {
    #[default]
    Cave,
    Contrast,
    Light,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum TerminalCursor {
    #[default]
    Block,
    Bar,
    Underline,
}

/// The options of the embedded terminal. A field missing in `prefs.json` takes its default, so
/// a file of an older version, or one edited by hand, still loads.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", default)]
pub struct TerminalPrefs {
    pub font_size: u8,
    pub theme: TerminalTheme,
    pub cursor: TerminalCursor,
    pub scrollback: u32,
    pub copy_on_select: bool,
    pub right_click_paste: bool,
    pub confirm_close: bool,
    pub confirm_multiline_paste: bool,
}

impl Default for TerminalPrefs {
    fn default() -> Self {
        Self {
            font_size: 13,
            theme: TerminalTheme::default(),
            cursor: TerminalCursor::default(),
            scrollback: 10_000,
            copy_on_select: true,
            right_click_paste: true,
            confirm_close: true,
            confirm_multiline_paste: false,
        }
    }
}

/// Bundled RDP display options that are passed through the connection call
/// chain. Avoids wide signatures (clippy::too_many_arguments).
#[derive(Debug, Clone, Copy)]
pub struct RdpOptions<'a> {
    pub scaling_mode: RdpScalingMode,
    pub window_mode: RdpWindowMode,
    pub custom_size: Option<&'a str>,
    pub performance_profile: RdpPerformanceProfile,
}

impl<'a> RdpOptions<'a> {
    /// The connection's own values win field by field; a field it leaves out keeps the global one.
    pub fn with_overrides(self, own: Option<&'a RdpConnectionOptions>) -> Self {
        let Some(own) = own else {
            return self;
        };
        RdpOptions {
            scaling_mode: own.scaling_mode.unwrap_or(self.scaling_mode),
            window_mode: own.window_mode.unwrap_or(self.window_mode),
            custom_size: own.custom_size.as_deref().or(self.custom_size),
            performance_profile: own.performance_profile.unwrap_or(self.performance_profile),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Connection {
    pub id: String,
    pub name: String,
    pub kind: ConnectionKind,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub username: Option<String>,
    pub domain: Option<String>,
    pub key_path: Option<String>,
    pub url: Option<String>,
    pub notes: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub trust_cert: bool,
    pub last_used: Option<String>,
    // Server-owned connections carry the id of their server. The launcher does
    // not edit it, but must round-trip it so a server-mode edit doesn't drop the
    // association. Absent for local/sync connections.
    #[serde(default)]
    pub server_id: Option<String>,
    // Per-connection overrides (R-1066); a field left out means the global default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub options: Option<ConnectionOptions>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionOptions {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ssh: Option<SshOptions>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rdp: Option<RdpConnectionOptions>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RdpConnectionOptions {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scaling_mode: Option<RdpScalingMode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub window_mode: Option<RdpWindowMode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub custom_size: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub performance_profile: Option<RdpPerformanceProfile>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub drives: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub audio: Option<RdpAudio>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub printers: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gateway: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub nla: Option<bool>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum RdpAudio {
    Local,
    Remote,
    Off,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SshOptions {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub jump_host: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub forwards: Vec<SshForward>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub agent_forwarding: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub compression: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub keepalive: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auth_method: Option<SshAuthMethod>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SshForward {
    #[serde(rename = "type")]
    pub kind: SshForwardKind,
    pub listen: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum SshForwardKind {
    L,
    R,
    D,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum SshAuthMethod {
    Key,
    Agent,
    Password,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    pub mode: SyncMode,
    // The read-only sync source (unauthenticated GET, strict https) — distinct from
    // server_url, the JWT login target. Wire name pinned to "url" for compat (2.86).
    #[serde(rename = "url")]
    pub sync_url: Option<String>,
    #[serde(default = "default_sync_interval_minutes")]
    pub interval_minutes: u32,
    #[serde(default)]
    pub language: Option<String>,
    #[serde(default)]
    pub store_passwords: bool,
    #[serde(default)]
    pub rdp_scaling_mode: RdpScalingMode,
    #[serde(default)]
    pub rdp_window_mode: RdpWindowMode,
    #[serde(default)]
    pub rdp_custom_size: Option<String>,
    #[serde(default)]
    pub rdp_performance_profile: RdpPerformanceProfile,
    #[serde(default)]
    pub allow_self_signed_certs: bool,
    #[serde(default)]
    pub server_url: Option<String>,
    // Last username used for a successful server login. Pre-filled on the login
    // screen so only the password has to be entered on each start. Not a secret.
    #[serde(default)]
    pub last_username: Option<String>,
    // Show native OS notifications for new bell-feed entries (opt-in; needs the
    // OS notification permission, requested when the user enables it).
    #[serde(default)]
    pub os_notifications: bool,
    /// Ids of the starred connections, kept in the workspace (`workspace.json`), not on a server.
    #[serde(default)]
    pub favorite_connections: Vec<String>,
    #[serde(default)]
    pub ssh_console: SshConsole,
    #[serde(default)]
    pub rdp_client: RdpClient,
    /// H.264 of the embedded RDP client on Linux through Cisco's OpenH264 (R-1102): on unless
    /// turned off, which deletes the library.
    #[serde(default = "default_true")]
    pub rdp_h264: bool,
    #[serde(default)]
    pub terminal: TerminalPrefs,
    /// Opens the SSH tabs of the last run again after sign-in (R-1070); off unless chosen.
    #[serde(default)]
    pub restore_sessions: bool,
    /// Ids of the connections whose SSH tabs were open, in tab order; kept in the workspace
    /// (`workspace.json`), as its connections are.
    #[serde(default)]
    pub open_sessions: Vec<String>,
    /// The snippets of the terminal (R-1071), kept in the workspace (`workspace.json`). `None`:
    /// the workspace never changed them and the panel shows its default list; an empty list stays
    /// empty.
    #[serde(default)]
    pub snippets: Option<Vec<Snippet>>,
}

/// A command of the snippet panel of the terminal (R-1071).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Snippet {
    pub name: String,
    pub command: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            mode: SyncMode::Local,
            sync_url: None,
            interval_minutes: default_sync_interval_minutes(),
            language: None,
            store_passwords: false,
            rdp_scaling_mode: RdpScalingMode::Auto,
            rdp_window_mode: RdpWindowMode::Fit,
            rdp_custom_size: None,
            rdp_performance_profile: RdpPerformanceProfile::Auto,
            allow_self_signed_certs: false,
            server_url: None,
            last_username: None,
            os_notifications: false,
            favorite_connections: Vec::new(),
            ssh_console: SshConsole::Embedded,
            rdp_client: RdpClient::Os,
            rdp_h264: true,
            terminal: TerminalPrefs::default(),
            restore_sessions: false,
            open_sessions: Vec::new(),
            snippets: None,
        }
    }
}

/// What the webview learns of a sign-in. No token: the session stays in the process
/// (`session.rs`).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthSession {
    pub server_url: String,
    pub username: String,
    pub is_admin: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TunnelStatus {
    pub running: bool,
    pub visitor_name: Option<String>,
    pub connected_since: Option<String>,
    /// Names of the visitors the running frpc applied; empty while none runs.
    pub visitors: Vec<String>,
    /// Where each visitor of the running frpc listens; empty while none runs.
    pub bindings: Vec<VisitorBinding>,
}

/// Where a visitor listens: the port the server's visitor TOML asked for and the local port on
/// `127.0.0.1` it got instead from the port map (`port_registry.rs`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VisitorBinding {
    pub name: String,
    pub server_port: u16,
    pub local_port: u16,
}

/// What a tunnel reconciliation did with the visitor bundle it fetched.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum RefreshOutcome {
    Started,
    Restarted,
    Reloaded,
    Unchanged,
    /// No tunnels, or a stop came in meanwhile: no frpc runs.
    Stopped,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TunnelRefresh {
    pub status: TunnelStatus,
    pub outcome: RefreshOutcome,
    /// The HTTP code with which the server refused the device or the user the tunnels (403);
    /// the refresh stopped frpc then. `None` for every other end, no tunnels (404) included.
    pub refused: Option<u16>,
}

fn default_sync_interval_minutes() -> u32 {
    1
}

pub(crate) fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ClientInfo {
    pub screen_width: Option<u32>,
    pub screen_height: Option<u32>,
    pub scale_factor: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PasswordState {
    pub stored: bool,
    pub can_store: bool,
}

/// The enrolled device certificate as the settings show it: the leaf's CN and
/// its expiry as RFC 3339 in UTC.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeviceIdentity {
    pub name: String,
    pub not_after: String,
}

/// The last message of an embedded terminal session (R-1069), after all of its output: the
/// program ended, with its exit code when waiting for it worked.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TerminalExit {
    pub exit_code: Option<u32>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RdpErrorPayload {
    pub correlation_id: String,
    pub message: String,
}

/// A workspace as the picker lists it and as its window knows itself (R-0431).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceInfo {
    pub id: WorkspaceId,
    pub name: String,
    /// One of the palette (`workspace::PALETTE`).
    pub color: String,
    pub kind: SyncMode,
    /// Its URL as `workspace::shown_url` gives it: a user and a password masked as one (`***@`),
    /// the values of its query and its fragment masked (`?token=***`, `#***`), in the parser's
    /// spelling; a URL with nothing to mask as it keeps it. None without a URL or for one that
    /// does not parse.
    pub url: Option<String>,
    /// The host of its URL; none without a URL.
    pub host: Option<String>,
    /// A process holds its lock.
    pub open: bool,
}

/// What the picker shows.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceList {
    pub workspaces: Vec<WorkspaceInfo>,
    /// The workspace the picker selects first, if it is listed.
    pub last_used: Option<WorkspaceId>,
    /// The note on the migration is due: `launcher::list` says so once.
    pub migrated_notice: bool,
    /// The name (no path) in the app data dir the migration set an unreadable `settings.json`
    /// aside under, "Standard" being built from the defaults instead; `launcher::list` gives it
    /// once.
    pub unreadable_settings: Option<String>,
}

/// What the picker sends to make a workspace (`id` none) or to edit the one `id` names.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceDraft {
    pub id: Option<WorkspaceId>,
    pub kind: SyncMode,
    pub name: String,
    pub color: String,
    /// The URL the workspace keeps. In an edit, the `url` of its [`WorkspaceInfo`] sent back as
    /// it came keeps the URL it has, user, query and fragment with it; another URL replaces it,
    /// and none (or a blank one) takes it away, unless the info had none.
    pub url: Option<String>,
}

/// Which process the webview talks to: the launcher, or the process of `workspace`.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceContext {
    pub launcher: bool,
    /// The workspace of this process, open as this process holds it; none in the launcher.
    pub workspace: Option<WorkspaceInfo>,
}
