// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use serde::{Deserialize, Serialize};

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
    pub url: Option<String>,
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
            url: None,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthSession {
    pub server_url: String,
    pub token: String,
    pub refresh_token: String,
    pub username: String,
    pub is_admin: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TunnelStatus {
    pub running: bool,
    pub visitor_name: Option<String>,
    pub connected_since: Option<String>,
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

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RdpErrorPayload {
    pub correlation_id: String,
    pub message: String,
}
