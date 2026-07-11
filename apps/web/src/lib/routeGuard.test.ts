// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Route authorization guard (1.34): the router must enforce adminOnly, not just
// the sidebar hiding the nav link — a non-admin typing #/users directly must not
// mount the admin page.

import { describe, it, expect } from 'vitest';
import type { Component } from 'svelte';
import { resolveRoute, type RouteDef } from './routeGuard';

const c = {} as Component; // component value is irrelevant to the guard
const table: Record<string, RouteDef> = {
  '/users': { component: c, adminOnly: true },
  '/frp': { component: c, adminOnly: true },
  '/public': { component: c }, // not admin-only
  '*': { component: c },
};

describe('resolveRoute', () => {
  it('mounts an admin route for an admin', () => {
    expect(resolveRoute(table, '/users', true)).toBe(table['/users']);
  });

  it('sends a non-admin on an admin route to the catch-all', () => {
    expect(resolveRoute(table, '/users', false)).toBe(table['*']);
  });

  it('lets anyone reach a non-admin route', () => {
    expect(resolveRoute(table, '/public', false)).toBe(table['/public']);
  });

  it('resolves a nested path by its base segment and still guards it', () => {
    expect(resolveRoute(table, '/frp/detail', true)).toBe(table['/frp']);
    expect(resolveRoute(table, '/frp/detail', false)).toBe(table['*']);
  });

  it('falls an unknown path to the catch-all for either role', () => {
    expect(resolveRoute(table, '/nope', true)).toBe(table['*']);
    expect(resolveRoute(table, '/nope', false)).toBe(table['*']);
  });
});
