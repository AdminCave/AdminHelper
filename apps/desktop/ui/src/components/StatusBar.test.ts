// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// StatusBar: the store's messages as a stack of toasts, each closable on its own (R-1062).

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import StatusBar from './StatusBar.svelte';
import { showStatus, showNotice, reportError, clearStatus, toasts } from '$lib/stores/statusBar';
import { setLanguage } from '$lib/i18n';

describe('StatusBar', () => {
  beforeEach(() => {
    setLanguage('de');
    vi.useFakeTimers();
    clearStatus();
  });

  afterEach(() => {
    cleanup();
    clearStatus();
    vi.useRealTimers();
  });

  it('renders nothing without a message', () => {
    const { container } = render(StatusBar);
    expect(container.querySelector('.toast-stack')).toBeNull();
  });

  it('shows two messages at once, an error as alert and a success as status', async () => {
    const { container } = render(StatusBar);
    showStatus('saved');
    reportError('boom');
    await tick();
    const items = Array.from(container.querySelectorAll('.toast-stack .toast'));
    expect(items.map((el) => el.querySelector('.title')?.textContent)).toEqual(['saved', 'boom']);
    expect(items.map((el) => el.getAttribute('role'))).toEqual(['status', 'alert']);
  });

  it('closes only the dismissed toast', async () => {
    const { container } = render(StatusBar);
    showStatus('a');
    showStatus('b');
    await tick();
    const buttons = container.querySelectorAll<HTMLButtonElement>('.toast .dismiss');
    await fireEvent.click(buttons[0]);
    expect(get(toasts).map((m) => m.text)).toEqual(['b']);
    expect(container.querySelectorAll('.toast')).toHaveLength(1);
  });

  it('removes the stack once the last toast expires', async () => {
    const { container } = render(StatusBar);
    showStatus('a');
    await tick();
    vi.advanceTimersByTime(6000);
    await tick();
    expect(container.querySelector('.toast-stack')).toBeNull();
  });

  // R-1078: a feed entry with its tone, its text and an action that opens it.
  it('shows a notice with tone and text, and Open opens it and closes the toast', async () => {
    const onOpen = vi.fn();
    const { container } = render(StatusBar);
    showNotice({ title: 'Disk full', body: 'web-01', tone: 'warning', onOpen });
    await tick();
    const toast = container.querySelector('.toast') as HTMLElement;
    expect(toast.classList.contains('toast-warning')).toBe(true);
    expect(toast.querySelector('.desc')?.textContent).toBe('web-01');
    const open = toast.querySelector<HTMLButtonElement>('.toast-open');
    expect(open?.textContent).toBe('Öffnen');
    await fireEvent.click(open as HTMLButtonElement);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(get(toasts)).toEqual([]);
  });

  it('a plain status has no open action', async () => {
    const { container } = render(StatusBar);
    showStatus('saved');
    await tick();
    expect(container.querySelector('.toast-open')).toBeNull();
  });

  it('says how many more a full stack pushed out', async () => {
    const { container } = render(StatusBar);
    for (const title of ['a', 'b', 'c', 'd', 'e']) showNotice({ title, tone: 'info' });
    await tick();
    expect(container.querySelector('.toast-overflow')?.textContent).toBe('+2 weitere');
    expect(container.querySelectorAll('.toast')).toHaveLength(3);
  });
});
