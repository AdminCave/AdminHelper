// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Characters a POSIX shell takes literally in a word — the set Python's shlex.quote leaves bare,
// so the values the server issues (URL, token, UUID, fingerprint) read as they always did.
// `%` stays bare: fish still expands a word that is exactly `%self` to its PID (feature flag
// `remove-percent-self`, off by default, https://fishshell.com/docs/current/language.html#featureflags;
// not run against a fish here). No value the server issues has that shape.
const SAFE = /^[A-Za-z0-9@%+=:,./_-]+$/;

/**
 * `value` as exactly one shell word that POSIX shells and fish both read as exactly that value,
 * except a bare `%self` for fish (see `SAFE`).
 * Inside single quotes POSIX takes every character literally and a single quote cannot occur
 * (POSIX Shell Command Language 2.2.2), while fish reads `\\` and `\'` there as escapes
 * (https://fishshell.com/docs/current/language.html#quotes). So no `'` and no `\` stays inside
 * the quotes: each closes the quote, follows as `\'` or `\\` (both shells read that as the
 * character itself outside quotes, POSIX 2.2.1) and reopens it.
 */
export function shellQuote(value: string): string {
  if (SAFE.test(value)) return value;
  return `'${value.replace(/['\\]/g, (c) => `'\\${c}'`)}'`;
}
