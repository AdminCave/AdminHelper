// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// kern-design-1 T3: the core components of the DS library (Button, IconButton,
// Badge, Tag, Kbd, Spinner, Pill, Dot, Panel) — variants as classes, events,
// locking and the accessible names.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { setLanguage } from '$lib/i18n';
import Button from './Button.svelte';
import IconButton from './IconButton.svelte';
import Badge from './Badge.svelte';
import Tag from './Tag.svelte';
import Kbd from './Kbd.svelte';
import Spinner from './Spinner.svelte';
import Pill from './Pill.svelte';
import Dot, { statusColor } from './Dot.svelte';
import Panel from './Panel.svelte';
import TestIcon from './__fixtures__/TestIcon.svelte';

setLanguage('de');
afterEach(() => cleanup());

const text = (s: string) => createRawSnippet(() => ({ render: () => `<span>${s}</span>` }));

// jsdom delivers a synthetic click even to a disabled button (browsers do not deliver
// user clicks there), so the lock is asserted on the disabled property.
describe('Button', () => {
  it('renders primary md by default as type=button and fires onclick', async () => {
    const onclick = vi.fn();
    const { getByRole } = render(Button, { onclick, children: text('Speichern') });
    const btn = getByRole('button', { name: 'Speichern' });
    expect(btn.className).toContain('btn-primary');
    expect(btn.className).toContain('btn-md');
    expect(btn.getAttribute('type')).toBe('button');
    await fireEvent.click(btn);
    expect(onclick).toHaveBeenCalledTimes(1);
  });

  it.each(['secondary', 'ghost', 'accent', 'danger'] as const)(
    'variant %s sets its class',
    (variant) => {
      const { getByRole } = render(Button, { variant, size: 'lg', children: text('x') });
      expect(getByRole('button').className).toContain(`btn-${variant}`);
      expect(getByRole('button').className).toContain('btn-lg');
    },
  );

  it('loading disables the button, shows a spinner and marks it busy', async () => {
    const { getByRole, queryByTestId } = render(Button, {
      loading: true,
      iconLeft: TestIcon,
      children: text('Senden'),
    });
    const btn = getByRole('button', { name: /Senden/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(btn.getAttribute('aria-busy')).toBe('true');
    expect(getByRole('status')).toBeTruthy();
    expect(queryByTestId('icon')).toBeNull();
  });

  it('disabled locks the button; fullWidth, type and icons pass through', async () => {
    const { getByRole, getAllByTestId } = render(Button, {
      disabled: true,
      fullWidth: true,
      type: 'submit',
      size: 'sm',
      iconLeft: TestIcon,
      iconRight: TestIcon,
      children: text('Los'),
    });
    const btn = getByRole('button');
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(btn.className).toContain('full');
    expect(btn.getAttribute('type')).toBe('submit');
    expect(getAllByTestId('icon').map((i) => i.dataset.size)).toEqual(['14', '14']);
  });

  it('merges a class array or object from the page instead of stringifying it', () => {
    const { getByRole } = render(Button, {
      class: ['extra', { picked: true, dropped: false }],
      children: text('Los'),
    });
    const cls = getByRole('button').className;
    expect(cls).toContain('btn-primary');
    expect(cls).toContain('extra');
    expect(cls).toContain('picked');
    expect(cls).not.toContain('dropped');
    expect(cls).not.toContain('[object');
  });
});

describe('IconButton', () => {
  it('takes its accessible name and tooltip from label', async () => {
    const onclick = vi.fn();
    const { getByRole, getByTestId } = render(IconButton, {
      icon: TestIcon,
      label: 'Schließen',
      onclick,
    });
    const btn = getByRole('button', { name: 'Schließen' });
    expect(btn.getAttribute('title')).toBe('Schließen');
    expect(btn.className).toContain('icon-btn-ghost');
    expect(btn.className).toContain('icon-btn-md');
    expect(getByTestId('icon').dataset.size).toBe('17');
    await fireEvent.click(btn);
    expect(onclick).toHaveBeenCalledTimes(1);
  });

  it.each(['secondary', 'solid'] as const)('variant %s sets its class', (variant) => {
    const { getByRole } = render(IconButton, { icon: TestIcon, label: 'x', variant, size: 'sm' });
    expect(getByRole('button').className).toContain(`icon-btn-${variant}`);
    expect(getByRole('button').className).toContain('icon-btn-sm');
  });
});

describe('Badge', () => {
  it.each(['neutral', 'success', 'warning', 'danger', 'info'] as const)('tone %s', (tone) => {
    const { container } = render(Badge, { tone, children: text('Aktiv') });
    expect(container.querySelector('.badge')!.className).toContain(`badge-${tone}`);
  });

  it('dot adds a decorative marker', () => {
    const { container } = render(Badge, { dot: true, children: text('Online') });
    expect(container.querySelector('.dot')!.getAttribute('aria-hidden')).toBe('true');
  });
});

describe('Tag', () => {
  it('defaults to accent md and is not interactive without handlers', () => {
    const { container, queryByRole } = render(Tag, { children: text('prod') });
    const tag = container.querySelector('.tag')!;
    expect(tag.className).toContain('tag-accent');
    expect(tag.className).toContain('tag-md');
    expect(queryByRole('button')).toBeNull();
  });

  it('remove fires onRemove without also clicking the tag or its container', async () => {
    const onRemove = vi.fn();
    const onClick = vi.fn();
    const outer = vi.fn();
    const { getByRole } = render(Tag, {
      onRemove,
      onClick,
      removeLabel: 'prod entfernen',
      children: text('prod'),
    });
    // Svelte handles clicks at the mount root, so the stop shows above it.
    document.body.addEventListener('click', outer);
    try {
      await fireEvent.click(getByRole('button', { name: 'prod entfernen' }));
      await fireEvent.click(getByRole('button', { name: 'prod' }));
    } finally {
      document.body.removeEventListener('click', outer);
    }
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(outer).toHaveBeenCalledTimes(1);
  });

  it('click and remove are sibling buttons, neither nested in the other', () => {
    const { getByRole } = render(Tag, {
      onClick: () => {},
      onRemove: () => {},
      removeLabel: 'weg',
      children: text('prod'),
    });
    const main = getByRole('button', { name: 'prod' });
    const remove = getByRole('button', { name: 'weg' });
    expect(main.contains(remove)).toBe(false);
    expect(remove.parentElement!.closest('button, [role="button"]')).toBeNull();
    expect(main.parentElement!.closest('button, [role="button"]')).toBeNull();
  });

  it('remove button falls back to the translated label', () => {
    const { getByRole } = render(Tag, { onRemove: () => {}, children: text('prod') });
    expect(getByRole('button', { name: 'Löschen' })).toBeTruthy();
  });

  it('a clickable tag is a native button and is mono by default', async () => {
    const onClick = vi.fn();
    const { container, getByRole } = render(Tag, {
      onClick,
      tone: 'outline',
      children: text('x'),
    });
    const btn = getByRole('button', { name: 'x' });
    // A native button gives Enter and Space without a key handler of our own.
    expect(btn.tagName).toBe('BUTTON');
    expect((btn as HTMLButtonElement).type).toBe('button');
    expect(container.querySelector('.tag')!.className).toContain('mono');
    await fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('mono can be switched off', () => {
    const { container } = render(Tag, { mono: false, children: text('x') });
    expect(container.querySelector('.tag')!.className).not.toContain('mono');
  });
});

describe('Kbd, Spinner, Pill', () => {
  it('Kbd renders a kbd element', () => {
    const { container } = render(Kbd, { children: text('Ctrl') });
    expect(container.querySelector('kbd')!.textContent).toBe('Ctrl');
  });

  it('Spinner is a status with the loading label and the given size', () => {
    const { getByRole } = render(Spinner, { size: 24, stroke: 3 });
    const s = getByRole('status', { name: 'Lade…' });
    expect(s.style.width).toBe('24px');
    expect(s.style.borderWidth).toBe('3px');
  });

  it.each(['ok', 'warn', 'crit', 'accent', 'muted'] as const)('Pill tone %s', (tone) => {
    const { container } = render(Pill, { tone, title: 'Zustand', children: text('3') });
    const pill = container.querySelector('.pill')!;
    expect(pill.className).toContain(`pill-${tone}`);
    expect(pill.getAttribute('title')).toBe('Zustand');
  });
});

describe('Dot', () => {
  it('maps status names to DS colors, unknown to subtle', () => {
    expect(statusColor('ok')).toBe('var(--success)');
    expect(statusColor('connecting')).toBe('var(--warning)');
    expect(statusColor('failed')).toBe('var(--danger)');
    expect(statusColor('pending')).toBe('var(--text-subtle)');
  });

  it('is decorative without label and an image with label', () => {
    const plain = render(Dot, { st: 'ok' }).container.querySelector('.dot') as HTMLElement;
    expect(plain.getAttribute('aria-hidden')).toBe('true');
    expect(plain.style.width).toBe('8px');
    cleanup();
    const { getByRole } = render(Dot, { st: 'crit', size: 10, ring: true, label: 'Kritisch' });
    const dot = getByRole('img', { name: 'Kritisch' });
    expect(dot.style.width).toBe('10px');
    expect(dot.getAttribute('style')).toContain('box-shadow');
  });
});

describe('Panel', () => {
  it('renders title, icon, action and body with padding', () => {
    const { getByRole, getByTestId, getByText, container } = render(Panel, {
      title: 'Dienste',
      icon: TestIcon,
      pad: 12,
      action: text('Mehr'),
      children: text('Inhalt'),
    });
    expect(getByRole('heading', { name: 'Dienste' })).toBeTruthy();
    expect(getByTestId('icon')).toBeTruthy();
    expect(getByText('Mehr')).toBeTruthy();
    expect((container.querySelector('.body') as HTMLElement).style.padding).toBe('12px');
  });

  it('omits the header without title and action', () => {
    const { container } = render(Panel, { children: text('Inhalt') });
    expect(container.querySelector('header')).toBeNull();
    expect(container.querySelector('section')!.textContent).toContain('Inhalt');
  });
});
