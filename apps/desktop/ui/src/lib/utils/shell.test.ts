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
  'user@host+a=b:c,d./e_f-g',
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
  ['%self', "'%self'"],
  ['a%2Bb', "'a%2Bb'"],
  ['~root', "'~root'"],
  ['*', "'*'"],
  [String.raw`a\b`, String.raw`'a'\\'b'`],
  [String.raw`a\'b`, String.raw`'a'\\''\''b'`],
  [String.raw`x\\`, String.raw`'x'\\''\\''`],
];

// How fish reads a word (https://fishshell.com/docs/current/language.html#quotes): inside single
// quotes only `\\` and `\'` are escapes and any other `\` stays; outside quotes `\\` and `\'` stand
// for the character. fish is not installed here, so this is a model of those rules, not the binary.
// It throws on anything else outside quotes (fish reads `\n` there as a newline, `$` as expansion),
// so a word only passes if it uses nothing the model leaves out.
function fishReads(word: string): string {
  let out = '';
  let i = 0;
  while (i < word.length) {
    const c = word[i];
    if (c === "'") {
      i++;
      while (word[i] !== "'") {
        if (i >= word.length) throw new Error(`unterminated quote in ${word}`);
        const escaped = word[i] === '\\' && (word[i + 1] === '\\' || word[i + 1] === "'");
        out += escaped ? word[i + 1] : word[i];
        i += escaped ? 2 : 1;
      }
      i++;
    } else if (c === '\\' && (word[i + 1] === '\\' || word[i + 1] === "'")) {
      out += word[i + 1];
      i += 2;
    } else if (/^[A-Za-z0-9@+=:,./_-]$/.test(c)) {
      out += c;
      i++;
    } else {
      throw new Error(`${JSON.stringify(c)} outside quotes is not modelled: ${word}`);
    }
  }
  return out;
}

const ALL = [...BARE, ...QUOTED.map(([v]) => v)];

describe('shellQuote', () => {
  it.each(BARE)('leaves %s as it is', (v) => {
    expect(shellQuote(v)).toBe(v);
  });

  it.each(QUOTED)('quotes %j as %s', (v, want) => {
    expect(shellQuote(v)).toBe(want);
  });

  // The proof that matters: a POSIX shell reads the quoted word back as exactly the value.
  it.each(ALL)('/bin/sh reads %j back unchanged', (v) => {
    const out = execFileSync('/bin/sh', ['-c', 'printf %s ' + shellQuote(v)], { encoding: 'utf8' });
    expect(out).toBe(v);
  });

  it.each(ALL)('fish (model) reads %j back unchanged', (v) => {
    expect(fishReads(shellQuote(v))).toBe(v);
  });
});
