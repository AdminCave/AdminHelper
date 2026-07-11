// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { Connection } from '$lib/bridge/types';
import { requestPassword, resolvePrompt } from './passwordPrompt';

const connA = { id: 'a', name: 'A', kind: 'ssh', host: 'h' } as unknown as Connection;
const connB = { id: 'b', name: 'B', kind: 'ssh', host: 'h' } as unknown as Connection;

describe('passwordPrompt (6.43)', () => {
  it('resolves with the submitted outcome', async () => {
    const p = requestPassword(connA, false, true);
    resolvePrompt({ cancelled: false, password: 'pw' });
    await expect(p).resolves.toMatchObject({ cancelled: false, password: 'pw' });
  });

  it('a second request cancels the first instead of hanging it', async () => {
    // 6.43: a second requestPassword while a prompt is still open would overwrite the continuation
    // and hang the first awaited promise forever — a permanently blocked connect flow. It must
    // cancel the first (resolving it with cancelled: true) so its awaiter unblocks, and the second
    // prompt then resolves normally.
    const first = requestPassword(connA, false, true);
    const second = requestPassword(connB, false, true);
    await expect(first).resolves.toEqual({ cancelled: true });
    resolvePrompt({ cancelled: false, password: 'pw' });
    await expect(second).resolves.toMatchObject({ password: 'pw' });
  });
});
