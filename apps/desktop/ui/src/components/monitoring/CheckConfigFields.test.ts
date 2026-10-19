// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T20: form-level guardrails mirroring the T4 backend boundary — number inputs
// carry min/max, a warn>=crit misconfiguration shows an inline hint (nvme_spare
// excluded: lower is worse there), and the dead check_restarts checkbox is gone.

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorCheckConfig } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import CheckConfigFields from './CheckConfigFields.svelte';

setLanguage('de');
afterEach(cleanup);

function inputFor(container: HTMLElement, label: string): HTMLInputElement {
  const fields = Array.from(container.querySelectorAll('label.field'));
  const match = fields.find((f) => f.textContent?.includes(label));
  if (!match) throw new Error(`no field labelled ${label}`);
  return match.querySelector('input') as HTMLInputElement;
}

describe('CheckConfigFields guardrails (T20)', () => {
  it('percent thresholds carry min/max mirroring the backend boundary', async () => {
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'agent_resources', config: {} as MonitorCheckConfig },
    });
    await tick();
    const cpuWarn = inputFor(container, 'CPU Warn');
    expect(cpuWarn.min).toBe('0');
    expect(cpuWarn.max).toBe('100');
    // hysteresis_pp is editable now (T6 introduced the key).
    expect(inputFor(container, 'Hysterese').max).toBe('50');
  });

  it('shows the warn>=crit hint only for genuinely inverted pairs', async () => {
    const bad = { cpu_warn: 95, cpu_crit: 90 } as MonitorCheckConfig;
    const { container, getByRole } = render(CheckConfigFields, {
      props: { checkType: 'agent_resources', config: bad },
    });
    await tick();
    expect(getByRole('note').textContent).toContain('CPU');
    expect(container.querySelectorAll('.cfg-hint').length).toBe(1);
  });

  it('nvme_spare warn>crit is NOT flagged (lower is worse there)', async () => {
    const spare = { nvme_spare_warn: 20, nvme_spare_crit: 10 } as MonitorCheckConfig;
    const { queryByRole } = render(CheckConfigFields, {
      props: { checkType: 'smart_health', config: spare },
    });
    await tick();
    expect(queryByRole('note')).toBeNull();
  });

  it('docker_health no longer renders the dead check_restarts checkbox', async () => {
    const config = {} as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'docker_health', config },
    });
    await tick();
    // The one checkbox left is the outage switch (R-0419), and it never writes
    // check_restarts.
    const boxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(boxes).toHaveLength(1);
    await fireEvent.click(boxes[0]);
    expect(config).toEqual({ alert_on_unavailable: false });
  });
});

// monitoring-silent-outages T11 (R-0419): a docker or zfs check the agent
// cannot read is a warning now, switchable per check, and the form had no
// switch. At the default the key must go: a template's check whose config
// carried {"alert_on_unavailable": true} would differ from the template's {}
// and count as changed by the user (mark_overrides).
describe('CheckConfigFields outage switch (R-0419)', () => {
  const TYPES = ['zfs_health', 'docker_health'] as const;

  async function outageBox(
    checkType: (typeof TYPES)[number],
    config: MonitorCheckConfig,
    label = 'Ausfall melden',
  ): Promise<HTMLInputElement> {
    const { container } = render(CheckConfigFields, { props: { checkType, config } });
    await tick();
    const input = inputFor(container, label);
    expect(input.type).toBe('checkbox');
    return input;
  }

  it.each(TYPES)('%s shows the switch, on by default, without writing it', async (type) => {
    const config = {} as MonitorCheckConfig;
    expect((await outageBox(type, config)).checked).toBe(true);
    expect(config).toEqual({});
  });

  it.each(TYPES)('%s writes false when switched off', async (type) => {
    const config = {} as MonitorCheckConfig;
    await fireEvent.click(await outageBox(type, config));
    expect(config).toEqual({ alert_on_unavailable: false });
  });

  it.each(TYPES)('%s drops the key instead of writing true when switched back on', async (type) => {
    const config = {} as MonitorCheckConfig;
    const box = await outageBox(type, config);
    await fireEvent.click(box);
    await fireEvent.click(box);
    expect(box.checked).toBe(true);
    expect(config).toEqual({});
  });

  it('shows a stored false as off and drops it when switched on', async () => {
    const config = { alert_on_unavailable: false } as MonitorCheckConfig;
    const box = await outageBox('zfs_health', config);
    expect(box.checked).toBe(false);
    await fireEvent.click(box);
    expect(config).toEqual({});
  });

  it('labels the switch in English', async () => {
    setLanguage('en');
    try {
      expect((await outageBox('docker_health', {}, 'Report outage')).checked).toBe(true);
    } finally {
      setLanguage('de');
    }
  });
});

// monitoring-services T7 (R-0418): the list mode now takes names with or
// without .service and aliases, ignore takes globs; the editor says so. A
// name entered twice gave SecServices a duplicate {#each} key.
describe('CheckConfigFields service_process (R-0418)', () => {
  function hints(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('.field-hint')).map(
      (h) => h.textContent?.trim() ?? '',
    );
  }

  it('shows the list hint in list mode and the glob hint in auto mode', async () => {
    const list = render(CheckConfigFields, {
      props: { checkType: 'service_process', config: { mode: 'list' } as MonitorCheckConfig },
    });
    await tick();
    const listHints = hints(list.container);
    expect(listHints).toHaveLength(1);
    expect(listHints[0]).toContain('.service');
    expect(listHints[0]).toContain('Aliase');
    expect(listHints[0]).not.toContain('foo@*');
    list.unmount();

    const auto = render(CheckConfigFields, {
      props: { checkType: 'service_process', config: { mode: 'auto' } as MonitorCheckConfig },
    });
    await tick();
    expect(hints(auto.container)).toEqual([expect.stringContaining('foo@*')]);
  });

  it('shows the hints in English', async () => {
    setLanguage('en');
    try {
      const list = render(CheckConfigFields, {
        props: { checkType: 'service_process', config: { mode: 'list' } as MonitorCheckConfig },
      });
      await tick();
      expect(hints(list.container)).toEqual([expect.stringContaining('aliases')]);
      list.unmount();

      const auto = render(CheckConfigFields, {
        props: { checkType: 'service_process', config: { mode: 'auto' } as MonitorCheckConfig },
      });
      await tick();
      expect(hints(auto.container)).toEqual([expect.stringContaining('Glob patterns')]);
    } finally {
      setLanguage('de');
    }
  });

  it('stores a name entered twice once', async () => {
    const config = { mode: 'list' } as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'service_process', config },
    });
    await tick();
    const input = inputFor(container, 'Dienste');
    await fireEvent.input(input, { target: { value: 'sshd, nginx, sshd , nginx' } });
    await fireEvent.change(input);
    expect(config.services).toEqual(['sshd', 'nginx']);
  });

  it('stores an ignore pattern entered twice once', async () => {
    const config = { mode: 'auto' } as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'service_process', config },
    });
    await tick();
    const input = inputFor(container, 'Ignorieren');
    await fireEvent.input(input, { target: { value: 'foo@*, bar.service, foo@*' } });
    await fireEvent.change(input);
    expect(config.ignore).toEqual(['foo@*', 'bar.service']);
  });

  // The field re-renders from config: dropping "nginx" from "nginx, nginx" per
  // keystroke would turn the typing of "nginx, nginx-exporter" into
  // "nginx-exporter". Only leaving the field (change) drops the repeat.
  it('keeps a repeat while typing and drops it on change', async () => {
    const config = { mode: 'list' } as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'service_process', config },
    });
    await tick();
    const input = inputFor(container, 'Dienste');
    await fireEvent.input(input, { target: { value: 'nginx, nginx' } });
    expect(config.services).toEqual(['nginx', 'nginx']);
    await fireEvent.change(input);
    expect(config.services).toEqual(['nginx']);
  });
});
