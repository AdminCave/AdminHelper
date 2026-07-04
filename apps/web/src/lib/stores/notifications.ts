// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';

import { tNow } from '$lib/i18n';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

const _toasts = writable<Toast[]>([]);
let nextId = 1;

export const toasts = { subscribe: _toasts.subscribe };

export function showToast(message: string, kind: ToastKind = 'success', durationMs = 3000): void {
  const id = nextId++;
  _toasts.update((list) => [...list, { id, kind, message }]);
  if (durationMs > 0) {
    setTimeout(() => {
      _toasts.update((list) => list.filter((t) => t.id !== id));
    }, durationMs);
  }
}

// Standard error toast: an Error's message, else the generic i18n string. tNow
// (not the $t store) because a toast is a one-shot snapshot, and this runs from
// plain .ts callers too (2.55).
export function showError(err: unknown): void {
  showToast(err instanceof Error ? err.message : tNow('error.generic'), 'error');
}

export function dismissToast(id: number): void {
  _toasts.update((list) => list.filter((t) => t.id !== id));
}
