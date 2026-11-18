// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0 T1 (R-1558): one object row shows level 1 (badge, reason, since) and at
// most four metrics with their threshold context; a hidden object is grey with its exception; the
// drawer shows every metric, rules, history and the exception.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import ObjectDrawer from './ObjectDrawer.svelte';
import ObjectRow from './ObjectRow.svelte';
import type { Metric, MonObject } from './model';

const NOW = new Date('2026-11-18T09:00:00Z');

const metric = (key: string, extra: Partial<Metric> = {}): Metric => ({
  key,
  label: key,
  value: 1,
  threshold: null,
  ...extra,
});

const DISK: MonObject = {
  key: 'nas-01/disk/wwn-0x5000c500a1b2c3d4',
  kind: 'disk',
  name: 'sda',
  server: 'nas-01',
  identity: ['ST4000VN008', 'HDD 4 TB', 'Pool tank'],
  status: 'warning',
  reason: 'Umgelagerte Sektoren sind seit gestern um 2 gestiegen.',
  since: '2026-11-17T09:00:00Z',
  metrics: [
    metric('temp', {
      label: 'Temperatur',
      value: 41,
      unit: '°C',
      threshold: { warn: 55, crit: 60 },
    }),
    metric('realloc', {
      label: 'Umgelagert',
      value: 8,
      threshold: { warn: 1, crit: 10 },
      status: 'warning',
      note: '+2 seit gestern',
    }),
    metric('pending', { label: 'Ausstehend', value: 0, threshold: { warn: 1, crit: 5 } }),
    metric('hours', { label: 'Laufzeit', value: 31000, unit: 'h' }),
    metric('fifth', { label: 'Fünfte', value: 5, newData: true }),
  ],
  rules: [
    {
      key: 'realloc.rising',
      text: 'Umgelagerte Sektoren steigen',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
      firing: true,
    },
    {
      key: 'temp.max',
      text: 'Temperatur über 60 °C',
      level: 'critical',
      source: 'eigene',
      enabled: false,
    },
  ],
  history: [{ at: '2026-11-17T09:00:00Z', status: 'warning', text: 'Umgelagert 6 → 8' }],
  raw: 'ID# ATTRIBUTE_NAME  VALUE\n  5 Reallocated_Sector_Ct 8',
};

afterEach(cleanup);

describe('ObjectRow', () => {
  it('shows status, name, reason, since and the identity line', () => {
    const { container, getByText } = render(ObjectRow, { object: DISK, now: NOW });
    expect(getByText('Warnung')).toBeTruthy();
    expect(getByText('sda')).toBeTruthy();
    expect(getByText('Umgelagerte Sektoren sind seit gestern um 2 gestiegen.')).toBeTruthy();
    expect(getByText('seit 1 Tag')).toBeTruthy();
    expect(container.querySelector('.identity')?.textContent).toBe(
      'ST4000VN008 · HDD 4 TB · Pool tank',
    );
  });

  it('names since when the object turned bad if that was before the last change', () => {
    const worse = { ...DISK, status: 'critical' as const, badSince: '2026-11-15T09:00:00Z' };
    const row = render(ObjectRow, { object: worse, now: NOW });
    expect(row.container.querySelector('.since')?.textContent).toBe(
      'seit 1 Tag · nicht ok seit 3 Tagen',
    );
    cleanup();
    const drawer = render(ObjectDrawer, { object: worse, now: NOW, onClose: () => {} });
    expect(drawer.container.querySelector('.bad-since')?.textContent?.trim()).toBe(
      '· nicht ok seit 3 Tagen',
    );
    cleanup();
    const plain = render(ObjectRow, { object: DISK, now: NOW });
    expect(plain.container.querySelector('.bad-since')).toBeNull();
  });

  it('puts the server first when the list spans servers', () => {
    const { container } = render(ObjectRow, { object: DISK, now: NOW, showServer: true });
    expect(container.querySelector('.identity')?.textContent).toBe(
      'nas-01 · ST4000VN008 · HDD 4 TB · Pool tank',
    );
  });

  it('shows at most four metrics, each with its threshold context', () => {
    const { container } = render(ObjectRow, { object: DISK, now: NOW });
    const shown = [...container.querySelectorAll('[data-metric]')].map((e) =>
      e.getAttribute('data-metric'),
    );
    expect(shown).toEqual(['temp', 'realloc', 'pending', 'hours']);
    const temp = container.querySelector('[data-metric="temp"]')?.textContent ?? '';
    expect(temp.replace(/\s+/g, ' ').trim()).toBe(
      'Temperatur 41 °C (Warnung ab 55, kritisch ab 60)',
    );
    const realloc = container.querySelector('[data-metric="realloc"]')?.textContent ?? '';
    expect(realloc).toContain('+2 seit gestern');
    const hours = container.querySelector('[data-metric="hours"]')?.textContent ?? '';
    expect(hours).not.toContain('(');
  });

  it('marks a metric the agent does not deliver yet', () => {
    const object = { ...DISK, metrics: [metric('x', { label: 'Neu', newData: true })] };
    const { getByText } = render(ObjectRow, { object, now: NOW });
    expect(getByText('neue Agent-Daten')).toBeTruthy();
  });

  it('greys a hidden object and names its exception instead of the status', () => {
    const object: MonObject = {
      ...DISK,
      exception: {
        effect: 'no-rating',
        scope: 'dieses Objekt',
        reason: 'alte Platte',
        by: 'kevin',
        at: '2026-11-01T10:00:00Z',
        boundValue: '8 umgelagerte Sektoren',
      },
    };
    const { container, getByText, queryByText } = render(ObjectRow, { object, now: NOW });
    expect(container.querySelector('.row')?.classList.contains('hidden')).toBe(true);
    expect(getByText('Ausgeblendet')).toBeTruthy();
    expect(queryByText('Warnung')).toBeNull();
    expect(container.querySelector('.exception')?.textContent).toContain(
      'gilt nur bei 8 umgelagerte Sektoren',
    );
  });

  it('reports its key when clicked', async () => {
    const onOpen = vi.fn();
    const { container } = render(ObjectRow, { object: DISK, now: NOW, onOpen });
    await fireEvent.click(container.querySelector('.row')!);
    expect(onOpen).toHaveBeenCalledWith(DISK.key);
  });
});

describe('ObjectDrawer', () => {
  it('shows every metric, the rules, the history, the raw data and the key', () => {
    const { container, getByText } = render(ObjectDrawer, {
      object: DISK,
      now: NOW,
      onClose: () => {},
    });
    expect(container.querySelectorAll('section:first-of-type tbody tr')).toHaveLength(5);
    expect(getByText('Umgelagerte Sektoren steigen')).toBeTruthy();
    expect(getByText('Umgelagert 6 → 8')).toBeTruthy();
    expect(getByText(DISK.key)).toBeTruthy();
    expect(container.textContent).toContain('eigene · aus');
    expect(container.textContent).toContain('ohne Schwelle');
    expect(container.textContent).toContain('Reallocated_Sector_Ct');
  });

  it('closes on Escape and offers the exception dialog', async () => {
    const onClose = vi.fn();
    const onException = vi.fn();
    const { getByText } = render(ObjectDrawer, { object: DISK, now: NOW, onClose, onException });
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
    await fireEvent.click(getByText('Ausnahme anlegen …'));
    expect(onException).toHaveBeenCalledWith(DISK.key, false);
  });
});
