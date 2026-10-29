// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Idle sign-out of the web panel: no pointer, keyboard, wheel or touch event in any tab of the
// origin for `minutes` minutes. The tabs share the time of the last activity in localStorage.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { watchIdle } from './idle';

const KEY = 'adminhelper_last_activity';
const MINUTE = 60_000;
const CHECK = 15_000;
const START = new Date('2026-10-23T08:00:00Z').getTime();

let stops: Array<() => void>;

function watch(minutes: number | null | undefined, options?: { restored?: boolean }) {
  const onIdle = vi.fn();
  const stop = watchIdle(minutes, onIdle, options);
  stops.push(stop);
  return { onIdle, stop };
}

function act(type: string) {
  window.dispatchEvent(new Event(type));
}

function blocked(): never {
  throw new DOMException('denied', 'SecurityError');
}

describe('watchIdle', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START);
    localStorage.clear();
    stops = [];
  });

  afterEach(() => {
    for (const stop of stops) stop();
    Reflect.deleteProperty(document, 'visibilityState');
    vi.restoreAllMocks();
    vi.useRealTimers();
    localStorage.clear();
  });

  it('(a) without activity: not before `minutes`, then exactly once', () => {
    const { onIdle } = watch(30);
    // The start counts as activity and is shared with the other tabs.
    expect(localStorage.getItem(KEY)).toBe(String(START));

    vi.advanceTimersByTime(30 * MINUTE - 1);
    expect(onIdle).not.toHaveBeenCalled();
    vi.advanceTimersByTime(CHECK);
    expect(onIdle).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(60 * MINUTE);
    expect(onIdle).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('(a) a limit far beyond the range of a timer delay neither fires early nor never', () => {
    // 10^9 minutes are 6e13 ms; a timer delay above 2^31-1 ms runs at once (the fake timers
    // reproduce that), so only a check that compares timestamps gets this right.
    const minutes = 1e9;
    const { onIdle } = watch(minutes);
    vi.advanceTimersByTime(60 * MINUTE);
    expect(onIdle).not.toHaveBeenCalled();

    // The clock jumps ahead, as after a long sleep; the next check lands 1 ms before the limit.
    vi.setSystemTime(START + minutes * MINUTE - CHECK - 1);
    vi.advanceTimersByTime(CHECK);
    expect(onIdle).not.toHaveBeenCalled();
    vi.advanceTimersByTime(CHECK);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('(b) a keydown after 29 minutes moves the sign-out', () => {
    const { onIdle } = watch(30);
    vi.advanceTimersByTime(29 * MINUTE);
    act('keydown');

    vi.advanceTimersByTime(30 * MINUTE - 1);
    expect(onIdle).not.toHaveBeenCalled();
    vi.advanceTimersByTime(CHECK);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('(c) activity in another tab of the origin moves it as well', () => {
    const { onIdle } = watch(30);
    vi.advanceTimersByTime(29 * MINUTE);
    localStorage.setItem(KEY, String(Date.now()));

    vi.advanceTimersByTime(30 * MINUTE - 1);
    expect(onIdle).not.toHaveBeenCalled();
    vi.advanceTimersByTime(CHECK);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('(d) after stopping: no sign-out, not even on becoming visible, and a later keydown writes nothing', () => {
    const { onIdle, stop } = watch(30);
    stop();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    vi.advanceTimersByTime(10_000);
    act('keydown');
    vi.advanceTimersByTime(60 * MINUTE);
    // Past the limit, a visibilitychange listener left behind would check and sign out at once.
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'visible',
    });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(onIdle).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([0, undefined, NaN, -1, null, Infinity])(
    '(e) %s turns the watch off: no listener, no timer, never a sign-out',
    (minutes) => {
      const onWindow = vi.spyOn(window, 'addEventListener');
      const onDocument = vi.spyOn(document, 'addEventListener');
      const { onIdle, stop } = watch(minutes);

      expect(onWindow).not.toHaveBeenCalled();
      expect(onDocument).not.toHaveBeenCalled();
      expect(vi.getTimerCount()).toBe(0);
      expect(localStorage.getItem(KEY)).toBeNull();
      vi.advanceTimersByTime(24 * 60 * MINUTE);
      expect(onIdle).not.toHaveBeenCalled();
      expect(() => stop()).not.toThrow();

      // The spies do see a watch that is on, so their silence above is not their blindness.
      watch(30);
      const types = onWindow.mock.calls.map(([type]) => type).sort();
      expect(types).toEqual(['keydown', 'pointerdown', 'pointermove', 'touchstart', 'wheel']);
      for (const [, , options] of onWindow.mock.calls) {
        expect(options).toEqual({ capture: true, passive: true });
      }
      expect(onDocument.mock.calls.map(([type]) => type)).toEqual(['visibilitychange']);
    },
  );

  it('(f) with storage blocked: no error, and the sign-out comes `minutes` after the last activity of this tab', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked);
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked);
    // jsdom reports an exception in an event listener here, not to dispatchEvent's caller.
    const errors: unknown[] = [];
    const onError = (e: ErrorEvent) => errors.push(e.error);
    window.addEventListener('error', onError);

    try {
      const { onIdle } = watch(30);
      vi.advanceTimersByTime(10 * MINUTE);
      act('keydown');

      vi.advanceTimersByTime(30 * MINUTE - 1);
      expect(onIdle).not.toHaveBeenCalled();
      vi.advanceTimersByTime(CHECK);
      expect(onIdle).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('error', onError);
    }
    expect(errors).toEqual([]);
    // The storage was really asked and refused, so the run above went through the blocked path.
    expect(getItem).toHaveBeenCalled();
    expect(setItem).toHaveBeenCalled();
  });

  it('(g) 100 pointermoves within 5 s write the shared time once', () => {
    watch(30);
    vi.advanceTimersByTime(5_000);
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const first = Date.now();

    for (let i = 0; i < 100; i++) {
      act('pointermove');
      vi.advanceTimersByTime(49);
    }

    expect(setItem).toHaveBeenCalledTimes(1);
    expect(setItem).toHaveBeenCalledWith(KEY, String(first));
  });

  it('checks when the tab becomes visible again, not while it is hidden', () => {
    let visibility: DocumentVisibilityState = 'visible';
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => visibility,
    });
    const { onIdle } = watch(30);
    // A background tab: the clock ran on, its timers were held back.
    vi.setSystemTime(START + 31 * MINUTE);

    visibility = 'hidden';
    document.dispatchEvent(new Event('visibilitychange'));
    expect(onIdle).not.toHaveBeenCalled();

    visibility = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  // A session brought back from the refresh cookie on page load: the time of the last activity in
  // this browser counts across reloads and a closed tab. After a login it does not.
  describe('restored', () => {
    it.each([31, 30])(
      '(a) last activity %s minutes back with a limit of 30: onIdle at once, and nothing keeps running',
      (ago) => {
        localStorage.setItem(KEY, String(START - ago * MINUTE));
        // jsdom queues the storage event of that write as a timer of its own.
        const timers = vi.getTimerCount();
        const onWindow = vi.spyOn(window, 'addEventListener');
        const { onIdle } = watch(30, { restored: true });

        expect(onIdle).toHaveBeenCalledTimes(1);
        expect(onWindow).not.toHaveBeenCalled();
        expect(vi.getTimerCount()).toBe(timers);
        vi.advanceTimersByTime(60 * MINUTE);
        expect(onIdle).toHaveBeenCalledTimes(1);
      },
    );

    it.each([
      ['5 minutes', 5 * MINUTE],
      ['1 ms less than 30 minutes', 30 * MINUTE - 1],
    ])(
      '(b) last activity %s back: no sign-out yet, then after another 30 minutes without input',
      (_label, ago) => {
        localStorage.setItem(KEY, String(START - ago));
        const { onIdle } = watch(30, { restored: true });

        expect(onIdle).not.toHaveBeenCalled();
        // Loading the page is input too: the shared time starts over.
        expect(localStorage.getItem(KEY)).toBe(String(START));
        vi.advanceTimersByTime(30 * MINUTE - 1);
        expect(onIdle).not.toHaveBeenCalled();
        vi.advanceTimersByTime(CHECK);
        expect(onIdle).toHaveBeenCalledTimes(1);
      },
    );

    it.each([undefined, { restored: false }])(
      '(c) not restored (%o, a login just now): last activity 2 hours back does not sign out',
      (options) => {
        localStorage.setItem(KEY, String(START - 120 * MINUTE));
        const { onIdle } = watch(30, options);

        expect(onIdle).not.toHaveBeenCalled();
        expect(localStorage.getItem(KEY)).toBe(String(START));
        vi.advanceTimersByTime(30 * MINUTE - 1);
        expect(onIdle).not.toHaveBeenCalled();
        vi.advanceTimersByTime(CHECK);
        expect(onIdle).toHaveBeenCalledTimes(1);
      },
    );

    it('(d) without a stored time: as after a login', () => {
      const { onIdle } = watch(30, { restored: true });

      expect(onIdle).not.toHaveBeenCalled();
      expect(localStorage.getItem(KEY)).toBe(String(START));
      vi.advanceTimersByTime(30 * MINUTE - 1);
      expect(onIdle).not.toHaveBeenCalled();
      vi.advanceTimersByTime(CHECK);
      expect(onIdle).toHaveBeenCalledTimes(1);
    });

    it('(d) with storage blocked: as after a login, and no error', () => {
      // A stale time the blocked storage cannot hand out.
      localStorage.setItem(KEY, String(START - 120 * MINUTE));
      const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked);
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked);

      const { onIdle } = watch(30, { restored: true });
      // The start did ask the storage, so the run below goes through the blocked path.
      expect(getItem).toHaveBeenCalled();
      expect(onIdle).not.toHaveBeenCalled();
      vi.advanceTimersByTime(30 * MINUTE - 1);
      expect(onIdle).not.toHaveBeenCalled();
      vi.advanceTimersByTime(CHECK);
      expect(onIdle).toHaveBeenCalledTimes(1);
    });
  });
});
