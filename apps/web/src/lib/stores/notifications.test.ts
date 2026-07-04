// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { tNow } from '$lib/i18n';
import { toasts, showToast, showError, dismissToast } from './notifications';

describe('notifications store', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Reset shared store state between tests.
    for (const t of get(toasts)) dismissToast(t.id);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts empty', () => {
    expect(get(toasts)).toEqual([]);
  });

  it('adds a toast with default kind "success"', () => {
    showToast('hello');
    const list = get(toasts);
    expect(list).toHaveLength(1);
    expect(list[0].message).toBe('hello');
    expect(list[0].kind).toBe('success');
  });

  it('uses the given kind', () => {
    showToast('boom', 'error');
    expect(get(toasts)[0].kind).toBe('error');
  });

  it('assigns increasing unique ids', () => {
    showToast('a');
    showToast('b');
    const [a, b] = get(toasts);
    expect(b.id).toBeGreaterThan(a.id);
  });

  it('auto-dismisses after the given duration', () => {
    showToast('temp', 'info', 1000);
    expect(get(toasts)).toHaveLength(1);
    vi.advanceTimersByTime(1000);
    expect(get(toasts)).toHaveLength(0);
  });

  it('does not auto-dismiss when duration is 0', () => {
    showToast('sticky', 'info', 0);
    vi.advanceTimersByTime(100000);
    expect(get(toasts)).toHaveLength(1);
  });

  it('dismissToast removes only the matching id', () => {
    showToast('a', 'info', 0);
    showToast('b', 'info', 0);
    const [a] = get(toasts);
    dismissToast(a.id);
    const list = get(toasts);
    expect(list).toHaveLength(1);
    expect(list[0].message).toBe('b');
  });

  it("showError shows an Error's message as an error toast (2.55)", () => {
    showError(new Error('boom'));
    expect(get(toasts).at(-1)).toMatchObject({ message: 'boom', kind: 'error' });
  });

  it('showError falls back to the generic i18n string for a non-Error', () => {
    showError('a plain string, not an Error');
    const last = get(toasts).at(-1);
    expect(last?.kind).toBe('error');
    expect(last?.message).toBe(tNow('error.generic'));
  });
});
