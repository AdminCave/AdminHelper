use serde::Serialize;

#[derive(Debug)]
pub enum AppError {
    Validation(String),
    Io(std::io::Error),
    Network(reqwest::Error),
    Connection(String),
    Keyring(String),
    Json(serde_json::Error),
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AppError::Validation(msg) => write!(f, "{msg}"),
            AppError::Io(err) => write!(f, "{err}"),
            AppError::Network(err) => write!(f, "{err}"),
            AppError::Connection(msg) => write!(f, "{msg}"),
            AppError::Keyring(msg) => write!(f, "{msg}"),
            AppError::Json(err) => write!(f, "{err}"),
        }
    }
}

impl Serialize for AppError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_string())
    }
}

impl From<std::io::Error> for AppError {
    fn from(err: std::io::Error) -> Self {
        AppError::Io(err)
    }
}

impl From<reqwest::Error> for AppError {
    fn from(err: reqwest::Error) -> Self {
        AppError::Network(err)
    }
}

impl From<serde_json::Error> for AppError {
    fn from(err: serde_json::Error) -> Self {
        AppError::Json(err)
    }
}

impl From<url::ParseError> for AppError {
    fn from(err: url::ParseError) -> Self {
        AppError::Validation(err.to_string())
    }
}
