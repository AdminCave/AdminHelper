// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T20: form-level guardrails mirroring the T4 backend boundary — number inputs
// carry min/max, a warn>=crit misconfiguration shows an inline hint (nvme_spare
// excluded: lower is worse there), and the dead check_restarts checkbox is gone.

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
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
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'docker_health', config: {} as MonitorCheckConfig },
    });
    await tick();
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
  });
});
