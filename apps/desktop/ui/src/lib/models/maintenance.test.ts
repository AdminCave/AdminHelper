// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T27: client-side mirror of is_in_maintenance for the badge — one-off UTC
// windows, weekly windows DST-correct via Intl in the window's zone, midnight
// overflow, global-vs-server scope resolution.

import { describe, it, expect } from 'vitest';
import type { MaintenanceWindow } from '$lib/api/types';
import { activeMaintenance, isWindowActive, serverInMaintenance } from './maintenance';

function once(startsAt: string, endsAt: string, over: Partial<MaintenanceWindow> = {}) {
  return {
    id: 'w1',
    kind: 'once',
    startsAt,
    endsAt,
    timezone: 'UTC',
    enabled: true,
    ...over,
  } as MaintenanceWindow;
}

function weekly(
  weekdays: number[],
  startTime: string,
  durationMinutes: number,
  timezone: string,
  over: Partial<MaintenanceWindow> = {},
) {
  return {
    id: 'w1',
    kind: 'weekly',
    weekdays,
    startTime,
    durationMinutes,
    timezone,
    enabled: true,
    ...over,
  } as MaintenanceWindow;
}

describe('isWindowActive (T27)', () => {
  it('one-off windows compare UTC instants (backend sends naive ISO)', () => {
    const w = once('2026-07-19T12:00:00', '2026-07-19T14:00:00');
    expect(isWindowActive(w, new Date('2026-07-19T13:00:00Z'))).toBe(true);
    expect(isWindowActive(w, new Date('2026-07-19T14:00:00Z'))).toBe(false); // end exclusive
    expect(isWindowActive({ ...w, enabled: false }, new Date('2026-07-19T13:00:00Z'))).toBe(false);
  });

  it('weekly windows stay wall-clock correct across DST (Europe/Berlin)', () => {
    const w = weekly([6], '02:00', 120, 'Europe/Berlin'); // Sunday 02:00-04:00
    expect(isWindowActive(w, new Date('2026-07-19T00:30:00Z'))).toBe(true); // 02:30 CEST
    expect(isWindowActive(w, new Date('2026-11-01T01:30:00Z'))).toBe(true); // 02:30 CET
    expect(isWindowActive(w, new Date('2026-07-19T03:00:00Z'))).toBe(false); // 05:00 CEST
    expect(isWindowActive(w, new Date('2026-11-01T04:00:00Z'))).toBe(false); // 05:00 CET
  });

  it('unknown timezone renders quietly inactive (badge-only divergence)', () => {
    const w = weekly([6], '02:00', 120, 'Not/AZone');
    expect(isWindowActive(w, new Date('2026-07-19T02:30:00Z'))).toBe(false);
  });

  it('midnight overflow keeps yesterday-started windows active', () => {
    const w = weekly([5], '23:00', 180, 'Europe/Berlin'); // Sat 23:00 + 3h
    expect(isWindowActive(w, new Date('2026-07-18T23:30:00Z'))).toBe(true); // Sun 01:30 CEST
    expect(isWindowActive(w, new Date('2026-07-19T01:00:00Z'))).toBe(false); // Sun 03:00 CEST
  });
});

describe('activeMaintenance scope', () => {
  it('resolves global vs server windows', () => {
    const now = new Date('2026-07-19T13:00:00Z');
    const windows = [
      once('2026-07-19T12:00:00', '2026-07-19T14:00:00', { id: 'g', serverId: null }),
      once('2026-07-19T12:00:00', '2026-07-19T14:00:00', { id: 's', serverId: 'srv-1' }),
    ];
    const active = activeMaintenance(windows, now);
    expect(active.global).toBe(true);
    expect(serverInMaintenance(active, 'srv-9')).toBe(true); // global covers all

    const onlyServer = activeMaintenance([windows[1]], now);
    expect(serverInMaintenance(onlyServer, 'srv-1')).toBe(true);
    expect(serverInMaintenance(onlyServer, 'srv-9')).toBe(false);
  });
});
