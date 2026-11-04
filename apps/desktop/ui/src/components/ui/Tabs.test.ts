// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tabs carry their id as data-tab, the stable hook the GUI E2E specs select a tab by
// (R-1064); the keyboard and selection behaviour is covered in nav.test.ts.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import Tabs from './Tabs.svelte';

afterEach(() => cleanup());

describe('Tabs data-tab', () => {
  it('sets the id of each tab, also for plain string tabs', () => {
    const { getAllByRole } = render(Tabs, {
      tabs: [{ id: 'overview', label: 'Übersicht' }, 'raw'],
    });
    expect(getAllByRole('tab').map((b) => b.getAttribute('data-tab'))).toEqual(['overview', 'raw']);
  });

  it('selects the tab found by its data-tab', async () => {
    const onChange = vi.fn();
    const { container } = render(Tabs, {
      tabs: [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
      ],
      value: 'a',
      onChange,
    });
    const b = container.querySelector('[data-tab="b"]') as HTMLButtonElement;
    await fireEvent.click(b);
    expect(onChange).toHaveBeenCalledWith('b');
    expect(b.getAttribute('aria-selected')).toBe('true');
  });
});
