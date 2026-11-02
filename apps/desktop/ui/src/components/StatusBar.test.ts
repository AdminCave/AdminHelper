// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// StatusBar: the store's messages as a stack of toasts, each closable on its own (R-1062).

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import StatusBar from './StatusBar.svelte';
import { showStatus, reportError, clearStatus, toasts } from '$lib/stores/statusBar';

describe('StatusBar', () => {
  beforeEach(() => {
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
});
