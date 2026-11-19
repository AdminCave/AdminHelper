// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Links from the desktop into the AdminHelper documentation (R-1596).
//!
//! The window names only a page below `docs/`; the base is fixed here, so the
//! command cannot be turned into an opener for arbitrary URLs.

use crate::error::AppError;

/// The docs live as HTML in the public repository; there is no hosted copy yet.
const DOCS_BASE: &str = "https://github.com/AdminCave/AdminHelper/blob/main/docs/";

fn page_char(c: char) -> bool {
    c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_'
}

/// The full URL of a docs page such as `en/admin/agent-deployment.html#windows`.
/// Each path segment and the anchor take only lower-case ASCII letters, digits,
/// `-` and `_`; the page ends in `.html`.
pub fn doc_url(path: &str) -> Result<String, AppError> {
    let refused = || AppError::Validation(format!("not a docs page: {path}"));
    let (page, anchor) = match path.split_once('#') {
        Some((page, anchor)) => (page, Some(anchor)),
        None => (path, None),
    };
    if let Some(anchor) = anchor {
        if anchor.is_empty() || !anchor.chars().all(page_char) {
            return Err(refused());
        }
    }
    let stem = page.strip_suffix(".html").ok_or_else(refused)?;
    if stem
        .split('/')
        .any(|segment| segment.is_empty() || !segment.chars().all(page_char))
    {
        return Err(refused());
    }
    Ok(format!("{DOCS_BASE}{path}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_the_url_of_a_docs_page() {
        assert_eq!(
            doc_url("en/admin/agent-deployment.html#windows").unwrap(),
            "https://github.com/AdminCave/AdminHelper/blob/main/docs/en/admin/agent-deployment.html#windows"
        );
        assert_eq!(
            doc_url("admin/agent-deployment.html").unwrap(),
            "https://github.com/AdminCave/AdminHelper/blob/main/docs/admin/agent-deployment.html"
        );
    }

    #[test]
    fn refuses_anything_but_a_page_below_docs() {
        for path in [
            "",
            "https://example.org/x.html",
            "//example.org/x.html",
            "../README.md",
            "admin/../../x.html",
            "admin//x.html",
            "/admin/x.html",
            "admin/x.md",
            "admin/x.html#",
            "admin/x.html#a#b",
            "admin/x.html?q=1",
            "Admin/X.html",
            "admin/x y.html",
            "admin/x.html#a b",
        ] {
            assert!(
                matches!(doc_url(path), Err(AppError::Validation(_))),
                "accepted {path:?}"
            );
        }
    }
}
