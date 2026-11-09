// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Scancodes, desktop coordinates of a fitted or zoomed canvas, wheel and buttons, and the keyboard grab:
// keys go to the session only while grabbed, Ctrl+Alt+Home and losing the focus release it, and
// releasing lets go of every key still down.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { zoomedSize } from './display';
import type { FrameInput } from './frameSocket';
import {
  buttonsOf,
  grabKeyboard,
  isReleaseChord,
  scancodeOf,
  toDesktop,
  wheelOf,
  type KeyboardGrab,
} from './input';

describe('scancodeOf', () => {
  it('maps physical keys to set-1 make codes', () => {
    expect(scancodeOf('KeyA')).toEqual({ code: 0x1e, ext: false });
    expect(scancodeOf('KeyZ')).toEqual({ code: 0x2c, ext: false });
    expect(scancodeOf('Digit0')).toEqual({ code: 0x0b, ext: false });
    expect(scancodeOf('Enter')).toEqual({ code: 0x1c, ext: false });
    expect(scancodeOf('F12')).toEqual({ code: 0x58, ext: false });
    expect(scancodeOf('IntlBackslash')).toEqual({ code: 0x56, ext: false });
    expect(scancodeOf('Numpad7')).toEqual({ code: 0x47, ext: false });
  });

  it('sets E0 for the keys that share a code with the numpad or the left side', () => {
    expect(scancodeOf('NumpadEnter')).toEqual({ code: 0x1c, ext: true });
    expect(scancodeOf('ControlRight')).toEqual({ code: 0x1d, ext: true });
    expect(scancodeOf('AltRight')).toEqual({ code: 0x38, ext: true });
    expect(scancodeOf('Home')).toEqual({ code: 0x47, ext: true });
    expect(scancodeOf('ArrowLeft')).toEqual({ code: 0x4b, ext: true });
    expect(scancodeOf('Delete')).toEqual({ code: 0x53, ext: true });
    expect(scancodeOf('MetaLeft')).toEqual({ code: 0x5b, ext: true });
  });

  it('gives null for keys without a plain code and for inherited names', () => {
    expect(scancodeOf('Pause')).toBeNull();
    expect(scancodeOf('MediaPlayPause')).toBeNull();
    expect(scancodeOf('')).toBeNull();
    expect(scancodeOf('toString')).toBeNull();
  });
});

describe('toDesktop', () => {
  // 1280x720 in a 1000x360 box: the picture is 640x360 at x 180.
  it('maps the fitted picture onto the desktop', () => {
    expect(toDesktop(180, 0, 1000, 360, 1280, 720)).toEqual({ x: 0, y: 0 });
    expect(toDesktop(500, 180, 1000, 360, 1280, 720)).toEqual({ x: 640, y: 360 });
    expect(toDesktop(819.9, 359.9, 1000, 360, 1280, 720)).toEqual({ x: 1279, y: 719 });
  });

  it('puts a point in the bars on the edge of the desktop', () => {
    expect(toDesktop(10, 100, 1000, 360, 1280, 720)).toEqual({ x: 0, y: 200 });
    expect(toDesktop(990, 400, 1000, 360, 1280, 720)).toEqual({ x: 1279, y: 719 });
  });

  it('is the origin before a desktop is known', () => {
    expect(toDesktop(50, 50, 1000, 360, 0, 0)).toEqual({ x: 0, y: 0 });
  });

  // A zoomed desktop (R-1100) has a canvas of its zoomed size, in a box that scrolls. The offset
  // of a pointer event is from the canvas, so the scrolled part is in it already.
  it('follows the zoom and the scroll of a fixed desktop', () => {
    const at200 = zoomedSize(1280, 720, 200, 1);
    // Scrolled by 1000 × 400, the pointer 280 × 320 into the box: 1280 × 720 into the canvas.
    const [scrollX, scrollY, inBoxX, inBoxY] = [1000, 400, 280, 320];
    expect(
      toDesktop(scrollX + inBoxX, scrollY + inBoxY, at200.width, at200.height, 1280, 720),
    ).toEqual({ x: 640, y: 360 });

    const at50 = zoomedSize(1920, 1080, 50, 1);
    expect(toDesktop(480, 270, at50.width, at50.height, 1920, 1080)).toEqual({ x: 960, y: 540 });
    // 1:1 on a screen of two pixels per CSS pixel: 960 × 540 CSS pixels for 1920 × 1080.
    const actual = zoomedSize(1920, 1080, 100, 2);
    expect(toDesktop(959.9, 539.9, actual.width, actual.height, 1920, 1080)).toEqual({
      x: 1919,
      y: 1079,
    });
  });
});

describe('wheel and buttons', () => {
  it('turns the DOM delta into one notch, up positive', () => {
    expect(wheelOf(-3)).toBe(120);
    expect(wheelOf(100)).toBe(-120);
    expect(wheelOf(0)).toBe(0);
  });

  it('keeps left, right and middle', () => {
    expect(buttonsOf(1 | 2 | 4 | 8 | 16)).toBe(7);
  });
});

describe('grabKeyboard', () => {
  let grab: KeyboardGrab | undefined;
  afterEach(() => grab?.destroy());

  function setup(): { target: HTMLElement; sent: FrameInput[]; changed: ReturnType<typeof vi.fn> } {
    const target = document.createElement('div');
    target.tabIndex = 0;
    document.body.append(target);
    const sent: FrameInput[] = [];
    const changed = vi.fn();
    grab = grabKeyboard(target, (input) => sent.push(input), changed);
    return { target, sent, changed };
  }

  const key = (
    target: HTMLElement,
    type: 'keydown' | 'keyup',
    code: string,
    init: KeyboardEventInit = {},
  ): KeyboardEvent => {
    const event = new KeyboardEvent(type, { code, bubbles: true, cancelable: true, ...init });
    target.dispatchEvent(event);
    return event;
  };

  it('sends nothing and blocks nothing until grabbed', () => {
    const { target, sent } = setup();
    const event = key(target, 'keydown', 'KeyA');
    expect(sent).toEqual([]);
    expect(event.defaultPrevented).toBe(false);
  });

  it('sends grabbed keys as scancodes and keeps them from the app', () => {
    const { target, sent, changed } = setup();
    const outside = vi.fn();
    document.body.addEventListener('keydown', outside);
    grab!.grab();
    expect(changed).toHaveBeenCalledWith(true);
    const event = key(target, 'keydown', 'ArrowUp');
    key(target, 'keyup', 'ArrowUp');
    expect(event.defaultPrevented).toBe(true);
    expect(outside).not.toHaveBeenCalled();
    expect(sent).toEqual([
      { t: 'key', code: 0x48, ext: true, down: true },
      { t: 'key', code: 0x48, ext: true, down: false },
    ]);
    document.body.removeEventListener('keydown', outside);
  });

  it('does not send the release of a key pressed before the grab', () => {
    const { target, sent } = setup();
    grab!.grab();
    key(target, 'keyup', 'KeyA');
    expect(sent).toEqual([]);
  });

  it('releases on Ctrl+Alt+Home, without the Home, and lets go of Ctrl and Alt', () => {
    const { target, sent, changed } = setup();
    grab!.grab();
    key(target, 'keydown', 'ControlLeft', { ctrlKey: true });
    key(target, 'keydown', 'AltLeft', { ctrlKey: true, altKey: true });
    const home = key(target, 'keydown', 'Home', { ctrlKey: true, altKey: true });
    expect(home.defaultPrevented).toBe(true);
    expect(grab!.grabbed).toBe(false);
    expect(changed).toHaveBeenLastCalledWith(false);
    expect(sent).toEqual([
      { t: 'key', code: 0x1d, ext: false, down: true },
      { t: 'key', code: 0x38, ext: false, down: true },
      { t: 'key', code: 0x1d, ext: false, down: false },
      { t: 'key', code: 0x38, ext: false, down: false },
    ]);
    // Released: the next key is the app's again.
    expect(key(target, 'keydown', 'KeyA').defaultPrevented).toBe(false);
    expect(sent).toHaveLength(4);
  });

  it('releases when the element or the window loses the focus', () => {
    const { target, sent, changed } = setup();
    grab!.grab();
    key(target, 'keydown', 'ShiftLeft');
    target.dispatchEvent(new FocusEvent('blur'));
    expect(grab!.grabbed).toBe(false);
    expect(sent.at(-1)).toEqual({ t: 'key', code: 0x2a, ext: false, down: false });
    grab!.grab();
    window.dispatchEvent(new FocusEvent('blur'));
    expect(grab!.grabbed).toBe(false);
    expect(changed.mock.calls).toEqual([[true], [false], [true], [false]]);
  });

  it('ends grabbed keys and listening when destroyed', () => {
    const { target, sent } = setup();
    grab!.grab();
    key(target, 'keydown', 'KeyQ');
    grab!.destroy();
    expect(sent.at(-1)).toEqual({ t: 'key', code: 0x10, ext: false, down: false });
    expect(key(target, 'keydown', 'KeyQ').defaultPrevented).toBe(false);
  });

  it('knows the release chord only as a key press', () => {
    const init = { code: 'Home', ctrlKey: true, altKey: true };
    expect(isReleaseChord(new KeyboardEvent('keydown', init))).toBe(true);
    expect(isReleaseChord(new KeyboardEvent('keyup', init))).toBe(false);
    expect(isReleaseChord(new KeyboardEvent('keydown', { code: 'Home', ctrlKey: true }))).toBe(
      false,
    );
  });
});
