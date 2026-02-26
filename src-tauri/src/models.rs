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
        }
    }
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
