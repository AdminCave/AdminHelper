// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Do not disturb (R-1078): until a point in time, toasts and OS notifications of this window
// stay quiet; critical ones come through while the person lets them pass (R-1081), which also
// holds for their quiet hours. Feed, badge and center page are not affected.
// Kept in localStorage per workspace: the workspace processes share one webview store, so the
// key carries the workspace id.

import { get, writable } from 'svelte/store';
import { context } from './workspace';
import { criticalPasses, inQuiet } from './notifyPrefs';
import type { NotificationSeverity } from '$lib/api/types';

export type DndDuration = '1h' | '4h' | 'tomorrow';

const KEY_PREFIX = 'ah.dnd.';
const MORNING_HOUR = 7;

const _until = writable<number | null>(null);
/** Epoch ms until which do not disturb holds; null when it is off. */
export const dndUntil = { subscribe: _until.subscribe };

let expiry: ReturnType<typeof setTimeout> | null = null;

function storageKey(): string {
  return KEY_PREFIX + (get(context)?.workspace?.id ?? 'default');
}

function clearExpiry(): void {
  if (expiry) clearTimeout(expiry);
  expiry = null;
}

// One timer at a time, replaced on every change, so a run of starts leaves nothing behind.
function apply(until: number | null, now: number): void {
  clearExpiry();
  if (until !== null && until <= now) until = null;
  _until.set(until);
  try {
    if (until === null) localStorage.removeItem(storageKey());
    else localStorage.setItem(storageKey(), String(until));
  } catch {
    /* storage unavailable: do not disturb holds for this run only */
  }
  if (until !== null) expiry = setTimeout(() => apply(null, Date.now()), until - now);
}

/** When `duration` started at `now` ends: in 1 or 4 hours, or at 07:00 local on the next day. */
export function dndEnd(duration: DndDuration, now: Date): number {
  if (duration === '1h') return now.getTime() + 3_600_000;
  if (duration === '4h') return now.getTime() + 4 * 3_600_000;
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, MORNING_HOUR).getTime();
}

export function startDnd(duration: DndDuration, now: Date = new Date()): void {
  apply(dndEnd(duration, now), now.getTime());
}

export function endDnd(): void {
  apply(null, Date.now());
}

/** Reads the stored point for this workspace; one that has passed counts as off. */
export function loadDnd(now: number = Date.now()): void {
  let stored: number | null = null;
  try {
    const raw = localStorage.getItem(storageKey());
    const value = raw === null ? NaN : Number(raw);
    if (Number.isFinite(value)) stored = value;
  } catch {
    /* storage unavailable: off */
  }
  apply(stored, now);
}

/** Whether a notice of `severity` may show now: outside do not disturb and the quiet hours,
 * and critical inside them too while it may pass. */
export function allows(severity: NotificationSeverity, now: number = Date.now()): boolean {
  if (severity === 'critical' && criticalPasses()) return true;
  const until = get(_until);
  return (until === null || now >= until) && !inQuiet(now);
}

// The workspace id arrives with the context after start; read its stored point then.
context.subscribe((c) => {
  if (c) loadDnd();
});
