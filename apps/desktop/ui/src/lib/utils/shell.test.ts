// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

import { describe, it, expect } from 'vitest';
import { execFileSync } from 'child_process';
import { shellQuote } from './shell';

// Words a shell takes literally: the forms the server issues (URL, token, UUID, fingerprint)
// and the whole safe character class.
const BARE = [
  'https://srm.example:8443',
  'adminhelper_prov_AbC-_9z',
  '3f2b8c1e-5d4a-4b6f-9e2d-7a1c0b9e8f42',
  'ab'.repeat(32),
  'user@host%2B+a=b:c,d./e_f-g',
];

const QUOTED: [string, string][] = [
  ['', "''"],
  ['a b', "'a b'"],
  ['$(id)', "'$(id)'"],
  ['`id`', "'`id`'"],
  ['a;b', "'a;b'"],
  ['a|b', "'a|b'"],
  ["a'b", "'a'\\''b'"],
  ["''", "''\\'''\\'''"],
  ['a\nb', "'a\nb'"],
  ['~root', "'~root'"],
  ['*', "'*'"],
];

describe('shellQuote', () => {
  it.each(BARE)('leaves %s as it is', (v) => {
    expect(shellQuote(v)).toBe(v);
  });

  it.each(QUOTED)('quotes %j as %s', (v, want) => {
    expect(shellQuote(v)).toBe(want);
  });

  // The proof that matters: a POSIX shell reads the quoted word back as exactly the value.
  it.each([...BARE, ...QUOTED.map(([v]) => v)])('/bin/sh reads %j back unchanged', (v) => {
    const out = execFileSync('/bin/sh', ['-c', 'printf %s ' + shellQuote(v)], { encoding: 'utf8' });
    expect(out).toBe(v);
  });
});
