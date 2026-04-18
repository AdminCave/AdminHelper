// Status-Bar-Store: globale Info/Fehler-Nachrichten.
// Ersetzt die showStatus/reportError-Callbacks aus desktop/src/.
// Auto-clear nach timeoutMs, aktuell 6s bei Erfolg und 10s bei Fehler.

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
