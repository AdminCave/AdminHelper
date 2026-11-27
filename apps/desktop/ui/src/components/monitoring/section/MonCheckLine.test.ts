// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-0439: the action buttons ran their action on keydown Enter AND on the click
// the browser makes of Enter on a <button>, so Enter fired twice and the toggle
// undid itself. jsdom makes no click of a keydown, so the pin is: a keydown
// Enter on a button runs nothing itself (the native click does) and does not
// reach the row; a click runs the action once; Enter on the row expands it.

import { describe, it, expect, afterEach, vi } from 'vitest';

vi.mock('uplot', () => ({ default: class {} }));
const h = vi.hoisted(() => ({ toggle: vi.fn(), run: vi.fn(), edit: vi.fn(), expand: vi.fn() }));
vi.mock('$lib/stores/monitoring', async (importOriginal) => ({
  ...(await importOriginal<typeof import('$lib/stores/monitoring')>()),
  toggleCheck: h.toggle,
  runCheck: h.run,
  openCheckEditor: h.edit,
  toggleExpanded: h.expand,
}));
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import type { MonitorCheck } from '$lib/api/types';
import MonCheckLine from './MonCheckLine.svelte';

const check = {
  id: 'chk-1',
  serverId: 'srv-1',
  name: 'Disk',
  checkType: 'ping',
  interval: '5m',
  severity: 'critical',
  enabled: true,
  state: null,
} as MonitorCheck;

const label = createRawSnippet(() => ({ render: () => '<span>Disk</span>' }));

function setup(): { row: HTMLElement; buttons: HTMLButtonElement[] } {
  const { container } = render(MonCheckLine, { check, label });
  return {
    row: container.querySelector<HTMLElement>('.mon-line')!,
    buttons: Array.from(container.querySelectorAll<HTMLButtonElement>('.mon-line-action')),
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('MonCheckLine keyboard', () => {
  it('leaves Enter on an action button to the native click and keeps the row closed', async () => {
    const { buttons } = setup();
    expect(buttons).toHaveLength(3);
    for (const b of buttons) await fireEvent.keyDown(b, { key: 'Enter' });
    expect(h.edit).not.toHaveBeenCalled();
    expect(h.run).not.toHaveBeenCalled();
    expect(h.toggle).not.toHaveBeenCalled();
    expect(h.expand).not.toHaveBeenCalled();
  });

  it('runs each action once on a click without expanding the row', async () => {
    const { buttons } = setup();
    for (const b of buttons) await fireEvent.click(b);
    expect(h.edit).toHaveBeenCalledTimes(1);
    expect(h.run).toHaveBeenCalledTimes(1);
    expect(h.toggle).toHaveBeenCalledTimes(1);
    expect(h.expand).not.toHaveBeenCalled();
  });

  it('expands the row on Enter on the row itself', async () => {
    const { row } = setup();
    await fireEvent.keyDown(row, { key: 'Enter' });
    expect(h.expand).toHaveBeenCalledTimes(1);
    expect(h.expand).toHaveBeenCalledWith('chk-1');
  });
});
