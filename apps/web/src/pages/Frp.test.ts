// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

/**
 * The frps state block on the FRP page (frps-supervisor T13).
 *
 * GET /api/frp/supervisor-status carries codes only; the page turns every code into a text of
 * its own, in German and in English, and anything else into a generic text. CODES lists every
 * code; the first two tests pin it to the reader on the server, which lets no other code
 * through, and to the supervisor, which writes them, so a new code fails here until it has a
 * text.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { get } from 'svelte/store';
import type * as FrpApi from '$lib/api/frp';

vi.mock('$lib/api/frp', async (importOriginal) => ({
  ...(await importOriginal<typeof FrpApi>()),
  listConfigs: vi.fn(),
  supervisorStatus: vi.fn(),
}));

import Frp from './Frp.svelte';
import { listConfigs, supervisorStatus, type FrpSupervisorStatus } from '$lib/api/frp';
import { ApiError } from '$lib/api/types';
import { language, type Language } from '$lib/i18n';
import { translations } from '$lib/i18n/dictionaries';
import { toasts, dismissToast } from '$lib/stores/notifications';

const CODES = {
  // STATES of the reader, plus the two it reports for a missing or broken status file.
  state: ['waiting', 'running', 'degraded', 'stopped', 'crashloop', 'missing', 'unreadable'],
  reason: [
    'none',
    'config_missing',
    'token_invalid',
    'tls_not_forced',
    'cert_paths',
    'cert_missing',
    'cert_expired',
    'cert_key_mismatch',
    'verify_failed',
    'input_unreadable',
    'input_unstable',
    'processes_left',
  ],
  event: ['started', 'applied', 'rejected', 'stopped', 'crashed', 'copy_changed', 'start_refused'],
};
type Kind = keyof typeof CODES;
const KINDS: Kind[] = ['state', 'reason', 'event'];
const TEST_ID: Record<Kind, string> = {
  state: 'frps-state',
  reason: 'frps-reason',
  event: 'frps-event',
};
const LANGUAGES: Language[] = ['de', 'en'];

// src/pages -> the repo root
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const READER = readFileSync(
  join(ROOT, 'apps', 'server', 'app', 'modules', 'frp', 'supervisor_status.py'),
  'utf-8',
);
const SUPERVISOR = readFileSync(join(ROOT, 'apps', 'frps', 'frps-supervisor.sh'), 'utf-8');

/** The members of `<name> = frozenset(...)` in the reader. */
function readerSet(name: string): string[] {
  const body = READER.match(new RegExp(`^${name} = frozenset\\(([\\s\\S]*?)\\)$`, 'm'))?.[1];
  return [...(body ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

/** Every code the supervisor script hands to its state, its events or its checks' results. */
function supervisorCodes(): string[] {
  const forms = [
    /\bREASON=([a-z_]+)/g,
    /\breason=([a-z_]+)/g,
    /\bevent=([a-z_]+)/g,
    /\bset_(?:config|state) ([a-z_]+) ([a-z_]+)/g,
    /\badd_event ([a-z_]+) ([a-z_]+)/g,
    /\bdrop_copy ([a-z_]+)/g,
    /\becho ([a-z_]+)$/gm,
    /\bprint "([a-z_]+)"/g,
  ];
  const codes = new Set<string>();
  for (const form of forms) {
    for (const m of SUPERVISOR.matchAll(form)) for (const code of m.slice(1)) codes.add(code);
  }
  return [...codes].sort();
}

const sorted = (codes: string[]) => [...codes].sort();
const text = (lang: Language, key: string): string | undefined => translations[lang][key];
const codeText = (lang: Language, kind: Kind, code: string) =>
  text(lang, `page.frp.supervisor.${kind}.${code}`);

const RUNNING: FrpSupervisorStatus = {
  state: 'running',
  reason: 'none',
  since: '2026-10-17T08:00:00Z',
  stale: false,
  lastEvent: 'applied',
  lastEventAt: '2026-10-17T07:59:58Z',
  publishedBindPort: 7000,
};

function withCode(kind: Kind, code: string): FrpSupervisorStatus {
  if (kind === 'state') return { ...RUNNING, state: code };
  if (kind === 'reason') return { ...RUNNING, reason: code };
  return { ...RUNNING, lastEvent: code };
}

/** Mounts the page with this answer and waits for the block to show it. */
async function show(status: FrpSupervisorStatus) {
  vi.mocked(supervisorStatus).mockResolvedValue(status);
  const view = render(Frp);
  await view.findByTestId('frps-state');
  return view;
}

const shown = (view: { getByTestId: (id: string) => HTMLElement }, testId: string) =>
  view.getByTestId(testId).textContent?.trim();

let visibility: DocumentVisibilityState;

/** What the tab reports from now on, announced to the page as a tab switch does. */
function setVisibility(state: DocumentVisibilityState) {
  visibility = state;
  document.dispatchEvent(new Event('visibilitychange'));
}

let errors: string[];
const onRejection = (e: PromiseRejectionEvent) => errors.push(`rejection: ${String(e.reason)}`);

beforeEach(() => {
  errors = [];
  visibility = 'visible';
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => visibility,
  });
  vi.mocked(listConfigs).mockReset().mockResolvedValue([]);
  vi.mocked(supervisorStatus).mockReset();
  language.set('de');
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    errors.push(`console.error: ${args.map(String).join(' ')}`);
  });
  window.addEventListener('unhandledrejection', onRejection);
});

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(document, 'visibilityState');
  window.removeEventListener('unhandledrejection', onRejection);
  for (const t of get(toasts)) dismissToast(t.id);
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('the code list', () => {
  it('holds exactly the codes the reader on the server lets through', () => {
    const fallback = [...READER.matchAll(/SupervisorStatus\(state="([a-z_]+)"\)/g)].map(
      (m) => m[1],
    );
    expect(sorted([...new Set([...readerSet('STATES'), ...fallback])])).toEqual(
      sorted(CODES.state),
    );
    expect(sorted(readerSet('REASONS'))).toEqual(sorted(CODES.reason));
    expect(sorted(readerSet('EVENTS'))).toEqual(sorted(CODES.event));
  });

  it('holds every code the supervisor writes', () => {
    const written = supervisorCodes();
    // The late codes, so that an extraction that finds nothing cannot pass.
    expect(written).toEqual(
      expect.arrayContaining([
        'copy_changed',
        'start_refused',
        'processes_left',
        'input_unreadable',
        'input_unstable',
      ]),
    );
    const known = new Set([...CODES.state, ...CODES.reason, ...CODES.event]);
    expect(written.filter((code) => !known.has(code))).toEqual([]);
  });
});

describe.each(LANGUAGES)('texts in %s', (lang) => {
  beforeEach(() => language.set(lang));

  for (const kind of KINDS) {
    it.each(CODES[kind])(`${kind} %s shows a text of its own`, async (code) => {
      const own = codeText(lang, kind, code);
      expect(own, `no ${lang} text for ${kind} ${code}`).toBeTruthy();
      expect(own).not.toBe(codeText(lang, kind, 'unknown'));

      const view = await show(withCode(kind, code));

      expect(shown(view, TEST_ID[kind])).toBe(own);
    });

    it(`no two ${kind} codes share a text`, () => {
      const texts = CODES[kind].map((code) => codeText(lang, kind, code));
      expect(new Set(texts).size).toBe(texts.length);
    });

    it.each(['exploded', 'constructor', '__proto__'])(
      `an unknown ${kind} code %s gets the generic text and is not shown`,
      async (code) => {
        const view = await show(withCode(kind, code));

        expect(shown(view, TEST_ID[kind])).toBe(codeText(lang, kind, 'unknown'));
        expect(view.container.textContent).not.toContain(code);
      },
    );
  }

  it('says the supervisor is not responding when the status is stale', async () => {
    const view = await show({ ...RUNNING, stale: true });

    expect(shown(view, 'frps-stale')).toBe(text(lang, 'page.frp.supervisor.stale'));
    // The state the supervisor last wrote stays visible next to the hint.
    expect(shown(view, 'frps-state')).toBe(codeText(lang, 'state', 'running'));
  });

  it('shows since when and when the last event happened, in local time', async () => {
    const locale = lang === 'de' ? 'de-DE' : 'en-US';
    const view = await show(RUNNING);

    expect(shown(view, 'frps-since')).toBe(new Date(RUNNING.since ?? '').toLocaleString(locale));
    expect(shown(view, 'frps-event-at')).toBe(
      new Date(RUNNING.lastEventAt ?? '').toLocaleString(locale),
    );
  });
});

describe('the state block', () => {
  it('names the late reasons as asked', async () => {
    expect(codeText('de', 'reason', 'input_unreadable')).toContain('nicht lesbar oder zu groß');
    expect(codeText('en', 'reason', 'input_unreadable')).toContain('unreadable or too large');
    const view = await show({ ...RUNNING, state: 'waiting', reason: 'input_unreadable' });

    expect(shown(view, 'frps-reason')).toBe(codeText('de', 'reason', 'input_unreadable'));
  });

  it('says nothing of not responding while the heartbeat is fresh', async () => {
    const view = await show(RUNNING);

    expect(view.queryByTestId('frps-stale')).toBeNull();
  });

  it.each(['missing', 'unreadable'])(
    'shows the %s state without reason, time or event',
    async (state) => {
      const view = await show({
        ...RUNNING,
        state,
        reason: null,
        since: null,
        lastEvent: null,
        lastEventAt: null,
      });

      expect(shown(view, 'frps-state')).toBe(codeText('de', 'state', state));
      expect(view.queryByTestId('frps-reason')).toBeNull();
      expect(view.queryByTestId('frps-since')).toBeNull();
      expect(view.queryByTestId('frps-event')).toBeNull();
    },
  );

  it.each([
    ['a network error', new TypeError('Failed to fetch')],
    ['403', new ApiError(403, 'Admin rights required')],
    ['404 from a server without the route', new ApiError(404, 'Not Found')],
  ])('turns neutral on %s and leaves the page usable', async (_name, err) => {
    vi.mocked(supervisorStatus).mockRejectedValue(err);
    const view = render(Frp);

    const neutral = await view.findByTestId('frps-unavailable');

    expect(neutral.textContent?.trim()).toBe(text('de', 'page.frp.supervisor.unavailable'));
    expect(view.queryByTestId('frps-state')).toBeNull();
    expect(view.container.querySelector('.page-title')).not.toBeNull();
    expect(get(toasts)).toEqual([]);
    await fireEvent.click(view.getByRole('button', { name: text('de', 'page.frp.createConfig') }));
    expect(await view.findByRole('dialog')).toBeTruthy();
    expect(errors).toEqual([]);
  });
});

describe('refreshing the state', () => {
  beforeEach(() => vi.useFakeTimers());

  it('asks on opening and every 30 s, and stops once the page is left', async () => {
    vi.mocked(supervisorStatus).mockResolvedValue(RUNNING);
    const view = render(Frp);
    await vi.advanceTimersByTimeAsync(0);
    expect(supervisorStatus).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(29_999);
    expect(supervisorStatus).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(supervisorStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(supervisorStatus).toHaveBeenCalledTimes(3);

    view.unmount();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(supervisorStatus).toHaveBeenCalledTimes(3);
  });

  it('shows each new answer, and the neutral state once a later request fails', async () => {
    vi.mocked(supervisorStatus)
      .mockResolvedValueOnce(RUNNING)
      .mockResolvedValueOnce({ ...RUNNING, state: 'degraded', reason: 'cert_expired' })
      .mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const view = render(Frp);

    await vi.advanceTimersByTimeAsync(0);
    expect(shown(view, 'frps-state')).toBe(codeText('de', 'state', 'running'));

    await vi.advanceTimersByTimeAsync(30_000);
    expect(shown(view, 'frps-state')).toBe(codeText('de', 'state', 'degraded'));
    expect(shown(view, 'frps-reason')).toBe(codeText('de', 'reason', 'cert_expired'));

    await vi.advanceTimersByTimeAsync(30_000);
    expect(view.queryByTestId('frps-state')).toBeNull();
    expect(view.getByTestId('frps-unavailable')).toBeTruthy();
  });

  it('does not let a late answer overwrite a newer one', async () => {
    const answers: Array<(status: FrpSupervisorStatus) => void> = [];
    vi.mocked(supervisorStatus).mockImplementation(
      () => new Promise<FrpSupervisorStatus>((resolve) => answers.push(resolve)),
    );
    const view = render(Frp);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(answers, 'both requests are open').toHaveLength(2);

    answers[1]({ ...RUNNING, state: 'degraded', reason: 'cert_expired' });
    await vi.advanceTimersByTimeAsync(0);
    expect(shown(view, 'frps-state')).toBe(codeText('de', 'state', 'degraded'));

    answers[0](RUNNING);
    await vi.advanceTimersByTimeAsync(0);
    expect(shown(view, 'frps-state')).toBe(codeText('de', 'state', 'degraded'));
    expect(shown(view, 'frps-reason')).toBe(codeText('de', 'reason', 'cert_expired'));
  });

  it('does not ask while the tab is hidden, and asks at once when it shows again', async () => {
    vi.mocked(supervisorStatus).mockResolvedValue(RUNNING);
    render(Frp);
    await vi.advanceTimersByTimeAsync(0);
    expect(supervisorStatus).toHaveBeenCalledTimes(1);

    setVisibility('hidden');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(supervisorStatus).toHaveBeenCalledTimes(1);

    setVisibility('visible');
    await vi.advanceTimersByTimeAsync(0);
    expect(supervisorStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(supervisorStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(supervisorStatus).toHaveBeenCalledTimes(3);
  });

  it('opened in a hidden tab, asks only once the tab shows', async () => {
    vi.mocked(supervisorStatus).mockResolvedValue(RUNNING);
    visibility = 'hidden';
    const view = render(Frp);
    await vi.advanceTimersByTimeAsync(90_000);
    expect(supervisorStatus).not.toHaveBeenCalled();

    setVisibility('visible');
    await vi.advanceTimersByTimeAsync(0);
    expect(supervisorStatus).toHaveBeenCalledTimes(1);
    expect(shown(view, 'frps-state')).toBe(codeText('de', 'state', 'running'));
  });

  it('leaves no visibility listener behind once the page is left', async () => {
    vi.mocked(supervisorStatus).mockResolvedValue(RUNNING);
    const view = render(Frp);
    await vi.advanceTimersByTimeAsync(0);
    view.unmount();

    setVisibility('hidden');
    setVisibility('visible');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(supervisorStatus).toHaveBeenCalledTimes(1);
  });
});
