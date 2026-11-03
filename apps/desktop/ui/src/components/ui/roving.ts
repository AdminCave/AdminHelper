// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Index the arrow, Home and End keys move to in a row of n items (wrapping), or
// undefined for any other key. Shared by Tabs, Segmented and Menu.
export function nextIndex(key: string, current: number, n: number): number | undefined {
  if (n === 0) return undefined;
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (current + 1) % n;
    case 'ArrowLeft':
    case 'ArrowUp':
      return (current - 1 + n) % n;
    case 'Home':
      return 0;
    case 'End':
      return n - 1;
    default:
      return undefined;
  }
}
