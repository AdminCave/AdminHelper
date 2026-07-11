// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { Component } from 'svelte';

export interface RouteDef {
  component: Component;
  // Authorization metadata lives next to the route so the router enforces it, not
  // just the sidebar hiding the nav link. The server is authoritative; this stops
  // a non-admin who types the URL directly from mounting the full admin page (with
  // its "+ create" buttons) and only getting 403 toasts afterwards.
  adminOnly?: boolean;
}

// Resolve the route for a path + principal. Kept here (not in the .svelte-importing
// routes.ts) and taking the table as a parameter so it is a pure function the
// node-only vitest env can unit-test. Falls back to the catch-all route for an
// unknown path OR an admin-only route a non-admin hits.
export function resolveRoute(
  table: Record<string, RouteDef>,
  current: string,
  isAdmin: boolean,
): RouteDef {
  const base = '/' + current.split('/').filter(Boolean)[0];
  const def = table[current] ?? table[base] ?? table['*'];
  if (def.adminOnly && !isAdmin) return table['*'];
  return def;
}
