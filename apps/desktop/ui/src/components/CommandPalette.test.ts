// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// CommandPalette: search, arrow keys, Enter, Escape and the empty state (R-1062).

import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { setLanguage, tNow } from '$lib/i18n';
import type { PaletteEntry } from '$lib/palette';
import CommandPalette from './CommandPalette.svelte';

function entries(): PaletteEntry[] {
  return ['Alpha', 'Beta', 'Gamma'].map((label) => ({
    id: label,
    kind: 'page',
    label,
    run: vi.fn(),
  }));
}

function input(): HTMLInputElement {
  return document.querySelector<HTMLInputElement>('.palette-input')!;
}

function labels(): string[] {
  return [...document.querySelectorAll('.palette-item .palette-label')].map(
    (el) => el.textContent ?? '',
  );
}

function selectedLabel(): string | undefined {
  return document.querySelector('.palette-item[aria-selected="true"] .palette-label')
    ?.textContent as string | undefined;
}

beforeAll(() => setLanguage('de'));
afterEach(() => cleanup());

describe('CommandPalette', () => {
  it('renders nothing while closed', () => {
    render(CommandPalette, { props: { open: false, entries: entries(), onClose: vi.fn() } });
    expect(document.querySelector('.palette')).toBeNull();
  });

  it('focuses the search field and filters while typing', async () => {
    render(CommandPalette, { props: { open: true, entries: entries(), onClose: vi.fn() } });
    await tick();
    expect(document.activeElement).toBe(input());
    expect(labels()).toEqual(['Alpha', 'Beta', 'Gamma']);
    await fireEvent.input(input(), { target: { value: 'ga' } });
    expect(labels()).toEqual(['Gamma']);
  });

  it('moves the selection with the arrow keys, wrapping, and runs it with Enter', async () => {
    const list = entries();
    const onClose = vi.fn();
    render(CommandPalette, { props: { open: true, entries: list, onClose } });
    await tick();
    expect(selectedLabel()).toBe('Alpha');
    await fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(selectedLabel()).toBe('Beta');
    await fireEvent.keyDown(input(), { key: 'ArrowUp' });
    await fireEvent.keyDown(input(), { key: 'ArrowUp' });
    expect(selectedLabel()).toBe('Gamma');
    expect(input().getAttribute('aria-activedescendant')).toBe(
      document.querySelector('.palette-item[aria-selected="true"]')?.id,
    );
    await fireEvent.keyDown(input(), { key: 'Enter' });
    expect(onClose).toHaveBeenCalledOnce();
    expect(list[2].run).toHaveBeenCalledOnce();
    expect(list[0].run).not.toHaveBeenCalled();
  });

  it('runs an entry on click', async () => {
    const list = entries();
    const onClose = vi.fn();
    render(CommandPalette, { props: { open: true, entries: list, onClose } });
    await tick();
    await fireEvent.click(document.querySelectorAll('.palette-item')[1]);
    expect(list[1].run).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes on Escape and says when nothing matches', async () => {
    const onClose = vi.fn();
    render(CommandPalette, { props: { open: true, entries: entries(), onClose } });
    await tick();
    await fireEvent.input(input(), { target: { value: 'zzz' } });
    expect(document.querySelector('.palette-empty')?.textContent).toBe(tNow('palette.empty'));
    await fireEvent.keyDown(input(), { key: 'Enter' });
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('starts empty again on the next opening', async () => {
    const view = render(CommandPalette, {
      props: { open: true, entries: entries(), onClose: vi.fn() },
    });
    await tick();
    await fireEvent.input(input(), { target: { value: 'be' } });
    await view.rerender({ open: false, entries: entries(), onClose: vi.fn() });
    await view.rerender({ open: true, entries: entries(), onClose: vi.fn() });
    await tick();
    expect(input().value).toBe('');
    expect(labels()).toEqual(['Alpha', 'Beta', 'Gamma']);
  });
});

describe('CommandPalette with shrinking entries', () => {
  it('keeps the selection on a real row when the entries shrink while open', async () => {
    const list = entries();
    const onClose = vi.fn();
    const view = render(CommandPalette, { props: { open: true, entries: list, onClose } });
    await tick();
    await fireEvent.keyDown(input(), { key: 'ArrowDown' });
    await fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(selectedLabel()).toBe('Gamma');

    await view.rerender({ open: true, entries: [list[0]], onClose });
    await tick();
    expect(selectedLabel()).toBe('Alpha');
    expect(input().getAttribute('aria-activedescendant')).toBe(
      document.querySelector('.palette-item')?.id,
    );
    await fireEvent.keyDown(input(), { key: 'Enter' });
    expect(list[0].run).toHaveBeenCalledOnce();
  });
});
