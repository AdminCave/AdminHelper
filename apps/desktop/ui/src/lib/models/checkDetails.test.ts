// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  backupGuestDetails,
  containerDetails,
  forecastDetails,
  probeDetails,
  resourceDetails,
  serviceDetails,
  smartDetails,
  systemStateNames,
  zfsDetails,
} from './checkDetails';

const ALL = {
  backupGuestDetails,
  resourceDetails,
  serviceDetails,
  containerDetails,
  zfsDetails,
  smartDetails,
  forecastDetails,
  probeDetails,
  systemStateNames,
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

  // arch-monitoring-ui-2 T9 (R-1227): the busiest processes under high load.
  const top = {
    cpu: [{ pid: 812, name: 'php-fpm', cpu_pct: 87.5 }],
    memory: [{ pid: 4021, name: 'clamd', rss: 1_288_490_188 }],
  };

  it('returns the top processes unchanged', () => {
    expect(resourceDetails({ ...valid, top_processes: top })).toEqual({
      ...valid,
      top_processes: top,
    });
  });

  it('drops a top process without pid, name or number and a list of the wrong type', () => {
    const d = resourceDetails({
      ...valid,
      top_processes: {
        cpu: [
          { name: 'x', cpu_pct: 1 },
          { pid: 2, cpu_pct: 1 },
          { pid: 3, name: 'y', cpu_pct: '1' },
          { pid: 4, name: 'z', rss: 1 },
          top.cpu[0],
        ],
        memory: { pid: 1, name: 'clamd', rss: 1 },
      },
    });
    expect(d?.top_processes).toEqual({ cpu: top.cpu });
  });

  it('drops a memory process without pid, name or a numeric rss', () => {
    const d = resourceDetails({
      ...valid,
      top_processes: {
        memory: [
          { pid: 1, name: 'x' },
          { pid: 2, name: 'y', rss: '1' },
          { name: 'z', rss: 1 },
          { pid: 3, rss: 1 },
          { pid: 4, name: 'w', cpu_pct: 1 },
          top.memory[0],
        ],
      },
    });
    expect(d?.top_processes).toEqual({ memory: top.memory });
  });

  it('leaves out top processes that are no object', () => {
    expect(resourceDetails({ ...valid, top_processes: [top.cpu[0]] })).toEqual(valid);
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

  // arch-monitoring-ui-2 T10 (R-1227): compose project, ports and start time per container.
  const compose = {
    ...valid.containers[0],
    compose_project: 'mailcow',
    ports: ['0.0.0.0:443->443/tcp', '[::]:443->443/tcp'],
    started_at: 1_762_900_000,
  };

  it('returns compose project, ports and start time unchanged', () => {
    expect(containerDetails({ ...valid, containers: [compose] })).toEqual({
      ...valid,
      containers: [compose],
    });
  });

  it('drops a compose field of the wrong type and keeps the container', () => {
    const d = containerDetails({
      containers: [
        { ...compose, compose_project: 7, ports: '443/tcp', started_at: '1762900000' },
        { ...compose, ports: ['443/tcp', 443, null] },
      ],
    });
    expect(d?.containers).toEqual([valid.containers[0], { ...compose, ports: ['443/tcp'] }]);
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

  // arch-monitoring-ui-2 T10 (R-1227): scrub, vdev errors and fragmentation per pool.
  const detailed = {
    ...valid.pools[0],
    fragmentationPercent: 12,
    scrub: { state: 'FINISHED', errors: 0, end: 1_762_900_000 },
    vdevErrors: [{ name: 'sda', read: 0, write: 1, checksum: 3 }],
  };

  it('returns scrub, vdev errors and fragmentation unchanged', () => {
    expect(zfsDetails({ pools: [detailed] })).toEqual({ pools: [detailed] });
  });

  it('drops a scrub without state or errors, a partial vdev and a wrong fragmentation', () => {
    const d = zfsDetails({
      pools: [
        { ...detailed, scrub: { state: 'FINISHED' }, fragmentationPercent: '12' },
        { ...detailed, scrub: { errors: 0 } },
        {
          ...detailed,
          scrub: { state: 'SCANNING', errors: 0, end: 'soon' },
          vdevErrors: [{ name: 'sdb', read: 1, write: 0 }, 'sdc', ...detailed.vdevErrors],
        },
      ],
    });
    const vdevErrors = detailed.vdevErrors;
    expect(d?.pools).toEqual([
      { ...valid.pools[0], vdevErrors },
      { ...valid.pools[0], fragmentationPercent: 12, vdevErrors },
      { ...detailed, scrub: { state: 'SCANNING', errors: 0 } },
    ]);
  });
});

// arch-monitoring-ui-2 T10 (R-1227): the backup details of one guest.
describe('backupGuestDetails', () => {
  const valid = {
    backupStorage: 'pbs',
    backupSize: 12_884_901_888,
    backupVerify: 'ok',
    backupJobs: [{ id: 'backup-nightly', schedule: '02:00', storage: 'pbs' }],
    backupError: 'ERROR: Backup of VM 104 failed - job failed',
    backupErrorTs: 1_762_900_000,
  };

  it('returns valid details unchanged and ignores the fields of the guest beside them', () => {
    expect(
      backupGuestDetails({ ...valid, vmid: 104, name: 'web', backupStatus: 'ok', ageHours: 3 }),
    ).toEqual(valid);
  });

  it('keeps an empty job list: no job covers the guest', () => {
    expect(backupGuestDetails({ backupJobs: [] })).toEqual({ backupJobs: [] });
  });

  it('drops a field of the wrong type and a job that is no object', () => {
    const d = backupGuestDetails({
      ...valid,
      backupSize: '12 GiB',
      backupVerify: null,
      backupJobs: ['backup-nightly', { id: 7, schedule: 'daily' }, ...valid.backupJobs],
      backupErrorTs: '1762900000',
    });
    expect(d).toEqual({
      backupStorage: 'pbs',
      backupJobs: [{ schedule: 'daily' }, ...valid.backupJobs],
      backupError: valid.backupError,
    });
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

describe('probeDetails', () => {
  const valid = {
    ts: 1_800_000_000,
    status: 'ok',
    error: null,
    measured_ts: 1_799_999_990,
    values: { duration_ms: 12, detail: 'HTTP/1.1 200', healthy: true, version: null },
    baseline: null,
    problems: ['duration_ms 12 > 10'],
  };

  it('returns valid details unchanged', () => {
    expect(probeDetails(valid)).toEqual(valid);
  });

  it('keeps only scalar values and text problems', () => {
    const d = probeDetails({
      ...valid,
      status: 3,
      values: { a: [1], b: { c: 1 }, d: Number.NaN, e: 'x' },
      baseline: { a: 1, b: [2] },
      problems: ['p', 7],
    });
    expect(d).not.toHaveProperty('status');
    expect(d?.values).toEqual({ e: 'x' });
    expect(d?.baseline).toEqual({ a: 1 });
    expect(d?.problems).toEqual(['p']);
  });
});

// arch-monitoring-ui-2 T9 (R-1227): the names behind the counts of a system_state check.
describe('systemStateNames', () => {
  const valid = {
    security_packages: ['openssl', 'libssl3'],
    reboot_packages: ['linux-image-amd64'],
    oom_processes: [{ pid: 4711, name: 'java' }],
  };

  it('returns valid names unchanged and ignores the counts beside them', () => {
    expect(
      systemStateNames({ ...valid, security_updates: 2, reboot_required: true, problems: [] }),
    ).toEqual(valid);
  });

  it('keeps only text names and processes with pid and name', () => {
    const d = systemStateNames({
      security_packages: ['openssl', 3, null],
      reboot_packages: 'linux-image-amd64',
      oom_processes: [{ pid: 1 }, { name: 'x' }, { pid: '2', name: 'y' }, valid.oom_processes[0]],
    });
    expect(d).toEqual({ security_packages: ['openssl'], oom_processes: valid.oom_processes });
  });

  it('reads the details of an agent before the names as empty fields', () => {
    expect(
      systemStateNames({
        reboot_required: true,
        time_synchronized: true,
        security_updates: 3,
        oom_kills: 0,
        problems: ['reboot'],
      }),
    ).toEqual({});
  });
});
