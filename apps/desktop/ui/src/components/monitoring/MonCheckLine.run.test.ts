// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// code-review-fixes T2 (B1): the run button used to be offered unconditionally,
// while the backend does nothing for push-evaluated and disabled checks. Pins
// that the dead action is no longer clickable and that the tooltip explains why.

import { describe, it, expect, afterEach, vi } from 'vitest';

// MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init calls
// matchMedia (missing in jsdom). The chart never renders here (collapsed line) —
// stub the lib away, same as MonCheckLine.edit.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import type { MonitorCheck } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import MonCheckLine from './section/MonCheckLine.svelte';

const label = createRawSnippet(() => ({ render: () => '<span>c</span>' }));

function check(over: Partial<MonitorCheck> = {}): MonitorCheck {
  return {
    id: 'c1',
    name: 'c',
    checkType: 'ping',
    interval: '5m',
    severity: 'critical',
    enabled: true,
    ...over,
  } as MonitorCheck;
}

// Select by aria-label, not by index: an index would silently shift the day a
// button is inserted before "run" (MonCheckLine.edit.test.ts does the same).
function runButton(container: HTMLElement, label: string | RegExp): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.mon-line-action'));
  const btn = btns.find((b) => {
    const al = b.getAttribute('aria-label') ?? '';
    return typeof label === 'string' ? al === label : label.test(al);
  });
  if (!btn) throw new Error(`run button not found for ${label}`);
  return btn;
}

afterEach(cleanup);

describe('MonCheckLine run button', () => {
  it('stays clickable for an enabled pull check', () => {
    setLanguage('en');
    const { container } = render(MonCheckLine, { props: { check: check(), label } });
    const btn = runButton(container, 'Run now');
    expect(btn.disabled).toBe(false);
    expect(btn.title).toBe('Run now');
  });

  it('is disabled for a push-evaluated check and says why', () => {
    setLanguage('en');
    const { container } = render(MonCheckLine, {
      props: { check: check({ checkType: 'smart_health' }), label },
    });
    const btn = runButton(container, /agent push/);
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain('agent push');
  });

  it('is disabled for a disabled check and says why', () => {
    setLanguage('en');
    const { container } = render(MonCheckLine, {
      props: { check: check({ enabled: false }), label },
    });
    const btn = runButton(container, /disabled/);
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain('disabled');
  });

  it('keeps agent_ping runnable — the scheduler evaluates it', () => {
    // agent_ping measures the ABSENCE of a push and is deliberately not push-only.
    setLanguage('en');
    const { container } = render(MonCheckLine, {
      props: { check: check({ checkType: 'agent_ping' }), label },
    });
    expect(runButton(container, 'Run now').disabled).toBe(false);
  });
});
