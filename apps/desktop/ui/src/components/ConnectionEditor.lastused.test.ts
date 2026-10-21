// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

// "Last used" in the connection editor is a value inside .field, whose global rule in app.css
// sets labels in capitals with wide spacing; a value keeps its own case (R-0564, as the URL
// values of R-0431 T54). jsdom loads neither app.css nor a component's <style>, so the test
// puts the real .field rule into the document; the label in capitals proves it applies.

import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { setLanguage, tNow } from '$lib/i18n';

vi.mock('$lib/bridge', () => ({}));
vi.mock('$lib/stores/connections', () => ({ upsert: vi.fn(), remove: vi.fn() }));
vi.mock('$lib/stores/connectFlow', () => ({ initiateConnect: vi.fn() }));

import { emptyConnection } from '$lib/models/connection';
import { openEditor, closeEditor } from '$lib/stores/editor';
import ConnectionEditor from './ConnectionEditor.svelte';

const APP_CSS = join(dirname(fileURLToPath(import.meta.url)), '..', 'styles', 'app.css');
const LAST_USED = '2026-10-20T08:30:00Z';

let sheet: HTMLStyleElement;

beforeAll(() => {
  setLanguage('en');
  const rule = readFileSync(APP_CSS, 'utf-8').match(/^\.field \{[^}]*\}/m);
  expect(rule).not.toBeNull();
  sheet = document.createElement('style');
  sheet.textContent = rule![0];
  document.head.append(sheet);
});

afterAll(() => {
  sheet.remove();
});

afterEach(() => {
  cleanup();
  closeEditor();
});

describe('ConnectionEditor last used', () => {
  it('shows the time it was last used in its own case under a label in capitals', async () => {
    openEditor({ ...emptyConnection('ssh'), name: 'web01', lastUsed: LAST_USED });
    const { container } = render(ConnectionEditor);
    await tick();

    const value = container.querySelector<HTMLElement>('[data-testid="editor-last-used"]')!;
    expect(value.textContent?.trim()).toBe(new Date(LAST_USED).toLocaleString());
    const label = value.previousElementSibling as HTMLElement;
    expect(label.textContent).toBe(tNow('editor.field.lastUsed'));
    expect(getComputedStyle(label).textTransform).toBe('uppercase');

    expect(getComputedStyle(value).textTransform).toBe('none');
    expect(getComputedStyle(value).letterSpacing).toBe('normal');
  });
});
