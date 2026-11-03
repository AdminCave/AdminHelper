// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Navigation and overlays of the DS library: Tabs and Segmented move with the arrow
// keys, Menu opens, walks, closes and hands focus back, Tooltip describes its
// trigger, Toast picks its live role and dismisses.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { setLanguage } from '$lib/i18n';
import Segmented from './Segmented.svelte';
import Tabs from './Tabs.svelte';
import Toast from './Toast.svelte';
import NavHarness from './__fixtures__/NavHarness.svelte';
import TestIcon from './__fixtures__/TestIcon.svelte';
import { nextIndex } from './roving';

setLanguage('de');
afterEach(() => cleanup());

const text = (s: string) => createRawSnippet(() => ({ render: () => `<span>${s}</span>` }));

describe('nextIndex', () => {
  it('wraps the arrows, jumps with Home and End, ignores other keys', () => {
    expect(nextIndex('ArrowRight', 2, 3)).toBe(0);
    expect(nextIndex('ArrowLeft', 0, 3)).toBe(2);
    expect(nextIndex('ArrowDown', 0, 3)).toBe(1);
    expect(nextIndex('ArrowUp', 1, 3)).toBe(0);
    expect(nextIndex('Home', 2, 3)).toBe(0);
    expect(nextIndex('End', 0, 3)).toBe(2);
    expect(nextIndex('a', 0, 3)).toBeUndefined();
    expect(nextIndex('ArrowRight', 0, 0)).toBeUndefined();
  });
});

describe('Tabs', () => {
  it('selects the first tab by default and keeps only it in the tab order', () => {
    const { getByRole, getAllByRole } = render(Tabs, {
      tabs: ['Alle', { id: 'off', label: 'Offline', count: 3 }],
      label: 'Filter',
    });
    expect(getByRole('tablist', { name: 'Filter' })).toBeTruthy();
    const [a, b] = getAllByRole('tab');
    expect(a.getAttribute('aria-selected')).toBe('true');
    expect(b.getAttribute('aria-selected')).toBe('false');
    expect([a.tabIndex, b.tabIndex]).toEqual([0, -1]);
    expect(b.textContent).toContain('3');
  });

  it('an unknown value falls back to the first tab, so the bar stays reachable', () => {
    const { getAllByRole } = render(Tabs, { tabs: ['a', 'b'], value: 'gone' });
    expect(getAllByRole('tab').map((t) => t.tabIndex)).toEqual([0, -1]);
  });

  it('arrow keys move focus and selection, wrapping; click selects', async () => {
    const onChange = vi.fn();
    const { getAllByRole } = render(Tabs, { tabs: ['a', 'b', 'c'], value: 'a', onChange });
    const tabs = getAllByRole('tab');
    await fireEvent.keyDown(tabs[0], { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(tabs[2]);
    expect(tabs[2].getAttribute('aria-selected')).toBe('true');
    await fireEvent.keyDown(tabs[2], { key: 'Home' });
    expect(document.activeElement).toBe(tabs[0]);
    await fireEvent.click(tabs[1]);
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(['c', 'a', 'b']);
  });
});

describe('Segmented', () => {
  it('is a radiogroup with roving focus; icon-only options are named by title', async () => {
    const onChange = vi.fn();
    const { getByRole, getAllByRole } = render(Segmented, {
      options: [
        { value: 'list', label: 'Liste' },
        { value: 'grid', icon: TestIcon, title: 'Raster' },
      ],
      value: 'list',
      label: 'Ansicht',
      onChange,
    });
    expect(getByRole('radiogroup', { name: 'Ansicht' })).toBeTruthy();
    const grid = getByRole('radio', { name: 'Raster' });
    const [list] = getAllByRole('radio');
    expect(list.getAttribute('aria-checked')).toBe('true');
    expect([list.tabIndex, grid.tabIndex]).toEqual([0, -1]);
    await fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(grid);
    expect(grid.getAttribute('aria-checked')).toBe('true');
    expect(grid.tabIndex).toBe(0);
    expect(onChange).toHaveBeenCalledWith('grid');
  });
});

describe('Menu', () => {
  function setup() {
    const del = vi.fn();
    const ren = vi.fn();
    const utils = render(NavHarness, {
      items: [
        { label: 'Umbenennen', onClick: ren, shortcut: 'F2' },
        { separator: true },
        { label: 'Löschen', onClick: del, danger: true },
      ],
    });
    const trigger = utils.getByRole('button', { name: 'Mehr' });
    return { ...utils, trigger, del, ren };
  }

  it('opens on click with focus on the first item and announces itself', async () => {
    const { trigger, getByRole, getAllByRole } = setup();
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(trigger);
    await tick();
    const menu = getByRole('menu');
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(trigger.getAttribute('aria-controls')).toBe(menu.id);
    expect(document.activeElement).toBe(getAllByRole('menuitem')[0]);
    expect(menu.className).toContain('end');
  });

  it('arrow keys skip the separator and wrap; Escape closes and refocuses the trigger', async () => {
    const { trigger, getAllByRole, queryByRole } = setup();
    await fireEvent.click(trigger);
    await tick();
    const [ren, del] = getAllByRole('menuitem');
    await fireEvent.keyDown(ren, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(del);
    await fireEvent.keyDown(del, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(ren);
    await fireEvent.keyDown(ren, { key: 'Escape' });
    expect(queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('ArrowUp on the trigger opens on the last item', async () => {
    const { trigger, getAllByRole } = setup();
    await fireEvent.keyDown(trigger, { key: 'ArrowUp' });
    await tick();
    const items = getAllByRole('menuitem');
    expect(document.activeElement).toBe(items[items.length - 1]);
  });

  it('choosing an item runs it, closes and refocuses the trigger', async () => {
    const { trigger, getByRole, queryByRole, del, ren } = setup();
    await fireEvent.click(trigger);
    await tick();
    await fireEvent.click(getByRole('menuitem', { name: 'Löschen' }));
    expect(del).toHaveBeenCalledTimes(1);
    expect(ren).not.toHaveBeenCalled();
    expect(queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('a press outside or Tab closes without stealing focus', async () => {
    const { trigger, getByRole, queryByRole, getAllByRole } = setup();
    await fireEvent.click(trigger);
    await tick();
    await fireEvent.mouseDown(getByRole('button', { name: 'Draußen' }));
    expect(queryByRole('menu')).toBeNull();

    await fireEvent.click(trigger);
    await tick();
    await fireEvent.mouseDown(getAllByRole('menuitem')[0]);
    expect(queryByRole('menu')).not.toBeNull();
    await fireEvent.keyDown(getAllByRole('menuitem')[0], { key: 'Tab' });
    expect(queryByRole('menu')).toBeNull();
  });

  it('clicking the open trigger closes it', async () => {
    const { trigger, queryByRole } = setup();
    await fireEvent.click(trigger);
    await tick();
    await fireEvent.click(trigger);
    expect(queryByRole('menu')).toBeNull();
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
  });
});

describe('Tooltip', () => {
  it('describes its trigger and shows on focus and hover; Escape hides it', async () => {
    const { getByRole } = render(NavHarness, { items: [] });
    const btn = getByRole('button', { name: 'Trennen' });
    const tip = document.getElementById(btn.getAttribute('aria-describedby')!)!;
    expect(tip.getAttribute('role')).toBe('tooltip');
    expect(tip.textContent).toBe('Verbindung trennen');
    expect(tip.hidden).toBe(true);

    await fireEvent.focusIn(btn);
    expect(tip.hidden).toBe(false);
    await fireEvent.keyDown(document, { key: 'Escape' });
    expect(tip.hidden).toBe(true);
    await fireEvent.focusOut(btn);

    await fireEvent.mouseEnter(btn.parentElement!);
    expect(tip.hidden).toBe(false);
    await fireEvent.mouseLeave(btn.parentElement!);
    expect(tip.hidden).toBe(true);
  });
});

describe('Toast', () => {
  it('is a status with title, description and action, without dismiss by default', () => {
    const { getByRole, getByText, queryByRole } = render(Toast, {
      title: 'Gespeichert',
      description: 'Drei Server',
      tone: 'success',
      action: text('Rückgängig'),
    });
    const toast = getByRole('status');
    expect(toast.className).toContain('toast-success');
    expect(getByText('Drei Server')).toBeTruthy();
    expect(getByText('Rückgängig')).toBeTruthy();
    expect(queryByRole('button')).toBeNull();
  });

  it('a danger toast is an alert and dismisses with the translated label', async () => {
    const onDismiss = vi.fn();
    const { getByRole } = render(Toast, { title: 'Fehler', tone: 'danger', onDismiss });
    expect(getByRole('alert')).toBeTruthy();
    await fireEvent.click(getByRole('button', { name: 'Schließen' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
