// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Theme store: defaults to dark, initialises from the data-theme attribute the FOUC
// script has already applied, and toggleTheme flips the attribute AND persists to
// localStorage (so the choice survives a reload). theme.ts reads document + localStorage
// at import time, so each test resets both and re-imports fresh.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

describe('theme store', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('defaults to dark when no attribute or storage is set', async () => {
    const { theme } = await import('./theme');
    expect(get(theme)).toBe('dark');
  });

  it('initialises from the data-theme attribute set by the FOUC script', async () => {
    document.documentElement.dataset.theme = 'light';
    const { theme } = await import('./theme');
    expect(get(theme)).toBe('light');
  });

  it('toggleTheme flips the attribute and persists to localStorage', async () => {
    const { theme, toggleTheme } = await import('./theme');
    expect(get(theme)).toBe('dark');

    toggleTheme();
    expect(get(theme)).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(localStorage.getItem('ah-theme')).toBe('light');

    toggleTheme();
    expect(get(theme)).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('ah-theme')).toBe('dark');
  });
});
