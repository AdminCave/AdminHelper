// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Status bar store: global info/error messages.
// Auto-clear after timeoutMs, currently 6s on success and 10s on error.

import { writable } from 'svelte/store';

export interface StatusMessage {
  text: string;
  isError: boolean;
  id: number;
}

let counter = 0;
let clearTimer: ReturnType<typeof setTimeout> | null = null;

const _state = writable<StatusMessage | null>(null);
export const status = { subscribe: _state.subscribe };

function scheduleClear(id: number, ms: number): void {
  if (clearTimer) clearTimeout(clearTimer);
  clearTimer = setTimeout(() => {
    _state.update((s) => (s && s.id === id ? null : s));
    clearTimer = null;
  }, ms);
}

export function showStatus(text: string): void {
  counter += 1;
  _state.set({ text, isError: false, id: counter });
  scheduleClear(counter, 6000);
}

export function reportError(text: string): void {
  counter += 1;
  _state.set({ text, isError: true, id: counter });
  scheduleClear(counter, 10000);
}

export function clearStatus(): void {
  if (clearTimer) {
    clearTimeout(clearTimer);
    clearTimer = null;
  }
  _state.set(null);
}
