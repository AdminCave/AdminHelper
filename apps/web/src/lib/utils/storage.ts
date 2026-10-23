// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Every localStorage access goes through these helpers, and they never throw. When the
// browser blocks site data, the getter `window.localStorage` itself throws a SecurityError,
// even under `typeof`; client.ts and i18n touch storage at import time, so one bare access
// blanked the app before the login form rendered (R-0654). Persistence is a convenience,
// not a start condition. try/catch also covers a full storage and a missing localStorage.

export function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — persistence best-effort */
  }
}

export function storageRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* storage unavailable — nothing to remove */
  }
}
