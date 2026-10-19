// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The line the login screen shows after a reload that ended the session (R-0430). The
// reload empties every store, so the line waits in sessionStorage, which a reload of the
// window keeps and closing it drops.

const KEY = 'ah-login-notice';

/** Leaves `text` for the login screen the coming reload brings up. */
export function leaveLoginNotice(text: string): void {
  try {
    sessionStorage.setItem(KEY, text);
  } catch {
    /* without storage the login screen comes up without the line */
  }
}

/** The line left for the login screen, once; empty if there is none. */
export function takeLoginNotice(): string {
  try {
    const text = sessionStorage.getItem(KEY) ?? '';
    sessionStorage.removeItem(KEY);
    return text;
  } catch {
    return '';
  }
}
