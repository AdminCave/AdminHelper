// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T18: check CRUD lives on the monitoring page now — the check line's edit
// button and the dashboard's add button drive the store-backed check editor
// (no callback threading through the section components).

import { describe, it, expect, afterEach, vi } from 'vitest';

// MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init calls
// matchMedia (missing in jsdom). The chart is never rendered here (collapsed
// line) — stub the lib away.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick, createRawSnippet } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { checkEditor, closeCheckEditor, monitoring, openCheckEditor } from '$lib/stores/monitoring';
import MonCheckLine from './section/MonCheckLine.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  closeCheckEditor();
});

const check = {
  id: 'chk-1',
  serverId: 'srv-1',
  name: 'CPU',
  checkType: 'agent_resources',
  enabled: true,
  config: {},
  state: { status: 'ok' },
} as unknown as MonitorCheck;

const label = createRawSnippet(() => ({ render: () => '<span>CPU</span>' }));

describe('check editor store wiring (T18)', () => {
  it('the edit button opens the editor with the check as target', async () => {
    const { getByLabelText } = render(MonCheckLine, { props: { check, label } });
    await tick();
    await fireEvent.click(getByLabelText('Bearbeiten'));
    const st = get(checkEditor);
    expect(st.open).toBe(true);
    expect(st.target?.id).toBe('chk-1');
    expect(st.serverId).toBe('srv-1');
    // stopPropagation: the edit click must not expand the row underneath.
    expect(get(monitoring).expandedCheckId).toBeNull();
  });

  it('openCheckEditor(null, serverId) preps a create, close resets', () => {
    openCheckEditor(null, 'srv-9');
    expect(get(checkEditor)).toEqual({ open: true, target: null, serverId: 'srv-9' });
    closeCheckEditor();
    expect(get(checkEditor)).toEqual({ open: false, target: null, serverId: '' });
  });
});
