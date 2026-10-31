// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  containerDetails,
  forecastDetails,
  resourceDetails,
  serviceDetails,
  smartDetails,
  zfsDetails,
} from './checkDetails';

const ALL = {
  resourceDetails,
  serviceDetails,
  containerDetails,
  zfsDetails,
  smartDetails,
  forecastDetails,
};

describe.each(Object.entries(ALL))('%s', (_name, narrow) => {
  it.each([null, undefined, 'text', 3, [{ a: 1 }]])('reads %j as no details', (v) => {
    expect(narrow(v)).toBeNull();
  });

  it('reads an empty object as details without fields', () => {
    expect(narrow({})).toEqual({});
  });
});

describe('resourceDetails', () => {
  const valid = {
    cpu: 12.5,
    memory: 40,
    memory_used_mb: 1600,
    memory_total_mb: 4000,
    swap: null,
    swap_total_mb: 0,
    swap_used_mb: 0,
    cpu_count: 4,
    load_per_cpu: 0.3,
    load_rated: false,
    problems: { cpu: 'warning', 'disk:/': 'critical' },
    disks: [
      {
        mount: '/',
        percent: 81,
        used_gb: 8.1,
        total_gb: 10,
        free_gb: 1.9,
        inodes_percent: null,
        ignored: true,
      },
    ],
    temperatures: [{ sensor: 'cpu', temp_c: 50, high: 80, critical: 95 }],
  };

  it('returns valid details unchanged', () => {
    expect(resourceDetails(valid)).toEqual(valid);
  });

  it('drops a field of the wrong type and a disk without its mount', () => {
    const d = resourceDetails({
      ...valid,
      cpu: '12',
      problems: { cpu: 3, memory: 'critical' },
      disks: [{ percent: 5 }, { mount: '/var', percent: 'x' }, valid.disks[0]],
    });
    expect(d).not.toHaveProperty('cpu');
    expect(d?.problems).toEqual({ memory: 'critical' });
    expect(d?.disks).toEqual(valid.disks);
  });

  it('reads the old details of another check type as empty fields', () => {
    // A check switched from agent_services keeps those details until its next push.
    expect(resourceDetails({ mode: 'auto', failed: ['a.service'] })).toEqual({});
  });
});

describe('serviceDetails', () => {
  const valid = {
    mode: 'list',
    failed: [],
    enabled_inactive: ['b.service'],
    active_count: 7,
    total: 9,
    watched: [
      { name: 'a.service', state: 'down' },
      { name: 'old.service', running: true },
    ],
  };

  it('returns valid details unchanged', () => {
    expect(serviceDetails(valid)).toEqual(valid);
  });

  it('drops a field of the wrong type', () => {
    const d = serviceDetails({
      ...valid,
      total: '9',
      failed: ['x', 2],
      watched: [{ state: 'down' }],
    });
    expect(d).not.toHaveProperty('total');
    expect(d?.failed).toEqual(['x']);
    expect(d?.watched).toEqual([]);
  });
});

describe('containerDetails', () => {
  const valid = {
    available: true,
    error: null,
    containers: [
      {
        id: 'abc',
        name: 'web',
        image: 'nginx',
        state: 'exited',
        category: 'critical',
        reason: 'exit',
        exit_code: 1,
        restart_count: 0,
      },
      // A category this UI does not know yet passes as it came.
      { name: 'old', state: 'running', category: 'paused' },
    ],
  };

  it('returns valid details unchanged', () => {
    expect(containerDetails(valid)).toEqual(valid);
  });

  it('drops a field of the wrong type and a container without its state', () => {
    const d = containerDetails({
      available: 'no',
      containers: [
        { name: 'x', category: 'ok' },
        { ...valid.containers[0], exit_code: '1' },
      ],
    });
    expect(d).not.toHaveProperty('available');
    const rest: Record<string, unknown> = { ...valid.containers[0] };
    delete rest.exit_code;
    expect(d?.containers).toEqual([rest]);
  });
});

describe('zfsDetails', () => {
  const valid = {
    available: false,
    error: 'not_installed',
    pools: [{ name: 'tank', health: 'ONLINE', capacityPercent: 42 }],
  };

  it('returns valid details unchanged', () => {
    expect(zfsDetails(valid)).toEqual(valid);
  });

  it('drops a field of the wrong type and a pool with a wrong capacity', () => {
    const d = zfsDetails({
      error: 7,
      pools: [{ name: 'bad', health: 'ONLINE', capacityPercent: '42' }, ...valid.pools],
    });
    expect(d).toEqual({ pools: valid.pools });
  });

  it('reads pools that are no list as none', () => {
    expect(zfsDetails({ pools: { name: 'tank' } })).toEqual({});
  });
});

describe('smartDetails', () => {
  const valid = {
    disks: [
      {
        device: '/dev/sda',
        kind: 'HDD',
        protocol: 'ATA',
        model: 'Disk',
        category: 'warning',
        temp_c: 41,
        temp_warn: 55,
        temp_crit: 60,
        power_on_hours: 1000,
        reallocated_sectors: 2,
        pending_sectors: 0,
      },
      {
        device: '/dev/nvme0',
        available_spare_pct: 100,
        percentage_used: 3,
        critical_warning_bits: ['spare'],
      },
    ],
  };

  it('returns valid details unchanged', () => {
    expect(smartDetails(valid)).toEqual(valid);
  });

  it('reads the absent form with its reason', () => {
    expect(smartDetails({ absent: 'no_devices' })).toEqual({ absent: 'no_devices' });
  });

  it('drops a field of the wrong type and a disk without its device', () => {
    const d = smartDetails({
      absent: 1,
      disks: [{ model: 'x' }, { device: '/dev/sdb', temp_c: '40' }],
    });
    expect(d).toEqual({ disks: [{ device: '/dev/sdb' }] });
  });
});

describe('forecastDetails', () => {
  const valid = {
    mounts: [
      { mount: '/', percent: 70, rate_pp_per_hour: 0.2, hours_left: 150 },
      { mount: '/srv', hours_left: null, note: 'not enough samples' },
    ],
  };

  it('returns valid details unchanged', () => {
    expect(forecastDetails(valid)).toEqual(valid);
  });

  it('drops a field of the wrong type and a mount without its name', () => {
    const d = forecastDetails({
      mounts: [{ percent: 3 }, { mount: '/', hours_left: 'soon', percent: 70 }],
    });
    expect(d).toEqual({ mounts: [{ mount: '/', percent: 70 }] });
  });
});
