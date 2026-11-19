// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// PowerShell takes the typographic single quotes U+2018..U+201B as quote delimiters too
// (about_Quoting_Rules, "smart quotation marks"; the character set from the language
// specification, chapter 2, single-quote-character). Not run against a pwsh here.
const QUOTES = /['\u2018\u2019\u201a\u201b]/g;

/**
 * `value` as one verbatim PowerShell string. Inside single quotes PowerShell expands neither
 * `$` nor the backtick; the only escape is a doubled quote character, which also holds for the
 * typographic ones (about_Quoting_Rules). Always quoted: a bare word could start with `-`,
 * hold `,` (array) or `@` (splatting).
 */
export function psQuote(value: string): string {
  return `'${value.replace(QUOTES, (c) => c + c)}'`;
}
