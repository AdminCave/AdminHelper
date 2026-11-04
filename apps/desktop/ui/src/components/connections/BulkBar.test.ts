// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The bulk bar of the connections page (R-1065): count, tag field and the bulk actions.

import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import BulkBar from './BulkBar.svelte';

function renderBar(busy = false) {
  const props = {
    count: 3,
    busy,
    onAddTag: vi.fn(),
    onRemoveTag: vi.fn(),
    onExport: vi.fn(),
    onDelete: vi.fn(),
    onClear: vi.fn(),
  };
  render(BulkBar, { props });
  return props;
}

const button = (key: string) => screen.getByRole('button', { name: tNow(key) });
const field = () => screen.getByRole('textbox', { name: tNow('connections.bulk.tag') });

beforeAll(() => {
  setLanguage('en');
});

afterEach(() => {
  cleanup();
});

describe('BulkBar', () => {
  it('counts the selection', () => {
    renderBar();
    expect(screen.getByText(tNow('connections.bulk.selected', { count: 3 }))).not.toBeNull();
  });

  it('adds and removes a trimmed tag and empties the field', async () => {
    const p = renderBar();
    expect((button('connections.bulk.addTag') as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.input(field(), { target: { value: '  prod ' } });
    await fireEvent.click(button('connections.bulk.addTag'));
    expect(p.onAddTag).toHaveBeenCalledWith('prod');
    expect((field() as HTMLInputElement).value).toBe('');

    await fireEvent.input(field(), { target: { value: 'old' } });
    await fireEvent.click(button('connections.bulk.removeTag'));
    expect(p.onRemoveTag).toHaveBeenCalledWith('old');
  });

  it('adds the tag on Enter', async () => {
    const p = renderBar();
    await fireEvent.input(field(), { target: { value: 'db' } });
    await fireEvent.keyDown(field(), { key: 'Enter' });
    expect(p.onAddTag).toHaveBeenCalledWith('db');
  });

  it('exports, deletes and clears', async () => {
    const p = renderBar();
    await fireEvent.click(button('connections.bulk.export'));
    await fireEvent.click(button('action.delete'));
    await fireEvent.click(button('connections.bulk.clear'));
    expect(p.onExport).toHaveBeenCalledTimes(1);
    expect(p.onDelete).toHaveBeenCalledTimes(1);
    expect(p.onClear).toHaveBeenCalledTimes(1);
  });

  it('locks the actions while one runs', () => {
    renderBar(true);
    for (const key of ['connections.bulk.export', 'action.delete']) {
      expect((button(key) as HTMLButtonElement).disabled).toBe(true);
    }
    expect((field() as HTMLInputElement).disabled).toBe(true);
  });
});
