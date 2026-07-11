// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import { formatDate, formatDateTime } from './datetime';

describe('datetime formatting (2.54)', () => {
  it('returns – for null / undefined / empty', () => {
    expect(formatDateTime(null)).toBe('–');
    expect(formatDateTime(undefined)).toBe('–');
    expect(formatDate('')).toBe('–');
  });

  it('returns – for an invalid date, not the string "Invalid Date"', () => {
    // new Date('bad').toLocaleString() returns 'Invalid Date' WITHOUT throwing, so
    // the copies' try/catch never fired; the NaN guard must render '–' instead.
    expect(formatDateTime('not-a-date')).toBe('–');
    expect(formatDate('garbage')).toBe('–');
  });

  it('formats a valid ISO timestamp (contains the year)', () => {
    expect(formatDateTime('2026-03-07T12:00:00Z')).toContain('2026');
    expect(formatDate('2026-03-07T12:00:00Z')).toContain('2026');
  });
});
