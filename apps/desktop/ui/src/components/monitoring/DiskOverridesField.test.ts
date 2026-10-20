// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-linux-base-v2 T19 (R-0423): disk_overrides of agent_resources as
// a table, one row per mount with warn, crit and min_free_gb
// (app/check_configs.py _DiskOverride, all three optional).

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorCheckConfig } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import DiskOverridesField from './DiskOverridesField.svelte';
import CheckConfigFields from './CheckConfigFields.svelte';

setLanguage('de');
afterEach(cleanup);

async function renderField(config: MonitorCheckConfig) {
  const r = render(DiskOverridesField, { props: { config } });
  await tick();
  const cells = (label: string) => r.queryAllByLabelText(label) as HTMLInputElement[];
  return {
    ...r,
    mounts: () => cells('Mount'),
    warns: () => cells('Warnung (%)'),
    crits: () => cells('Kritisch (%)'),
    minFree: () => cells('Mindest-GB frei'),
    add: () => fireEvent.click(r.getByRole('button', { name: 'Mount hinzufügen' })),
    remove: (i: number) =>
      fireEvent.click(r.getAllByRole('button', { name: 'Zeile entfernen' })[i]),
  };
}

describe('DiskOverridesField', () => {
  it('stores a new row with a mount and a warning as {"/data": {"warn": 90}}', async () => {
    const config = {} as MonitorCheckConfig;
    const f = await renderField(config);
    expect(f.mounts()).toHaveLength(0);
    await f.add();
    await fireEvent.input(f.mounts()[0], { target: { value: '/data' } });
    await fireEvent.input(f.warns()[0], { target: { value: '90' } });
    expect(config).toEqual({ disk_overrides: { '/data': { warn: 90 } } });
  });

  it('does not store a row without a mount, and keeps it on screen', async () => {
    const config = {} as MonitorCheckConfig;
    const f = await renderField(config);
    await f.add();
    await fireEvent.input(f.warns()[0], { target: { value: '90' } });
    await fireEvent.input(f.mounts()[0], { target: { value: '  ' } });
    expect(config).toEqual({});
    expect(f.warns()[0].value).toBe('90');
    await fireEvent.input(f.mounts()[0], { target: { value: ' /data ' } });
    expect(config).toEqual({ disk_overrides: { '/data': { warn: 90 } } });
  });

  it('stores all three values as numbers, 0 and decimals included', async () => {
    const config = {} as MonitorCheckConfig;
    const f = await renderField(config);
    await f.add();
    await fireEvent.input(f.mounts()[0], { target: { value: '/srv' } });
    await fireEvent.input(f.warns()[0], { target: { value: '0' } });
    await fireEvent.input(f.crits()[0], { target: { value: '97.5' } });
    await fireEvent.input(f.minFree()[0], { target: { value: '250' } });
    expect(config).toEqual({
      disk_overrides: { '/srv': { warn: 0, crit: 97.5, min_free_gb: 250 } },
    });
  });

  it('drops an emptied field from the entry and the key with the last row', async () => {
    const config = {
      disk_overrides: { '/data': { warn: 90, crit: 95, min_free_gb: 100 } },
    } as MonitorCheckConfig;
    const f = await renderField(config);
    await fireEvent.input(f.warns()[0], { target: { value: '' } });
    expect(config).toEqual({ disk_overrides: { '/data': { crit: 95, min_free_gb: 100 } } });
    await fireEvent.input(f.crits()[0], { target: { value: '' } });
    await fireEvent.input(f.minFree()[0], { target: { value: '' } });
    expect(config).toEqual({ disk_overrides: { '/data': {} } });
    await f.remove(0);
    expect(f.mounts()).toHaveLength(0);
    expect('disk_overrides' in config).toBe(false);
  });

  it('drops the key when the mount of the only row is cleared', async () => {
    const config = { disk_overrides: { '/data': { warn: 90 } } } as MonitorCheckConfig;
    const f = await renderField(config);
    await fireEvent.input(f.mounts()[0], { target: { value: '' } });
    expect(config).toEqual({});
  });

  it('shows stored overrides, a missing value as an empty field', async () => {
    const config = {
      disk_overrides: { '/data': { warn: 90, min_free_gb: 100 }, '/boot': { crit: 99 } },
    } as MonitorCheckConfig;
    const f = await renderField(config);
    expect(f.mounts().map((i) => i.value)).toEqual(['/data', '/boot']);
    expect(f.warns().map((i) => i.value)).toEqual(['90', '']);
    expect(f.crits().map((i) => i.value)).toEqual(['', '99']);
    expect(f.minFree().map((i) => i.value)).toEqual(['100', '']);
    // Showing them writes nothing.
    expect(config).toEqual({
      disk_overrides: { '/data': { warn: 90, min_free_gb: 100 }, '/boot': { crit: 99 } },
    });
  });

  it('removes the clicked row and keeps the others', async () => {
    const config = {
      disk_overrides: { '/a': { warn: 70 }, '/b': { warn: 80 }, '/c': { warn: 90 } },
    } as MonitorCheckConfig;
    const f = await renderField(config);
    await f.remove(1);
    expect(f.mounts().map((i) => i.value)).toEqual(['/a', '/c']);
    expect(config).toEqual({ disk_overrides: { '/a': { warn: 70 }, '/c': { warn: 90 } } });
  });

  it('flags a repeated mount and stores only its first row', async () => {
    const config = { disk_overrides: { '/data': { warn: 90 } } } as MonitorCheckConfig;
    const f = await renderField(config);
    expect(f.queryByRole('note')).toBeNull();
    await f.add();
    await fireEvent.input(f.mounts()[1], { target: { value: '/data' } });
    await fireEvent.input(f.warns()[1], { target: { value: '70' } });
    expect(f.getByRole('note').textContent).toContain('/data');
    expect(config).toEqual({ disk_overrides: { '/data': { warn: 90 } } });
    // Without the first row the second one counts, and the hint goes.
    await f.remove(0);
    expect(f.queryByRole('note')).toBeNull();
    expect(config).toEqual({ disk_overrides: { '/data': { warn: 70 } } });
  });

  it('carries the backend bounds on the number fields', async () => {
    const f = await renderField({ disk_overrides: { '/data': {} } } as MonitorCheckConfig);
    for (const input of [f.warns()[0], f.crits()[0]]) {
      expect([input.type, input.min, input.max]).toEqual(['number', '0', '100']);
    }
    expect([f.minFree()[0].min, f.minFree()[0].max]).toEqual(['0', '1000000']);
  });

  // The template editor keys its check cards by index: removing a card hands
  // the field of the card below it the next card's config.
  it('follows a new config object', async () => {
    const first = { disk_overrides: { '/a': { warn: 70 } } } as MonitorCheckConfig;
    const second = { disk_overrides: { '/b': { crit: 99 } } } as MonitorCheckConfig;
    const f = await renderField(first);
    await f.rerender({ config: second });
    await tick();
    expect(f.mounts().map((i) => i.value)).toEqual(['/b']);
    await fireEvent.input(f.warns()[0], { target: { value: '80' } });
    expect(second).toEqual({ disk_overrides: { '/b': { warn: 80, crit: 99 } } });
    expect(first).toEqual({ disk_overrides: { '/a': { warn: 70 } } });
  });

  it('is part of the agent_resources form and of no other', async () => {
    const config = { disk_overrides: { '/data': { warn: 90 } } } as MonitorCheckConfig;
    const resources = render(CheckConfigFields, {
      props: { checkType: 'agent_resources', config },
    });
    await tick();
    expect(resources.getByText('Schwellen je Mount')).toBeTruthy();
    expect((resources.getByLabelText('Mount') as HTMLInputElement).value).toBe('/data');
    resources.unmount();

    const smart = render(CheckConfigFields, { props: { checkType: 'smart_health', config } });
    await tick();
    expect(smart.queryByText('Schwellen je Mount')).toBeNull();
  });

  it('labels the table in English', async () => {
    setLanguage('en');
    try {
      const config = {} as MonitorCheckConfig;
      const r = render(DiskOverridesField, { props: { config } });
      await tick();
      expect(r.getByText('Thresholds per mount')).toBeTruthy();
      expect(r.getByText('Exact mount paths; an empty field takes the global value.')).toBeTruthy();
      await fireEvent.click(r.getByRole('button', { name: 'Add mount' }));
      for (const label of ['Mount', 'Warning (%)', 'Critical (%)', 'Min. free GB']) {
        expect(r.getAllByRole('columnheader', { name: label })).toHaveLength(1);
        expect(r.getByLabelText(label)).toBeTruthy();
      }
      await fireEvent.input(r.getByLabelText('Mount'), { target: { value: '/data' } });
      await fireEvent.click(r.getByRole('button', { name: 'Add mount' }));
      await fireEvent.input(r.getAllByLabelText('Mount')[1], { target: { value: '/data' } });
      expect(r.getByRole('note').textContent).toContain(
        'Mount entered more than once, only the first row counts: /data',
      );
      await fireEvent.click(r.getAllByRole('button', { name: 'Remove row' })[1]);
      expect(r.getAllByLabelText('Mount')).toHaveLength(1);
    } finally {
      setLanguage('de');
    }
  });
});
