// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';

function readHash(): string {
  const h = location.hash || '';
  return h.startsWith('#') ? h.slice(1) : h;
}

const _path = writable<string>(readHash() || '/users');

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => _path.set(readHash() || '/users'));
}

export const path = { subscribe: _path.subscribe };

export function replace(to: string): void {
  const target = to.startsWith('/') ? to : `/${to}`;
  history.replaceState(null, '', `#${target}`);
  _path.set(target);
}
