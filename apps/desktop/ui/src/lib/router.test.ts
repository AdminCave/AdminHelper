// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { navigate, replace, currentPath, segments } from './router';

// The hash router is a 1:1 copy shared with apps/web; every navigation in the app depends on it, yet it
// had no test (6.116). Covers slash normalization, the same-hash special case, replace, and segments.
describe('router', () => {
  beforeEach(() => {
    location.hash = '';
  });

  it('normalizes a bare path to a leading slash', () => {
    navigate('servers');
    expect(location.hash).toBe('#/servers');
  });

  it('keeps an already-absolute path unchanged', () => {
    navigate('/dashboard');
    expect(location.hash).toBe('#/dashboard');
  });

  it('updates the store directly when navigating to the already-active hash', () => {
    // location.hash === `#${target}` won't fire hashchange, so navigate() must set _path itself,
    // otherwise re-navigating to the current page would be a no-op (router.ts 25-29).
    location.hash = '#/here';
    navigate('/here');
    expect(currentPath()).toBe('/here');
  });

  it('replace sets both the path store and the hash', () => {
    replace('/settings');
    expect(currentPath()).toBe('/settings');
    expect(location.hash).toBe('#/settings');
  });

  it('segments splits the path and drops empty parts', () => {
    replace('/servers/42');
    expect(get(segments)).toEqual(['servers', '42']);
    replace('/');
    expect(get(segments)).toEqual([]);
  });
});
