// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A fixed "now" keeps the mockup and its screenshots reproducible.
export const NOW = new Date('2026-11-18T09:00:00Z');

const MINUTE = 60_000;

/** ISO time `minutes` before NOW. */
export function ago(minutes: number): string {
  return new Date(NOW.getTime() - minutes * MINUTE).toISOString();
}

export const HOUR = 60;
export const DAY = 24 * HOUR;
