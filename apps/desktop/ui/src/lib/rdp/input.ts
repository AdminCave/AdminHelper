// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Keyboard and mouse of an embedded RDP session. Keys go out as PC/AT set-1 scancodes taken from
// `KeyboardEvent.code` (the physical key, whatever the local layout), so the server's layout
// decides the character. While the keyboard is grabbed every key goes to the session;
// Ctrl+Alt+Home and losing the focus give it back.

import type { FrameInput } from './frameSocket';
import { fitRect } from './renderer';

export interface Scancode {
  code: number;
  // The E0 prefix.
  ext: boolean;
}

const PLAIN: Record<string, number> = {
  Escape: 0x01,
  Digit1: 0x02,
  Digit2: 0x03,
  Digit3: 0x04,
  Digit4: 0x05,
  Digit5: 0x06,
  Digit6: 0x07,
  Digit7: 0x08,
  Digit8: 0x09,
  Digit9: 0x0a,
  Digit0: 0x0b,
  Minus: 0x0c,
  Equal: 0x0d,
  Backspace: 0x0e,
  Tab: 0x0f,
  KeyQ: 0x10,
  KeyW: 0x11,
  KeyE: 0x12,
  KeyR: 0x13,
  KeyT: 0x14,
  KeyY: 0x15,
  KeyU: 0x16,
  KeyI: 0x17,
  KeyO: 0x18,
  KeyP: 0x19,
  BracketLeft: 0x1a,
  BracketRight: 0x1b,
  Enter: 0x1c,
  ControlLeft: 0x1d,
  KeyA: 0x1e,
  KeyS: 0x1f,
  KeyD: 0x20,
  KeyF: 0x21,
  KeyG: 0x22,
  KeyH: 0x23,
  KeyJ: 0x24,
  KeyK: 0x25,
  KeyL: 0x26,
  Semicolon: 0x27,
  Quote: 0x28,
  Backquote: 0x29,
  ShiftLeft: 0x2a,
  Backslash: 0x2b,
  KeyZ: 0x2c,
  KeyX: 0x2d,
  KeyC: 0x2e,
  KeyV: 0x2f,
  KeyB: 0x30,
  KeyN: 0x31,
  KeyM: 0x32,
  Comma: 0x33,
  Period: 0x34,
  Slash: 0x35,
  ShiftRight: 0x36,
  NumpadMultiply: 0x37,
  AltLeft: 0x38,
  Space: 0x39,
  CapsLock: 0x3a,
  F1: 0x3b,
  F2: 0x3c,
  F3: 0x3d,
  F4: 0x3e,
  F5: 0x3f,
  F6: 0x40,
  F7: 0x41,
  F8: 0x42,
  F9: 0x43,
  F10: 0x44,
  NumLock: 0x45,
  ScrollLock: 0x46,
  Numpad7: 0x47,
  Numpad8: 0x48,
  Numpad9: 0x49,
  NumpadSubtract: 0x4a,
  Numpad4: 0x4b,
  Numpad5: 0x4c,
  Numpad6: 0x4d,
  NumpadAdd: 0x4e,
  Numpad1: 0x4f,
  Numpad2: 0x50,
  Numpad3: 0x51,
  Numpad0: 0x52,
  NumpadDecimal: 0x53,
  IntlBackslash: 0x56,
  F11: 0x57,
  F12: 0x58,
  IntlRo: 0x73,
  IntlYen: 0x7d,
};

const EXTENDED: Record<string, number> = {
  NumpadEnter: 0x1c,
  ControlRight: 0x1d,
  NumpadDivide: 0x35,
  PrintScreen: 0x37,
  AltRight: 0x38,
  Home: 0x47,
  ArrowUp: 0x48,
  PageUp: 0x49,
  ArrowLeft: 0x4b,
  ArrowRight: 0x4d,
  End: 0x4f,
  ArrowDown: 0x50,
  PageDown: 0x51,
  Insert: 0x52,
  Delete: 0x53,
  MetaLeft: 0x5b,
  MetaRight: 0x5c,
  ContextMenu: 0x5d,
};

// Null for a key set 1 has no plain make code for (Pause, media keys): it is not sent.
export function scancodeOf(code: string): Scancode | null {
  if (Object.hasOwn(PLAIN, code)) return { code: PLAIN[code], ext: false };
  if (Object.hasOwn(EXTENDED, code)) return { code: EXTENDED[code], ext: true };
  return null;
}

// Ctrl+Alt+Home gives the keyboard back; the session never sees the Home.
export function isReleaseChord(event: KeyboardEvent): boolean {
  return event.type === 'keydown' && event.code === 'Home' && event.ctrlKey && event.altKey;
}

const clamp = (value: number, max: number): number =>
  Math.min(Math.max(Math.floor(value), 0), Math.max(max - 1, 0));

// A point in the canvas box (CSS pixels from its top left) in desktop pixels, the canvas being
// fitted with `object-fit: contain`; a point in the bars beside the picture lands on its edge.
export function toDesktop(
  offsetX: number,
  offsetY: number,
  boxWidth: number,
  boxHeight: number,
  desktopWidth: number,
  desktopHeight: number,
): { x: number; y: number } {
  const picture = fitRect(boxWidth, boxHeight, desktopWidth, desktopHeight);
  if (picture.width === 0 || picture.height === 0) return { x: 0, y: 0 };
  return {
    x: clamp(((offsetX - picture.x) * desktopWidth) / picture.width, desktopWidth),
    y: clamp(((offsetY - picture.y) * desktopHeight) / picture.height, desktopHeight),
  };
}

// One notch of the wheel as RDP counts it; up is positive, the reverse of the DOM's deltaY.
export const WHEEL_STEP = 120;

export function wheelOf(deltaY: number): number {
  if (deltaY < 0) return WHEEL_STEP;
  if (deltaY > 0) return -WHEEL_STEP;
  return 0;
}

// The DOM's `buttons` bits are the protocol's: 1 left, 2 right, 4 middle.
export function buttonsOf(buttons: number): number {
  return buttons & 0b111;
}

export interface KeyboardGrab {
  readonly grabbed: boolean;
  grab(): void;
  release(): void;
  destroy(): void;
}

// Grabs the keyboard of `target`: while grabbed, its key events go to `send` as scancodes and
// none reaches the app. Releasing lets go of every key the session still holds down, so no key
// stays pressed on the server.
export function grabKeyboard(
  target: HTMLElement,
  send: (input: FrameInput) => void,
  changed: (grabbed: boolean) => void = () => {},
): KeyboardGrab {
  let grabbed = false;
  const held = new Map<string, Scancode>();

  const release = (): void => {
    if (!grabbed) return;
    grabbed = false;
    for (const key of held.values()) send({ t: 'key', code: key.code, ext: key.ext, down: false });
    held.clear();
    changed(false);
  };

  const onKey = (event: KeyboardEvent): void => {
    if (!grabbed) return;
    event.preventDefault();
    event.stopPropagation();
    if (isReleaseChord(event)) {
      release();
      return;
    }
    const key = scancodeOf(event.code);
    if (!key) return;
    const down = event.type === 'keydown';
    if (down) held.set(event.code, key);
    else if (!held.delete(event.code)) return;
    send({ t: 'key', code: key.code, ext: key.ext, down });
  };

  target.addEventListener('keydown', onKey);
  target.addEventListener('keyup', onKey);
  target.addEventListener('blur', release);
  window.addEventListener('blur', release);

  return {
    get grabbed() {
      return grabbed;
    },
    grab() {
      if (grabbed) return;
      grabbed = true;
      changed(true);
    },
    release,
    destroy() {
      release();
      target.removeEventListener('keydown', onKey);
      target.removeEventListener('keyup', onKey);
      target.removeEventListener('blur', release);
      window.removeEventListener('blur', release);
    },
  };
}
