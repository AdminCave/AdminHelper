// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/** Result of a form/model validation: ok, plus an optional message when not ok. */
export interface ValidationResult {
  ok: boolean;
  message?: string;
}

/** Parse a comma-separated tag string into trimmed, de-duplicated, non-empty tags.
 * The single source (audit 2.22): connection.ts's copy skipped the Set dedup, so the
 * launcher editor let you add duplicate tags while the infra hub didn't. */
export function parseTags(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(',')
        .map((tag) => tag.trim())
        .filter((tag) => tag.length > 0),
    ),
  ];
}
