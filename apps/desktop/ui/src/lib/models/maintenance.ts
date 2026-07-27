// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Client-side mirror of the monitoring service's is_in_maintenance (pure
// logic, drives the "maintenance" badge): one-off windows compare UTC
// instants, weekly windows evaluate wall clock in the window's IANA timezone
// via Intl (DST-correct, midnight overflow honored). Divergence here only
// mis-renders a badge — the authoritative mute lives server-side.

import type { MaintenanceWindow } from '$lib/api/types';

const WEEKDAY_INDEX: Record<string, number> = {
  Mon: 0,
  Tue: 1,
  Wed: 2,
  Thu: 3,
  Fri: 4,
  Sat: 5,
  Sun: 6,
};

function zonedParts(now: Date, timeZone: string): { weekday: number; minutes: number } | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    const weekday = WEEKDAY_INDEX[get('weekday')];
    const minutes = Number(get('hour')) * 60 + Number(get('minute'));
    if (weekday === undefined || Number.isNaN(minutes)) return null;
    return { weekday, minutes };
  } catch {
    // Unknown zone: badge-only feature, quietly inactive (the backend
    // validates zones at the boundary, so this is tzdata drift at worst).
    return null;
  }
}

function onceActive(w: MaintenanceWindow, now: Date): boolean {
  if (!w.startsAt || !w.endsAt) return false;
  const starts = new Date(w.startsAt.endsWith('Z') ? w.startsAt : `${w.startsAt}Z`).getTime();
  const ends = new Date(w.endsAt.endsWith('Z') ? w.endsAt : `${w.endsAt}Z`).getTime();
  if (Number.isNaN(starts) || Number.isNaN(ends)) return false;
  return starts <= now.getTime() && now.getTime() < ends;
}

function weeklyActive(w: MaintenanceWindow, now: Date): boolean {
  const weekdays = w.weekdays ?? [];
  if (weekdays.length === 0 || !w.startTime || !w.durationMinutes) return false;
  const [hh, mm] = w.startTime.split(':').map(Number);
  if (Number.isNaN(hh) || Number.isNaN(mm)) return false;
  const zoned = zonedParts(now, w.timezone || 'UTC');
  if (!zoned) return false;
  const startMin = hh * 60 + mm;
  const dur = w.durationMinutes;
  // Same-day portion of the window.
  if (
    weekdays.includes(zoned.weekday) &&
    startMin <= zoned.minutes &&
    zoned.minutes < startMin + dur
  ) {
    return true;
  }
  // Midnight overflow: yesterday's window still running past 00:00.
  const yesterday = (zoned.weekday + 6) % 7;
  return weekdays.includes(yesterday) && zoned.minutes < startMin + dur - 1440;
}

export function isWindowActive(w: MaintenanceWindow, now: Date): boolean {
  if (!w.enabled) return false;
  return w.kind === 'once' ? onceActive(w, now) : weeklyActive(w, now);
}

export interface ActiveMaintenance {
  global: boolean;
  servers: Set<string>;
}

/** Which servers currently sit in an active window (global = every server). */
export function activeMaintenance(windows: MaintenanceWindow[], now: Date): ActiveMaintenance {
  const result: ActiveMaintenance = { global: false, servers: new Set() };
  for (const w of windows) {
    if (!isWindowActive(w, now)) continue;
    if (w.serverId == null) result.global = true;
    else result.servers.add(w.serverId);
  }
  return result;
}

export function serverInMaintenance(active: ActiveMaintenance, serverId: string | null): boolean {
  return active.global || (serverId != null && active.servers.has(serverId));
}
