// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { tNow } from '$lib/i18n';

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return tNow('timeAgo.never');
  const ms = Date.parse(dateStr);
  if (Number.isNaN(ms)) return tNow('timeAgo.never');
  const diff = Date.now() - ms;
  if (diff < 0) return tNow('timeAgo.never');
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return tNow('timeAgo.justNow');
  const mins = Math.floor(secs / 60);
  if (mins < 60) return tNow('timeAgo.minutes', { count: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return tNow('timeAgo.hours', { count: hours });
  const days = Math.floor(hours / 24);
  if (days === 1) return tNow('timeAgo.yesterday');
  if (days < 30) return tNow('timeAgo.days', { count: days });
  const months = Math.floor(days / 30);
  if (months >= 12) {
    const years = Math.floor(months / 12);
    return tNow(years === 1 ? 'timeAgo.year' : 'timeAgo.years', { count: years });
  }
  return tNow(months === 1 ? 'timeAgo.month' : 'timeAgo.months', { count: months });
}
