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
) -> Result<Vec<Connection>, AppError> {
    validate_https_url(&url)?;
    let response = reqwest::get(&url).await?;
    if !response.status().is_success() {
        return Err(AppError::Network(response.error_for_status().unwrap_err()));
    }
    let connections: Vec<Connection> = response.json().await?;
    let connections = sanitize_synced_connections(connections);
    write_connections(&app, &connections)?;
    Ok(connections)
}
