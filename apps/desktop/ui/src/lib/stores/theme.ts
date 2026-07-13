// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';

export type Theme = 'dark' | 'light';

// Non-sensitive UI state → localStorage, NOT the persisted Settings contract (no Rust /
// migration touch). data-theme on <html> drives the theme (see :root[data-theme=light]).
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
    // Keep the mobile browser chrome in sync with the theme (web only; the desktop
    // index.html has no theme-color meta, so querySelector returns null and this skips).
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'light' ? '#fff' : '#000');
  }
  // setItem can THROW (Safari private mode / quota / blocked storage); an unhandled throw
  // here propagates out of this module's import and blanks the app. Swallow it — the theme
  // still applies via the attribute, only persistence is best-effort. (typeof-guard dropped:
  // try/catch also covers a missing localStorage.)
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* storage unavailable — persistence best-effort */
  }
});

export const theme = {
  subscribe: _theme.subscribe,
  set: _theme.set,
};

export function toggleTheme(): void {
  _theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
}
