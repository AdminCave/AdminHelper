// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Data and feedback surfaces of the design system: what they render, which parts
// are optional, and the copy feedback of CodeBlock.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { setLanguage } from '$lib/i18n';
import Callout from './Callout.svelte';
import CodeBlock from './CodeBlock.svelte';
import EmptyState from './EmptyState.svelte';
import MetaList from './MetaList.svelte';
import Skeleton from './Skeleton.svelte';
import TestIcon from './__fixtures__/TestIcon.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const text = (s: string) => createRawSnippet(() => ({ render: () => `<span>${s}</span>` }));
const button = (s: string) =>
  createRawSnippet(() => ({ render: () => `<button type="button">${s}</button>` }));

describe('Callout', () => {
  it('shows tone, icon, title, text and action', () => {
    const { container, getByText, getByRole, getByTestId } = render(Callout, {
      tone: 'warning',
      title: 'Zertifikat läuft ab',
      icon: TestIcon,
      children: text('in 3 Tagen'),
      action: button('Erneuern'),
    });
    expect(container.querySelector('.callout')!.className).toContain('callout-warning');
    expect(getByText('Zertifikat läuft ab')).toBeTruthy();
    expect(getByText('in 3 Tagen')).toBeTruthy();
    expect(getByRole('button', { name: 'Erneuern' })).toBeTruthy();
    expect(getByTestId('icon').closest('[aria-hidden]')).not.toBeNull();
  });

  it('defaults to info and renders no empty parts', () => {
    const { container } = render(Callout, { title: 'Hinweis' });
    expect(container.querySelector('.callout')!.className).toContain('callout-info');
    expect(container.querySelector('.icon, .text, .action')).toBeNull();
    expect(container.querySelector('[role]')).toBeNull();
  });
});

describe('EmptyState', () => {
  it('follows the DS contract: icon, title, description, action, framed by default', () => {
    const { container, getByRole, getByText, getByTestId } = render(EmptyState, {
      icon: TestIcon,
      title: 'Keine Verbindungen',
      description: 'Lege die erste an.',
      action: button('Neu'),
    });
    expect(getByRole('heading', { name: 'Keine Verbindungen' })).toBeTruthy();
    expect(getByText('Lege die erste an.')).toBeTruthy();
    expect(getByRole('button', { name: 'Neu' })).toBeTruthy();
    expect(getByTestId('icon').getAttribute('data-size')).toBe('22');
    expect(container.querySelector('.empty-state')!.classList.contains('framed')).toBe(true);
  });

  it('framed=false drops the frame', () => {
    const { container } = render(EmptyState, { title: 'x', framed: false });
    expect(container.querySelector('.empty-state')!.classList.contains('framed')).toBe(false);
  });
});

describe('Skeleton', () => {
  it('is hidden from assistive tech and shortens the last of several lines', () => {
    const { container } = render(Skeleton, { count: 3, width: '200px', height: 12 });
    const root = container.querySelector('.skeleton')!;
    expect(root.getAttribute('aria-hidden')).toBe('true');
    const lines = [...root.querySelectorAll<HTMLElement>('.line')];
    expect(lines.map((l) => l.style.width)).toEqual(['200px', '200px', '70%']);
    expect(lines[0].style.height).toBe('12px');
  });

  it('circle takes its height as width and a pill radius', () => {
    const { container } = render(Skeleton, { circle: true, height: 32 });
    const line = container.querySelector<HTMLElement>('.line')!;
    expect(line.style.width).toBe('32px');
    expect(line.style.borderRadius).toBe('var(--radius-pill)');
  });
});

describe('CodeBlock', () => {
  it('shows filename and code and copies with feedback that resets', async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const { getByRole, getByText, container } = render(CodeBlock, {
      code: 'adminhelper-agent enroll',
      filename: 'install.sh',
    });
    expect(getByText('install.sh')).toBeTruthy();
    expect(container.querySelector('pre code')!.textContent).toBe('adminhelper-agent enroll');

    await fireEvent.click(getByRole('button', { name: 'Kopieren' }));
    await tick();
    expect(writeText).toHaveBeenCalledWith('adminhelper-agent enroll');
    expect(getByRole('button', { name: 'Kopiert' })).toBeTruthy();
    expect(getByRole('status').textContent).toBe('Kopiert');

    vi.advanceTimersByTime(1700);
    await tick();
    expect(getByRole('button', { name: 'Kopieren' })).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it('a refused clipboard shows no success', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const { getByRole } = render(CodeBlock, { code: 'x' });
    await fireEvent.click(getByRole('button', { name: 'Kopieren' }));
    await tick();
    expect(getByRole('button', { name: 'Kopieren' })).toBeTruthy();
    expect(getByRole('status').textContent).toBe('');
    vi.unstubAllGlobals();
  });

  it('without copy and label there is no header', () => {
    const { container } = render(CodeBlock, { code: 'x', copyable: false });
    expect(container.querySelector('.head')).toBeNull();
  });
});

describe('MetaList', () => {
  it('pairs keys and values in a dl, values in mono unless switched off', () => {
    const { container } = render(MetaList, {
      rows: [
        { key: 'Host', value: '192.0.2.10' },
        { key: 'Name', value: 'web-1', mono: false },
      ],
    });
    const dl = container.querySelector('dl')!;
    expect([...dl.querySelectorAll('dt')].map((d) => d.textContent)).toEqual(['Host', 'Name']);
    const dd = [...dl.querySelectorAll('dd')];
    expect(dd.map((d) => d.textContent)).toEqual(['192.0.2.10', 'web-1']);
    expect(dd.map((d) => d.classList.contains('mono'))).toEqual([true, false]);
  });
});
