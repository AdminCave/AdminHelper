// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { TranslateFn } from '$lib/i18n';

// Takes the (reactive) translator from the caller instead of the tNow snapshot:
// reading `$t` in the template subscribes it to the language store, so the
// rendered "x min ago" re-computes on a language switch.
export function timeAgo(dateStr: string | null | undefined, t: TranslateFn): string {
  if (!dateStr) return t('timeAgo.never');
  const ms = Date.parse(dateStr);
  if (Number.isNaN(ms)) return t('timeAgo.never');
  const diff = Date.now() - ms;
  if (diff < 0) return t('timeAgo.never');
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return t('timeAgo.justNow');
  const mins = Math.floor(secs / 60);
  if (mins < 60) return t('timeAgo.minutes', { count: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t('timeAgo.hours', { count: hours });
  const days = Math.floor(hours / 24);
  if (days === 1) return t('timeAgo.yesterday');
  if (days < 30) return t('timeAgo.days', { count: days });
  const months = Math.floor(days / 30);
  if (months >= 12) {
    const years = Math.floor(months / 12);
    return t(years === 1 ? 'timeAgo.year' : 'timeAgo.years', { count: years });
  }
  return t(months === 1 ? 'timeAgo.month' : 'timeAgo.months', { count: months });
}
