// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';

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

export function dismissToast(id: number): void {
  _toasts.update((list) => list.filter((t) => t.id !== id));
}
