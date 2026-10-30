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

/// Bundled RDP display options that are passed through the connection call
/// chain. Avoids wide signatures (clippy::too_many_arguments).
#[derive(Debug, Clone, Copy)]
pub struct RdpOptions<'a> {
    pub scaling_mode: RdpScalingMode,
    pub window_mode: RdpWindowMode,
    pub custom_size: Option<&'a str>,
    pub performance_profile: RdpPerformanceProfile,
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
