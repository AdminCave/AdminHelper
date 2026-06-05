// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  worstStatus,
  groupChecksByServer,
  filterChecks,
  statusClass,
  computeSummary,
  checkTypeUnit,
  isPercentCheck,
} from './monitoring';
import type { MonitorCheck, Server } from '$lib/api/types';

const chk = (
  id: string,
  serverId: string | null,
  type: MonitorCheck['checkType'],
  status?: MonitorCheck['state'],
): MonitorCheck => ({
  id,
  name: id,
  serverId,
  checkType: type,
  interval: '5m',
  severity: 'warning',
  enabled: true,
  state: status ?? null,
});

describe('worstStatus', () => {
  it('critical beats warning beats ok', () => {
    expect(
      worstStatus([
        { state: { status: 'ok' } },
        { state: { status: 'warning' } },
        { state: { status: 'critical' } },
      ]),
    ).toBe('critical');
    expect(worstStatus([{ state: { status: 'ok' } }, { state: { status: 'warning' } }])).toBe(
      'warning',
    );
  });
  it('all ok yields ok', () => {
    expect(worstStatus([{ state: { status: 'ok' } }])).toBe('ok');
  });
});

describe('groupChecksByServer', () => {
  it('groups by serverId and names from server list', () => {
    const servers: Server[] = [
      { id: 's1', name: 'Alpha', hostname: 'a' },
      { id: 's2', name: 'Bravo', hostname: 'b' },
    ];
    const checks = [chk('c1', 's1', 'ping'), chk('c2', 's2', 'ping'), chk('c3', 's1', 'tcp')];
    const groups = groupChecksByServer(checks, servers);
    expect(groups.map((g) => g.serverName)).toEqual(['Alpha', 'Bravo']);
    expect(groups[0].checks.map((c) => c.id).sort()).toEqual(['c1', 'c3']);
  });

  it('puts orphan checks into "Ohne Server"', () => {
    const groups = groupChecksByServer([chk('c1', null, 'ping')], []);
    expect(groups).toHaveLength(1);
    expect(groups[0].serverId).toBeNull();
  });
});

describe('filterChecks', () => {
  const data = [
    chk('c1', 's1', 'ping', { status: 'ok' }),
    chk('c2', 's1', 'tcp', { status: 'warning' }),
    chk('c3', 's2', 'ping', { status: 'critical' }),
  ];
  it('filters by server', () => {
    const out = filterChecks(data, { server: 's1', type: '', status: '', search: '' });
    expect(out.map((c) => c.id)).toEqual(['c1', 'c2']);
  });
  it('filters by type', () => {
    const out = filterChecks(data, { server: '', type: 'ping', status: '', search: '' });
    expect(out.map((c) => c.id)).toEqual(['c1', 'c3']);
  });
  it('filters by status', () => {
    const out = filterChecks(data, { server: '', type: '', status: 'critical', search: '' });
    expect(out.map((c) => c.id)).toEqual(['c3']);
  });
  it('free-text search is case insensitive and matches name', () => {
    const out = filterChecks(data, { server: '', type: '', status: '', search: 'C2' });
    expect(out.map((c) => c.id)).toEqual(['c2']);
  });
});

describe('statusClass + units', () => {
  it('maps status to css class', () => {
    expect(statusClass('ok')).toBe('mon-ok');
    expect(statusClass(undefined)).toBe('mon-pending');
  });
  it('checkTypeUnit for common types', () => {
    expect(checkTypeUnit('ping')).toBe('ms');
    expect(checkTypeUnit('agent_resources')).toBe('%');
    expect(checkTypeUnit('docker_health')).toBe('');
  });
  it('isPercentCheck only for resource-type checks', () => {
    expect(isPercentCheck('agent_resources')).toBe(true);
    expect(isPercentCheck('zfs_health')).toBe(true);
    expect(isPercentCheck('ping')).toBe(false);
  });
});

describe('computeSummary', () => {
  it('counts by status', () => {
    const s = computeSummary([
      chk('1', null, 'ping', { status: 'ok' }),
      chk('2', null, 'ping', { status: 'warning' }),
      chk('3', null, 'ping', { status: 'critical' }),
      chk('4', null, 'ping'),
    ]);
    expect(s.total).toBe(4);
    expect(s.ok).toBe(1);
    expect(s.warning).toBe(1);
    expect(s.critical).toBe(1);
    expect(s.pending).toBe(1);
  });
});
