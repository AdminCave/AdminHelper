// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// What the embedded terminal (R-1069) pastes: text, tabs and line breaks. Any other control
// character would reach the program as a key of its own, not as part of the pasted text.

function isDropped(code: number): boolean {
  return (
    (code < 0x20 && code !== 0x09 && code !== 0x0a && code !== 0x0d) ||
    (code >= 0x7f && code <= 0x9f)
  );
}

/** `text` without the C0 and C1 control characters and DEL; tab, LF and CR stay. */
export function sanitizePaste(text: string): string {
  let out = '';
  for (const ch of text) {
    if (!isDropped(ch.charCodeAt(0))) out += ch;
  }
  return out;
}
