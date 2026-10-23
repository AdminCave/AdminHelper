// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Characters a POSIX shell takes literally in a word — the set Python's shlex.quote leaves bare,
// so the values the server issues (URL, token, UUID, fingerprint) read as they always did.
const SAFE = /^[A-Za-z0-9@%+=:,./_-]+$/;

/**
 * `value` as exactly one POSIX shell word with exactly that value. Inside single quotes every
 * character is literal and a single quote cannot occur (POSIX Shell Command Language 2.2.2), so
 * each `'` closes the quote, adds an escaped `\'` and reopens it.
 */
export function shellQuote(value: string): string {
  if (SAFE.test(value)) return value;
  return `'${value.replace(/'/g, "'\\''")}'`;
}
