// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { storageGet, storageSet } from './utils/storage';

// All tabs of the origin share one clock: logging out ends the shared refresh cookie, so a tab
// that only counted its own activity would sign out the tab the user is working in.
const LAST_ACTIVITY_KEY = 'adminhelper_last_activity';
const ACTIVITY_EVENTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'] as const;
const WRITE_EVERY_MS = 5_000;
// The limit itself is never a timer delay: browsers run a delay above 2^31-1 ms (about 24.8
// days) at once. A fixed check compares timestamps instead, which also catches up after a
// sleeping machine or the throttled timers of a background tab.
const CHECK_EVERY_MS = 15_000;

/**
 * Calls `onIdle` once when no tab of this origin has seen a pointer, keyboard, wheel or touch
 * event for `minutes` minutes. Anything but a positive finite number turns the watch off.
 * `restored` marks a session brought back on page load, not one from a login: if the last
 * activity stored in this browser lies `minutes` or more back, `onIdle` runs at once.
 * Returns the function that stops it.
 */
export function watchIdle(
  minutes: number | null | undefined,
  onIdle: () => void,
  { restored = false }: { restored?: boolean } = {},
): () => void {
  if (typeof minutes !== 'number' || !Number.isFinite(minutes) || minutes <= 0) return () => {};
  const limitMs = minutes * 60_000;

  // Otherwise closing the tab would get around the limit: the refresh cookie outlives it.
  // A missing time or blocked storage reads as null, which must not count as 0 (1970). A time
  // after the clock (set back since) or one that is no number leaves the age unknown, so it ends
  // the session too.
  if (restored) {
    const stored = storageGet(LAST_ACTIVITY_KEY);
    const age = Date.now() - Number(stored);
    if (stored !== null && !(age >= 0 && age < limitMs)) {
      onIdle();
      return () => {};
    }
  }

  let stopped = false;
  let lastActivity = Date.now();
  let lastWrite = lastActivity;
  storageSet(LAST_ACTIVITY_KEY, String(lastActivity));

  function onActivity() {
    lastActivity = Date.now();
    if (lastActivity - lastWrite < WRITE_EVERY_MS) return;
    lastWrite = lastActivity;
    storageSet(LAST_ACTIVITY_KEY, String(lastActivity));
  }

  function check() {
    // Blocked storage reads as null: then only this tab counts.
    const shared = Number(storageGet(LAST_ACTIVITY_KEY));
    const last = Number.isFinite(shared) ? Math.max(lastActivity, shared) : lastActivity;
    if (Date.now() - last < limitMs) return;
    stop();
    onIdle();
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') check();
  }

  const listenerOptions: AddEventListenerOptions = { capture: true, passive: true };
  for (const type of ACTIVITY_EVENTS) window.addEventListener(type, onActivity, listenerOptions);
  document.addEventListener('visibilitychange', onVisibilityChange);
  const timer = setInterval(check, CHECK_EVERY_MS);

  function stop() {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    for (const type of ACTIVITY_EVENTS) window.removeEventListener(type, onActivity, true);
    document.removeEventListener('visibilitychange', onVisibilityChange);
  }

  return stop;
}
