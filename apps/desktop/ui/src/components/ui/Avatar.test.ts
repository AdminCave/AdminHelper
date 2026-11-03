// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Avatar: initials from a display or login name, the size as a class, the name as its title.

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import Avatar, { initials } from './Avatar.svelte';

afterEach(() => cleanup());

describe('initials', () => {
  it('takes the first letter of the first and the last word', () => {
    expect(initials('Kevin Stenzel')).toBe('KS');
    expect(initials('Anna Maria Berg')).toBe('AB');
  });

  it('takes two letters of a single name and splits login names at . _ - @', () => {
    expect(initials('kevin')).toBe('KE');
    expect(initials('k')).toBe('K');
    expect(initials('anna.berg')).toBe('AB');
    expect(initials('ops_admin')).toBe('OA');
    expect(initials('root@host')).toBe('RH');
  });

  it('keeps a letter outside the BMP whole and falls back to ? for an empty name', () => {
    expect(initials('𝒜lpha 𝒵eta')).toBe('𝒜𝒵');
    expect(initials('   ')).toBe('?');
  });
});

describe('Avatar', () => {
  it('renders the initials with the size class and the name as title', () => {
    const { container } = render(Avatar, { props: { name: 'Kevin Stenzel', size: 'sm' } });
    const el = container.querySelector('.ui-avatar') as HTMLElement;
    expect(el.textContent).toBe('KS');
    expect(el.classList.contains('ui-avatar-sm')).toBe(true);
    expect(el.getAttribute('title')).toBe('Kevin Stenzel');
  });
});
