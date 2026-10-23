// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// FOUC-free theme init: apply the persisted theme before the first paint, so a
// light-mode user never flashes dark on load. Default = dark (no attribute).
// A file, not an inline script in index.html: the server's CSP allows only
// script-src 'self', which blocks inline scripts. Vite copies public/ as is.
try {
  var stored = localStorage.getItem('ah-theme');
  if (stored === 'light' || stored === 'dark') {
    document.documentElement.dataset.theme = stored;
  }
} catch (e) {
  /* localStorage unavailable (private mode, blocked site data) — stay on the dark default */
}
