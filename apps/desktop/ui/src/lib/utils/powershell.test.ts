// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import { psQuote } from './powershell';

describe('psQuote', () => {
  it.each([
    ['', "''"],
    ['https://srm.example:8443', "'https://srm.example:8443'"],
    ['-x', "'-x'"],
    ['$(id)', "'$(id)'"],
    ['$env:PATH', "'$env:PATH'"],
    ['a`b', "'a`b'"],
    ['a,b', "'a,b'"],
    ["a'b", "'a''b'"],
    ["''", "''''''"],
    ['a‘b’c', "'a‘‘b’’c'"],
    ['‚‛', "'‚‚‛‛'"],
  ])('%j → %j', (value, quoted) => {
    expect(psQuote(value)).toBe(quoted);
  });

  it('leaves no quote character undoubled inside the delimiters', () => {
    const inner = psQuote("x'‘’‚‛y'").slice(1, -1);
    // Every run of quote characters has even length: none closes the string.
    for (const run of inner.match(/['‘-‛]+/g) ?? []) {
      expect(run.length % 2).toBe(0);
    }
  });
});
