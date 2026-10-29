// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// api-contracts T24 (R-0687): the section reads its details through
// smartDetails, so details of the wrong form render the empty section instead
// of throwing.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecSmart -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init
// calls matchMedia (missing in jsdom); same stub as SecZfs.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import SecSmart from './SecSmart.svelte';

function check(state: MonitorCheckState): MonitorCheck {
  return {
    id: 'chk-smart',
    serverId: 'srv-1',
    name: 'SMART',
    checkType: 'smart_health',
    interval: '1h',
    severity: 'critical',
    enabled: true,
    state,
  } as MonitorCheck;
}

function texts(el: HTMLElement, selector: string): string[] {
  return Array.from(el.querySelectorAll<HTMLElement>(selector)).map(
    (p) => p.textContent?.replace(/\s+/g, ' ').trim() ?? '',
  );
}

afterEach(cleanup);

describe('SecSmart', () => {
  it('shows the hottest disk and the disk count', () => {
    const disks = [
      { device: '/dev/sda', kind: 'HDD', category: 'ok', temp_c: 38 },
      { device: '/dev/nvme0', kind: 'NVMe', category: 'warning', temp_c: 51 },
    ];
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { disks } })] },
    });
    expect(texts(el, '.mon-line-num')).toEqual(['51']);
    expect(texts(el, '.mon-line-pill')).toEqual(['2 Disks']);
  });

  it('shows a dash for a host without disks', () => {
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { absent: 'no_devices' } })] },
    });
    expect(texts(el, '.mon-line-pill')).toEqual(['—']);
  });

  it('renders the empty section for details of the wrong form', () => {
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { disks: { sda: { temp_c: 40 } } } })] },
    });
    expect(texts(el, '.mon-line-pill')).toEqual(['—']);
    expect(texts(el, '.mon-line-num')).toEqual([]);
  });
});
