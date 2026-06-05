// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { status, showStatus, reportError, clearStatus } from './statusBar';

describe('statusBar store', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    clearStatus();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('showStatus sets a non-error message', () => {
    showStatus('saved');
    const s = get(status);
    expect(s?.text).toBe('saved');
    expect(s?.isError).toBe(false);
  });

  it('reportError sets an error message', () => {
    reportError('boom');
    const s = get(status);
    expect(s?.text).toBe('boom');
    expect(s?.isError).toBe(true);
  });

  it('assigns a fresh, increasing id per message', () => {
    showStatus('a');
    const first = get(status)?.id;
    showStatus('b');
    const second = get(status)?.id;
    expect(first).toBeDefined();
    expect(second).toBeGreaterThan(first as number);
  });

  it('auto-clears a success message after 6s', () => {
    showStatus('saved');
    vi.advanceTimersByTime(5999);
    expect(get(status)).not.toBeNull();
    vi.advanceTimersByTime(1);
    expect(get(status)).toBeNull();
  });

  it('auto-clears an error message after 10s (not 6s)', () => {
    reportError('boom');
    vi.advanceTimersByTime(6000);
    expect(get(status)).not.toBeNull();
    vi.advanceTimersByTime(4000);
    expect(get(status)).toBeNull();
  });

  it('clearStatus removes the message and cancels the pending timer', () => {
    showStatus('saved');
    clearStatus();
    expect(get(status)).toBeNull();
    // Make sure the former timer no longer does anything.
    vi.advanceTimersByTime(10_000);
    expect(get(status)).toBeNull();
  });

  it('a newer message survives the timer of the one it replaced', () => {
    showStatus('first');
    vi.advanceTimersByTime(3000);
    showStatus('second');
    // The first timer would fire at 6000ms -> 3000ms after the second set.
    vi.advanceTimersByTime(3000);
    expect(get(status)?.text).toBe('second');
    // The timer of the second message fires only another 3000ms later.
    vi.advanceTimersByTime(3000);
    expect(get(status)).toBeNull();
  });
});
