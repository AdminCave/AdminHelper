// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Drawer sections of the storage kinds (R-1558 T2): SMART table with exit bits in words, vdev
// tree, backup list and trend chart with its limit lines.

import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import BackupList from './details/BackupList.svelte';
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
  });
});
