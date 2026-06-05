// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::error::AppError;
use crate::models::Connection;
use crate::validation::validate_web_url;

pub fn open_web(connection: &Connection) -> Result<(), AppError> {
    let raw = connection
        .url
        .as_ref()
        .ok_or_else(|| AppError::Validation("URL fehlt".to_string()))?;
    let url = validate_web_url(raw)?;
    open::that(&url)?;
    Ok(())
}
