// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import {
  status,
  toasts,
  showStatus,
  showNotice,
  overflow,
  reportError,
  clearStatus,
  dismissStatus,
  MAX_TOASTS,
} from './statusBar';

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

  // R-0248: a network error from the backend carries the ERR_* codes in its source
  // chain (error.rs); they are for the code, the status bar shows the prose.
  it('reportError drops a code buried in the message, as a failed tunnel start reports it', () => {
    reportError(
      'Tunnel: error sending request: ' +
        'client error (Connect): ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat ' +
        'für x hat sich seit dem ersten Verbinden geändert',
    );
    expect(get(status)?.text).toBe(
      'Tunnel: error sending request: ' +
        'client error (Connect): AdminHelper TOFU: Das Server-Zertifikat ' +
        'für x hat sich seit dem ersten Verbinden geändert',
    );
  });

  it('reportError drops a code at the start of the message', () => {
    reportError(
      'ERR_CA_PIN_MISMATCH: AdminHelper: Das Server-Zertifikat wird nicht mehr von der ' +
        'bei der Geräte-Registrierung gepinnten CA gedeckt (mögliche MITM-Attacke).',
    );
    const s = get(status);
    expect(s?.text).toBe(
      'AdminHelper: Das Server-Zertifikat wird nicht mehr von der ' +
        'bei der Geräte-Registrierung gepinnten CA gedeckt (mögliche MITM-Attacke).',
    );
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

  // R-1062: messages stack as toasts instead of replacing each other.
  it('keeps several messages at once, oldest first', () => {
    showStatus('a');
    reportError('b');
    expect(get(toasts).map((m) => [m.text, m.isError])).toEqual([
      ['a', false],
      ['b', true],
    ]);
  });

  it('keeps at most MAX_TOASTS and drops the oldest together with its timer', () => {
    for (const text of ['a', 'b', 'c', 'd']) showStatus(text);
    expect(MAX_TOASTS).toBe(3);
    expect(get(toasts).map((m) => m.text)).toEqual(['b', 'c', 'd']);
    vi.advanceTimersByTime(6000);
    expect(get(toasts)).toEqual([]);
  });

  it('expires each message on its own timer', () => {
    reportError('err');
    vi.advanceTimersByTime(1000);
    showStatus('ok');
    vi.advanceTimersByTime(6000);
    expect(get(toasts).map((m) => m.text)).toEqual(['err']);
    vi.advanceTimersByTime(3000);
    expect(get(toasts)).toEqual([]);
  });

  it('dismissStatus removes exactly that message and its timer', () => {
    showStatus('a');
    showStatus('b');
    const [first] = get(toasts);
    dismissStatus(first.id);
    expect(get(toasts).map((m) => m.text)).toEqual(['b']);
    expect(get(status)?.text).toBe('b');
    dismissStatus(first.id);
    expect(get(toasts).map((m) => m.text)).toEqual(['b']);
  });

  // R-1078: feed entries as toasts.
  it('a notice carries tone, text and its open action, and goes after 6 s', () => {
    const onOpen = vi.fn();
    showNotice({ title: 'Disk full', body: 'web-01', tone: 'warning', onOpen });
    const m = get(toasts)[0];
    expect([m.text, m.body, m.tone, m.isError, m.sticky]).toEqual([
      'Disk full',
      'web-01',
      'warning',
      false,
      false,
    ]);
    m.onOpen?.();
    expect(onOpen).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(6000);
    expect(get(toasts)).toEqual([]);
  });

  it('a sticky notice stands until it is closed', () => {
    showNotice({ title: 'Down', tone: 'danger', sticky: true });
    vi.advanceTimersByTime(60 * 60_000);
    const [m] = get(toasts);
    expect(m.text).toBe('Down');
    dismissStatus(m.id);
    expect(get(toasts)).toEqual([]);
  });

  it('a burst of info does not push a sticky notice out, and counts what it dropped', () => {
    showNotice({ title: 'crit', tone: 'danger', sticky: true });
    for (const title of ['a', 'b', 'c', 'd']) showNotice({ title, tone: 'info' });
    expect(get(toasts).map((m) => m.text)).toEqual(['crit', 'c', 'd']);
    expect(get(overflow)).toBe(2);
  });

  // The answer to the user's own action must show even during an incident (R-0248).
  it('with every toast standing the oldest goes, and a new status or error always shows', () => {
    for (const title of ['c1', 'c2', 'c3']) showNotice({ title, tone: 'danger', sticky: true });
    showStatus('saved');
    expect(get(toasts).map((m) => m.text)).toEqual(['c2', 'c3', 'saved']);
    expect(get(overflow)).toBe(1);
    reportError('failed');
    expect(get(toasts).map((m) => m.text)).toEqual(['c2', 'c3', 'failed']);
    expect(get(overflow)).toBe(1);
    vi.advanceTimersByTime(10000);
    expect(get(toasts).map((m) => m.text)).toEqual(['c2', 'c3']);
  });

  it('a notice that would go by itself does not push a standing one out', () => {
    for (const title of ['c1', 'c2', 'c3']) showNotice({ title, tone: 'danger', sticky: true });
    showNotice({ title: 'info', tone: 'info' });
    expect(get(toasts).map((m) => m.text)).toEqual(['c1', 'c2', 'c3']);
    expect(get(overflow)).toBe(1);
    vi.advanceTimersByTime(6000);
    expect(get(toasts).map((m) => m.text)).toEqual(['c1', 'c2', 'c3']);
  });

  it('counts only pushed-out notices, and starts again once the stack is empty', () => {
    for (const text of ['a', 'b', 'c', 'd']) showStatus(text);
    expect(get(toasts).map((m) => m.text)).toEqual(['b', 'c', 'd']);
    expect(get(overflow)).toBe(0);
    for (const title of ['n1', 'n2', 'n3', 'n4']) showNotice({ title, tone: 'info' });
    expect(get(overflow)).toBe(1);
    vi.advanceTimersByTime(6000);
    expect(get(toasts)).toEqual([]);
    expect(get(overflow)).toBe(0);
    showNotice({ title: 'n5', tone: 'info' });
    expect(get(overflow)).toBe(0);
  });
});
