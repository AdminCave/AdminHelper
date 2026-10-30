// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// api-contracts T24 (R-0687): the section reads its details through
// forecastDetails, so details of the wrong form render the empty section
// instead of throwing.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecForecast -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module
// init calls matchMedia (missing in jsdom); same stub as SecZfs.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import SecForecast from './SecForecast.svelte';

function check(state: MonitorCheckState): MonitorCheck {
  return {
    id: 'chk-forecast',
    serverId: 'srv-1',
    name: 'Forecast',
    checkType: 'disk_forecast',
    interval: '1h',
    severity: 'warning',
    enabled: true,
    state,
  } as MonitorCheck;
}

function pills(el: HTMLElement): { text: string; cls: string }[] {
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-line-pill')).map((p) => ({
    text: p.textContent?.replace(/\s+/g, ' ').trim() ?? '',
    cls: p.className,
  }));
}

setLanguage('de');
afterEach(cleanup);

describe('SecForecast', () => {
  it('shows each mount with its hours left, a dash or stable', () => {
    const mounts = [
      { mount: '/', percent: 90, rate_pp_per_hour: 1.5, hours_left: 6.6 },
      { mount: '/srv', hours_left: null, note: 'not enough samples' },
      { mount: '/home', percent: 20, hours_left: null },
    ];
    const { container: el } = render(SecForecast, {
      props: { checks: [check({ status: 'critical', details: { mounts } })] },
    });
    const all = pills(el);
    expect(all.map((p) => p.text)).toEqual(['/ ~7h', '/srv —', '/home stabil']);
    expect(all[0].cls).toContain('pill-crit');
  });

  it('renders the empty section for details of the wrong form', () => {
    const { container: el } = render(SecForecast, {
      props: {
        checks: [check({ status: 'ok', details: { mounts: { '/': { hours_left: 3 } } } })],
      },
    });
    expect(pills(el).map((p) => p.text)).toEqual(['—']);
  });

  it('drops a mount whose name is not a string', () => {
    const { container: el } = render(SecForecast, {
      props: {
        checks: [check({ status: 'ok', details: { mounts: [{ mount: 3, hours_left: 2 }] } })],
      },
    });
    expect(pills(el).map((p) => p.text)).toEqual(['—']);
  });
});
