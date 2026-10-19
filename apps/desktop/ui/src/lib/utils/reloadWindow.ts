// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/** Reloads the app window, so every store starts empty. A module of its own so tests can mock it. */
export function reloadWindow(): void {
  window.location.reload();
}
