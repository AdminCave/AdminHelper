// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable, derived, get } from 'svelte/store';

function readHash(): string {
  const h = location.hash || '';
  return h.startsWith('#') ? h.slice(1) : h;
}

const _path = writable<string>(readHash() || '/connections');

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => _path.set(readHash() || '/connections'));
}

export const path = { subscribe: _path.subscribe };

export function navigate(to: string): void {
  const target = to.startsWith('/') ? to : `/${to}`;
  if (location.hash !== `#${target}`) {
    location.hash = target;
  } else {
    _path.set(target);
  }
}

export function replace(to: string): void {
  const target = to.startsWith('/') ? to : `/${to}`;
  history.replaceState(null, '', `#${target}`);
  _path.set(target);
}

export function currentPath(): string {
  return get(_path);
}

export const segments = derived(_path, ($p) => $p.split('/').filter(Boolean));
