// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { copyToClipboard } from './clipboard';
import { language } from '$lib/i18n';
import { translations } from '$lib/i18n/dictionaries';
import { toasts, dismissToast } from '$lib/stores/notifications';

const de = translations.de;

function stubClipboard(clipboard: unknown): void {
  vi.stubGlobal('navigator', { ...navigator, clipboard });
}

beforeEach(() => language.set('de'));

afterEach(() => {
  vi.unstubAllGlobals();
  for (const t of get(toasts)) dismissToast(t.id);
});

describe('copyToClipboard', () => {
  it('copies the text and shows the toast of the key given', async () => {
    const writeText = vi.fn(async () => {});
    stubClipboard({ writeText });

    await expect(copyToClipboard('placeholder-value', 'toast.hook.tokenCopied')).resolves.toBe(
      true,
    );

    expect(writeText).toHaveBeenCalledWith('placeholder-value');
    expect(get(toasts).map((t) => [t.kind, t.message])).toEqual([
      ['success', de['toast.hook.tokenCopied']],
    ]);
  });

  it('a refused write shows "copy failed"', async () => {
    stubClipboard({ writeText: vi.fn(async () => Promise.reject(new Error('denied'))) });

    await expect(copyToClipboard('x', 'toast.hook.tokenCopied')).resolves.toBe(false);

    expect(get(toasts).map((t) => [t.kind, t.message])).toEqual([
      ['error', de['toast.copyFailed']],
    ]);
  });

  it('without a clipboard API (insecure context) it shows "copy failed" and does not throw', async () => {
    stubClipboard(undefined);

    await expect(copyToClipboard('x', 'toast.hook.tokenCopied')).resolves.toBe(false);

    expect(get(toasts).map((t) => [t.kind, t.message])).toEqual([
      ['error', de['toast.copyFailed']],
    ]);
  });
});
