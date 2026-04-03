use url::Url;

use crate::error::AppError;
use crate::models::Connection;
use crate::storage::write_connections;
use crate::validation::sanitize_synced_connections;

fn validate_https_url(raw: &str) -> Result<(), AppError> {
    let url = Url::parse(raw)?;
    if url.scheme() != "https" {
        return Err(AppError::Validation(
            "Nur https:// URLs sind erlaubt".to_string(),
        ));
    }
    Ok(())
}

pub async fn sync_connections(
    app: tauri::AppHandle,
    url: String,
    allow_self_signed: bool,
) -> Result<Vec<Connection>, AppError> {
    validate_https_url(&url)?;
    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(allow_self_signed)
        .build()?;
    let response = client.get(&url).send().await?.error_for_status()?;
    let connections: Vec<Connection> = response.json().await?;
    let connections = sanitize_synced_connections(connections);
    write_connections(&app, &connections)?;
    Ok(connections)
}
