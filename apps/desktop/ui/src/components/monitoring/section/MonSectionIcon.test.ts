// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// MonSectionIcon maps the section and action names to Lucide icons: every name the
// sections and check lines use draws a hidden icon of its size, an unknown one nothing.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import MonSectionIcon from './MonSectionIcon.svelte';

afterEach(() => cleanup());

const SECTIONS = [
  'live',
  'network',
  'services',
  'docker',
  'backups',
  'storage',
  'smart',
  'heartbeat',
];
const ACTIONS = ['chevron', 'edit', 'play', 'power', 'reset'];

describe('MonSectionIcon', () => {
  it.each([...SECTIONS.map((n) => [n, '18']), ...ACTIONS.map((n) => [n, '14'])])(
    '%s draws a %s px icon hidden from assistive tech',
    (name, size) => {
      const { container } = render(MonSectionIcon, { name });
      const svg = container.querySelector('svg')!;
      expect(svg).not.toBeNull();
      expect(svg.getAttribute('width')).toBe(size);
      expect(svg.getAttribute('aria-hidden')).toBe('true');
      expect(
        svg.querySelector('path, circle, rect, polyline, line, polygon, ellipse'),
      ).not.toBeNull();
    },
  );

  it('an unknown name draws nothing', () => {
    const { container } = render(MonSectionIcon, { name: 'nope' });
    expect(container.querySelector('svg')).toBeNull();
  });
});
