// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/** Normalize an unknown thrown value to a message string. */
export function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Sentinel the session layer throws when the JWT expired (surfaced by refresh);
 * callers suppress the error toast when errMsg(err) matches it. */
export const SESSION_EXPIRED = 'SESSION_EXPIRED';
