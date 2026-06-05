// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { toasts, showToast, dismissToast } from './notifications';

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
});
