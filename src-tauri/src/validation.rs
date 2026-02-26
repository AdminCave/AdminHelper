use crate::error::AppError;
use crate::models::{Connection, ConnectionKind};
use url::Url;

pub fn validate_host(host: &str) -> Result<(), AppError> {
    let trimmed = host.trim();
    if trimmed.is_empty() {
        return Err(AppError::Validation("Host fehlt".to_string()));
    }
    if trimmed.starts_with('-') {
        return Err(AppError::Validation("Ungueltiger Hostname".to_string()));
    }
    if trimmed
        .contains(|c: char| c.is_control() || c.is_whitespace() || ";|&$`'\"\\{}()!#".contains(c))
    {
        return Err(AppError::Validation("Ungueltiger Hostname".to_string()));
    }
    Ok(())
}

pub fn validate_no_control_chars(value: &str, label: &str) -> Result<(), AppError> {
    if value.contains(|c: char| c.is_control()) {
        return Err(AppError::Validation(format!(
            "{label} enthaelt ungueltige Zeichen"
        )));
    }
    Ok(())
}

pub fn validate_web_url(raw: &str) -> Result<String, AppError> {
    let trimmed = raw.trim();
    let with_scheme = if !trimmed.contains("://") {
        format!("https://{trimmed}")
    } else {
        trimmed.to_string()
    };
    let parsed = Url::parse(&with_scheme)?;
    match parsed.scheme() {
        "https" | "http" => Ok(parsed.to_string()),
        other => Err(AppError::Validation(format!(
            "Unerlaubtes URL-Schema: {other}"
        ))),
    }
}

pub fn validate_connection_input(connection: &Connection) -> Result<(), AppError> {
    if let Some(ref host) = connection.host {
        let trimmed = host.trim();
        if !trimmed.is_empty() {
            validate_host(trimmed)?;
        }
    }
    if let Some(ref username) = connection.username {
        validate_no_control_chars(username, "Benutzer")?;
    }
    if let Some(ref domain) = connection.domain {
        validate_no_control_chars(domain, "Domaene")?;
    }
    if let Some(ref key_path) = connection.key_path {
        let trimmed = key_path.trim();
        if !trimmed.is_empty() && trimmed.contains("..") {
            return Err(AppError::Validation("Ungueltiger SSH Key Pfad".to_string()));
        }
    }
    if let Some(ref url) = connection.url {
        if connection.kind == ConnectionKind::Web && !url.trim().is_empty() {
            validate_web_url(url)?;
        }
    }
    Ok(())
}

pub fn sanitize_synced_connections(connections: Vec<Connection>) -> Vec<Connection> {
    connections
        .into_iter()
        .filter(|c| validate_connection_input(c).is_ok())
        .collect()
}
