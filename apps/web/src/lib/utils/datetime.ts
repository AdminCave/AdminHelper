// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { get } from 'svelte/store';

import { language } from '$lib/i18n';

// BCP-47 locale for date formatting, derived from the UI language. English is
// en-US everywhere (2.54 — Hooks.svelte had drifted to en-GB).
function locale(): string {
  return get(language) === 'de' ? 'de-DE' : 'en-US';
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  // new Date('bad').toLocaleString() returns the string 'Invalid Date' — it does
  // NOT throw — so the copies' try/catch was dead code; guard on NaN so a bad
  // value renders '–' as intended, not 'Invalid Date' (2.54).
  return Number.isNaN(d.getTime()) ? '–' : d.toLocaleString(locale());
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '–' : d.toLocaleDateString(locale());
}
