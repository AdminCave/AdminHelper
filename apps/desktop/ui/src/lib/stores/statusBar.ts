// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Status bar store: global info/error messages as a stack of toasts (R-1062).
// Each message clears itself, 6s on success and 10s on error; at most MAX_TOASTS stand,
// a new one pushes the oldest out. `status` is the newest message, for callers and tests
// that only ask what was said last.

import { derived, writable } from 'svelte/store';
import { withoutErrorCodes } from '$lib/utils/errors';

export interface StatusMessage {
  text: string;
  isError: boolean;
  id: number;
}

export const MAX_TOASTS = 3;

let counter = 0;
const timers = new Map<number, ReturnType<typeof setTimeout>>();

const _toasts = writable<StatusMessage[]>([]);
export const toasts = { subscribe: _toasts.subscribe };
export const status = derived(_toasts, (list) => list[list.length - 1] ?? null);

function cancelTimer(id: number): void {
  const timer = timers.get(id);
  if (timer) clearTimeout(timer);
  timers.delete(id);
}

function push(text: string, isError: boolean, ms: number): void {
  counter += 1;
  const id = counter;
  _toasts.update((list) => {
    const next = [...list, { text, isError, id }];
    for (const dropped of next.splice(0, Math.max(0, next.length - MAX_TOASTS))) {
      cancelTimer(dropped.id);
    }
    return next;
  });
  timers.set(
    id,
    setTimeout(() => dismissStatus(id), ms),
  );
}

export function showStatus(text: string): void {
  push(text, false, 6000);
}

// Every error the UI shows here goes through this one function; a backend network error
// carries the ERR_* codes in its message, and the user reads the prose (R-0248).
export function reportError(text: string): void {
  push(withoutErrorCodes(text), true, 10000);
}

export function dismissStatus(id: number): void {
  cancelTimer(id);
  _toasts.update((list) => list.filter((m) => m.id !== id));
}

export function clearStatus(): void {
  for (const id of [...timers.keys()]) cancelTimer(id);
  _toasts.set([]);
}
