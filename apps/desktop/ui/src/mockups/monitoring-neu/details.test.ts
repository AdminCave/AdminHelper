// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Drawer sections (R-1558): SMART table with exit bits in words, vdev tree, backup list and trend
// chart with limit lines and forecast (T2, T3), journal excerpt and top processes (T3).

import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import BackupList from './details/BackupList.svelte';
import LogLines from './details/LogLines.svelte';
import ProcessTable from './details/ProcessTable.svelte';
import SmartAttributes from './details/SmartAttributes.svelte';
import TrendChart from './details/TrendChart.svelte';
import VdevTree from './details/VdevTree.svelte';

afterEach(cleanup);

describe('SmartAttributes', () => {
  it('lists the attributes and names the exit bits as hex with plain words', () => {
    const { container } = render(SmartAttributes, {
      detail: {
        type: 'smart',
        title: 'SMART-Attribute',
        rows: [
          { id: 5, name: 'Reallocated_Sector_Ct', raw: '8', normalized: 97, threshold: 10 },
          { id: 9, name: 'Power_On_Hours', raw: '38190', normalized: 57, threshold: 0 },
        ],
        exitBits: [
          { bit: 3, text: 'SMART meldet: Platte fällt aus' },
          { bit: 6, text: 'Das Fehlerprotokoll enthält Einträge' },
        ],
      },
    });
    const rows = [...container.querySelectorAll('[data-attr]')].map((r) =>
      r.getAttribute('data-attr'),
    );
    expect(rows).toEqual(['Reallocated_Sector_Ct', 'Power_On_Hours']);
    const bits = [...container.querySelectorAll('.bits li')].map((l) => l.textContent?.trim());
    expect(bits).toEqual([
      '0x08 SMART meldet: Platte fällt aus',
      '0x40 Das Fehlerprotokoll enthält Einträge',
    ]);
  });

  it('shows no exit-bit list when smartctl exited clean', () => {
    const { container } = render(SmartAttributes, {
      detail: { type: 'smart', title: 'SMART-Attribute', rows: [], exitBits: [] },
    });
    expect(container.querySelector('.bits')).toBeNull();
  });
});

describe('VdevTree', () => {
  it('shows the pool, its vdevs and devices with state and counters', () => {
    const leaf = (name: string, state = 'ONLINE', cksum = 0) => ({
      name,
      state,
      status: state === 'ONLINE' ? ('ok' as const) : ('critical' as const),
      read: 0,
      write: 0,
      cksum,
    });
    const { container } = render(VdevTree, {
      detail: {
        type: 'vdev',
        title: 'Aufbau',
        root: {
          ...leaf('rpool', 'DEGRADED'),
          children: [
            {
              ...leaf('mirror-0', 'DEGRADED'),
              children: [leaf('sda3'), { ...leaf('sdd3', 'FAULTED', 4), note: 'zu viele Fehler' }],
            },
          ],
        },
      },
    });
    const names = [...container.querySelectorAll('[data-vdev]')].map((r) =>
      r.getAttribute('data-vdev'),
    );
    expect(names).toEqual(['rpool', 'mirror-0', 'sda3', 'sdd3']);
    const faulted = container.querySelector('[data-vdev="sdd3"]')?.textContent ?? '';
    expect(faulted).toContain('FAULTED');
    expect(faulted).toContain('zu viele Fehler');
  });
});

describe('BackupList', () => {
  it('shows time, size, storage with protection and the verification in words', () => {
    const { container, getByText } = render(BackupList, {
      detail: {
        type: 'backups',
        title: 'Backups',
        retention: 'keep-daily 7',
        rows: [
          { at: '2026-11-18T03:00:00Z', size: '6,2 GB', storage: 'pbs-store', verify: 'failed' },
          {
            at: '2026-11-17T03:00:00Z',
            size: '6,2 GB',
            storage: 'pbs-store',
            verify: 'ok',
            protected: true,
          },
        ],
      },
    });
    const rows = [...container.querySelectorAll('tbody tr')].map((r) =>
      [...r.querySelectorAll('td')].map((td) => td.textContent?.trim()),
    );
    expect(rows).toEqual([
      ['18.11.2026, 03:00', '6,2 GB', 'pbs-store', 'Verifizierung fehlgeschlagen'],
      ['17.11.2026, 03:00', '6,2 GB', 'pbs-store · geschützt', 'verifiziert'],
    ]);
    expect(getByText('Aufbewahrung: keep-daily 7')).toBeTruthy();
  });
});

describe('TrendChart', () => {
  const points = [
    { at: '2026-11-16T09:00:00Z', value: 49 },
    { at: '2026-11-17T09:00:00Z', value: 56 },
    { at: '2026-11-18T09:00:00Z', value: 58 },
  ];

  it('draws the series and a dashed line per limit', () => {
    const { container } = render(TrendChart, {
      detail: {
        type: 'trend',
        title: 'Temperatur',
        unit: '°C',
        points,
        threshold: { warn: 55, crit: 60 },
      },
    });
    const limits = [...container.querySelectorAll('[data-limit]')].map((l) =>
      l.getAttribute('data-limit'),
    );
    expect(limits).toEqual(['warn', 'crit']);
    expect(
      container.querySelector('polyline.series')?.getAttribute('points')?.split(' '),
    ).toHaveLength(3);
    expect(container.querySelector('svg')?.getAttribute('aria-label')).toBe(
      'Temperatur: zuletzt 58 °C',
    );
    const crit = Number(container.querySelector('[data-limit="crit"]')?.getAttribute('y1'));
    const warn = Number(container.querySelector('[data-limit="warn"]')?.getAttribute('y1'));
    expect(crit).toBeLessThan(warn);
  });

  it('draws no limit line without a threshold', () => {
    const { container } = render(TrendChart, {
      detail: { type: 'trend', title: 'Größe', unit: 'GB', points },
    });
    expect(container.querySelectorAll('[data-limit]')).toHaveLength(0);
    expect(container.querySelector('polyline.forecast')).toBeNull();
  });

  it('continues the series dashed with the forecast, from the last measured point', () => {
    const { container } = render(TrendChart, {
      detail: {
        type: 'trend',
        title: 'Belegung',
        unit: '%',
        points,
        threshold: { warn: 80, crit: 90 },
        forecast: [{ at: '2026-11-27T09:00:00Z', value: 100 }],
      },
    });
    const series = container.querySelector('polyline.series')?.getAttribute('points')?.split(' ');
    const forecast = container
      .querySelector('polyline.forecast')
      ?.getAttribute('points')
      ?.split(' ');
    expect(forecast).toHaveLength(2);
    expect(forecast?.[0]).toBe(series?.at(-1));
    // The time axis reaches the forecast: the last measured point is no longer at the right edge.
    expect(Number(series?.at(-1)?.split(',')[0])).toBeLessThan(Number(forecast?.[1].split(',')[0]));
    expect(container.querySelector('.caption')?.textContent).toBe(
      '16.11.2026, 09:00 bis 18.11.2026, 09:00 · zuletzt 58 % · Warnung ab 80, kritisch ab 90' +
        ' · gestrichelt: Prognose, 100 % am 27.11.2026, 09:00',
    );
  });

  it('says so instead of failing when there are no points yet', () => {
    const { container } = render(TrendChart, {
      detail: { type: 'trend', title: 'Belegung', unit: '%', points: [] },
    });
    expect(container.querySelector('svg')).toBeNull();
    expect(container.querySelector('.caption')?.textContent).toBe('Noch keine Messwerte.');
  });
});

describe('LogLines', () => {
  it('shows time, source and text per line with the priority, and where the full log is', () => {
    const { container } = render(LogLines, {
      detail: {
        type: 'log',
        title: 'Journal',
        lines: [
          { at: '2026-11-18T08:14:05Z', source: 'nginx', priority: 'err', text: 'open() failed' },
          { at: '2026-11-18T08:14:06Z', source: 'systemd', priority: 'info', text: 'Stopped.' },
        ],
        more: 'journalctl -u nginx.service',
      },
    });
    const lines = [...container.querySelectorAll('li')].map((l) => [
      l.getAttribute('data-priority'),
      ...[...l.querySelectorAll('.at, .src, .text')].map((s) => s.textContent?.trim()),
    ]);
    expect(lines).toEqual([
      ['err', '08:14:05', 'nginx', 'open() failed'],
      ['info', '08:14:06', 'systemd', 'Stopped.'],
    ]);
    expect(container.querySelector('li[data-priority="err"] .dot')?.children).toHaveLength(1);
    expect(container.querySelector('li[data-priority="info"] .dot')?.children).toHaveLength(0);
    expect(container.querySelector('.more code')?.textContent).toBe('journalctl -u nginx.service');
  });
});

describe('ProcessTable', () => {
  const rows = [
    { pid: 48211, name: 'postgres', user: 'postgres', cpu: 71.4, memMb: 9812 },
    { pid: 1022, name: 'pgbouncer', user: 'postgres', cpu: 6.1, memMb: 18 },
  ];

  it('lists the processes with CPU and memory and marks the sort column', () => {
    const { container } = render(ProcessTable, {
      detail: { type: 'processes', title: 'Top-Prozesse', sortedBy: 'cpu', rows },
    });
    const cells = [...container.querySelectorAll('tbody tr')].map((r) =>
      [...r.querySelectorAll('td')].map((td) => td.textContent?.trim()),
    );
    expect(cells).toEqual([
      ['48211', 'postgres', 'postgres', '71,4 %', '9.812 MB'],
      ['1022', 'pgbouncer', 'postgres', '6,1 %', '18 MB'],
    ]);
    expect(container.querySelector('th.sorted')?.textContent).toBe('CPU');
    expect(container.textContent).not.toContain('neue Agent-Daten');
  });

  it('marks the list as new agent data', () => {
    const { container } = render(ProcessTable, {
      detail: { type: 'processes', title: 'Top-Prozesse', sortedBy: 'mem', rows, newData: true },
    });
    expect(container.querySelector('th.sorted')?.textContent).toBe('RAM');
    expect(container.querySelector('p')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Sortiert nach RAM, Stand der letzten Meldung neue Agent-Daten',
    );
  });
});
