// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Status bar store: global info/error messages as a stack of toasts (R-1062).
// Each message clears itself, 6s on success and 10s on error; at most MAX_TOASTS stand,
// a new one pushes the oldest out. `status` is the newest message, for callers and tests
// that only ask what was said last.
// A notice (R-1078) is a feed entry as a toast: a tone after its severity, a text, an action that
// opens it, and a critical one stands until closed. The notices a full stack pushes out are
// counted (they stay in the bell and the feed), so the stack can say "+N more" until it is empty
// again.

import { derived, get, writable } from 'svelte/store';
import { withoutErrorCodes } from '$lib/utils/errors';

export type ToastTone = 'neutral' | 'info' | 'warning' | 'danger';

export interface StatusMessage {
  text: string;
  isError: boolean;
  id: number;
  tone: ToastTone;
  body?: string;
  sticky?: boolean;
  notice?: boolean;
  onOpen?: () => void;
}

export interface Notice {
  title: string;
  body?: string | null;
  tone: ToastTone;
  sticky?: boolean;
  onOpen?: () => void;
}

export const MAX_TOASTS = 3;

let counter = 0;
const timers = new Map<number, ReturnType<typeof setTimeout>>();

const _toasts = writable<StatusMessage[]>([]);
export const toasts = { subscribe: _toasts.subscribe };
export const status = derived(_toasts, (list) => list[list.length - 1] ?? null);
const _overflow = writable(0);
/** How many notices a full stack pushed out since it was last empty. */
export const overflow = { subscribe: _overflow.subscribe };

function cancelTimer(id: number): void {
  const timer = timers.get(id);
  if (timer) clearTimeout(timer);
  timers.delete(id);
}

// A status or an error always shows: it answers what the user just did. A full stack drops the
// oldest older toast that would go by itself, and only when every one stands the oldest. A notice
// that would go by itself never pushes a standing one out: a full stack of critical notices drops
// it instead (it stays in the bell and the feed).
function push(message: Omit<StatusMessage, 'id'>, ms: number | null): void {
  if (message.notice && !message.sticky) {
    const list = get(_toasts);
    if (list.length >= MAX_TOASTS && list.every((m) => m.sticky)) {
      _overflow.update((n) => n + 1);
      return;
    }
  }
  counter += 1;
  const id = counter;
  _toasts.update((list) => {
    const next = [...list];
    while (next.length >= MAX_TOASTS) {
      const at = next.findIndex((m) => !m.sticky);
      const [dropped] = next.splice(at === -1 ? 0 : at, 1);
      cancelTimer(dropped.id);
      if (dropped.notice) _overflow.update((n) => n + 1);
    }
    return [...next, { ...message, id }];
  });
  if (ms !== null) {
    timers.set(
      id,
      setTimeout(() => dismissStatus(id), ms),
    );
  }
}

export function showStatus(text: string): void {
  push({ text, isError: false, tone: 'neutral' }, 6000);
}

/** A feed entry as a toast; it goes after 6 s like a status, a sticky one only when closed. */
export function showNotice(n: Notice): void {
  push(
    {
      text: n.title,
      body: n.body ?? undefined,
      isError: false,
      tone: n.tone,
      sticky: n.sticky ?? false,
      notice: true,
      onOpen: n.onOpen,
    },
    n.sticky ? null : 6000,
  );
}

// Every error the UI shows here goes through this one function; a backend network error
// carries the ERR_* codes in its message, and the user reads the prose (R-0248).
export function reportError(text: string): void {
  push({ text: withoutErrorCodes(text), isError: true, tone: 'danger' }, 10000);
}

export function dismissStatus(id: number): void {
  cancelTimer(id);
  _toasts.update((list) => list.filter((m) => m.id !== id));
  if (get(_toasts).length === 0) _overflow.set(0);
}

export function clearStatus(): void {
  for (const id of [...timers.keys()]) cancelTimer(id);
  _toasts.set([]);
  _overflow.set(0);
}
