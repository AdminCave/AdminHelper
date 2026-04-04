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
    pub allow_self_signed_certs: bool,
    #[serde(default)]
    pub server_url: Option<String>,
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
            allow_self_signed_certs: false,
            server_url: None,
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
