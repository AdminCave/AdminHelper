// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import { parseTags, extractAllTags } from './tags';

describe('parseTags', () => {
  it('splits on commas and trims whitespace', () => {
    expect(parseTags('a, b ,  c')).toEqual(['a', 'b', 'c']);
  });

  it('drops empty entries', () => {
    expect(parseTags('a,, ,b')).toEqual(['a', 'b']);
  });

  it('deduplicates while preserving first occurrence', () => {
    expect(parseTags('a,b,a,c,b')).toEqual(['a', 'b', 'c']);
  });

  it('truncates each tag to 50 chars (after trim, before dedup)', () => {
    const long = 'x'.repeat(60);
    expect(parseTags(long)).toEqual(['x'.repeat(50)]);
  });

  it('returns empty array for empty input', () => {
    expect(parseTags('')).toEqual([]);
  });
});

describe('extractAllTags', () => {
  it('unions tags across items, deduped and sorted', () => {
    const items = [{ tags: ['b', 'a'] }, { tags: ['a', 'c'] }];
    expect(extractAllTags(items)).toEqual(['a', 'b', 'c']);
  });

  it('treats missing tags as empty', () => {
    const items = [{ tags: ['z'] }, {}, { tags: undefined }];
    expect(extractAllTags(items)).toEqual(['z']);
  });

  it('returns empty array for no items', () => {
    expect(extractAllTags([])).toEqual([]);
  });
});
