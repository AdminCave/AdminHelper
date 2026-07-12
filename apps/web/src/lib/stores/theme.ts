// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'ah-theme';

// The FOUC-free inline script in index.html has already applied data-theme before the
// first paint; initialise from the attribute the browser is already showing so the store
// never disagrees with what is on screen. Default = dark (attribute absent).
function initial(): Theme {
  if (typeof document !== 'undefined') {
    const attr = document.documentElement.dataset.theme;
    if (attr === 'light' || attr === 'dark') return attr;
  }
  return 'dark';
}

const _theme = writable<Theme>(initial());

_theme.subscribe((theme) => {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = theme;
  }
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, theme);
  }
});

export const theme = {
  subscribe: _theme.subscribe,
  set: _theme.set,
};

export function toggleTheme(): void {
  _theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
}
