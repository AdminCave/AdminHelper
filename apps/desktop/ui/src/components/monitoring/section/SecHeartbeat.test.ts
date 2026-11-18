// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1564: the heartbeat read the first number of the check message as seconds, so
// "Agent unreachable for 47 min (limit: 15 min)" showed as 47 s. The checker words the
// age in minutes when the agent is gone and in seconds while it reports.

import { describe, it, expect, afterEach, vi } from 'vitest';

vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import type { MonitorCheck } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import SecHeartbeat from './SecHeartbeat.svelte';

function check(message: string | null): MonitorCheck {
  return {
    id: 'chk-hb',
    serverId: 'srv-1',
    name: 'Agent',
    checkType: 'agent_ping',
    interval: '1m',
    severity: 'critical',
    enabled: true,
    state: { status: 'critical', message },
  } as MonitorCheck;
}

function shown(message: string | null): string {
  const { container } = render(SecHeartbeat, { checks: [check(message)] });
  const num = container.querySelector('.mon-line-num')?.textContent?.trim();
  const unit = container.querySelector('.mon-line-unit')?.textContent?.trim();
  return `${num} ${unit}`.trim();
}

afterEach(() => {
  cleanup();
  setLanguage('de');
});

describe('SecHeartbeat age', () => {
  it('reads minutes from an unreachable agent, not the number as seconds', () => {
    expect(shown('Agent unreachable for 47 min (limit: 15 min)')).toBe('47 min');
  });

  it('reads seconds from an active agent', () => {
    expect(shown('Agent active (last report 12s ago)')).toBe('12 s');
  });

  it('shows a dash for a message of another form', () => {
    expect(shown('Agent has never reported (limit: 15 min)')).toBe('—');
    expect(shown(null)).toBe('—');
  });
});
