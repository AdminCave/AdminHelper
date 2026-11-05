// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The colour schemes of the embedded terminal (R-1069). Background, text, selection and the
// colours for red, green, yellow, blue and grey are those of the mockup's terminal; magenta, cyan
// and the bright variants follow them, so a program's colour output stays readable on each.

import type { ITheme } from '@xterm/xterm';
import type { TerminalTheme } from '$lib/bridge/types';

const THEMES: Record<TerminalTheme, ITheme> = {
  cave: {
    background: '#111214',
    foreground: '#d6d9dc',
    cursor: '#d6d9dc',
    cursorAccent: '#111214',
    selectionBackground: 'rgba(79,157,255,0.28)',
    black: '#2a2c31',
    red: '#ff6b6b',
    green: '#34d186',
    yellow: '#f5b454',
    blue: '#4f9dff',
    magenta: '#c792ea',
    cyan: '#4fd1d9',
    white: '#d6d9dc',
    brightBlack: '#6e757c',
    brightRed: '#ff8f8f',
    brightGreen: '#62dda2',
    brightYellow: '#f8c87f',
    brightBlue: '#7ab5ff',
    brightMagenta: '#d9b2f1',
    brightCyan: '#7fe0e6',
    brightWhite: '#ffffff',
  },
  contrast: {
    background: '#000000',
    foreground: '#ffffff',
    cursor: '#ffffff',
    cursorAccent: '#000000',
    selectionBackground: 'rgba(96,165,250,0.35)',
    black: '#1f1f1f',
    red: '#f87171',
    green: '#4ade80',
    yellow: '#facc15',
    blue: '#60a5fa',
    magenta: '#e879f9',
    cyan: '#22d3ee',
    white: '#e5e7eb',
    brightBlack: '#9aa1a8',
    brightRed: '#fca5a5',
    brightGreen: '#86efac',
    brightYellow: '#fde047',
    brightBlue: '#93c5fd',
    brightMagenta: '#f0abfc',
    brightCyan: '#67e8f9',
    brightWhite: '#ffffff',
  },
  // On a light background "white" and the bright colours are darker shades: white text would
  // not show.
  light: {
    background: '#fafafa',
    foreground: '#16181c',
    cursor: '#16181c',
    cursorAccent: '#fafafa',
    selectionBackground: 'rgba(37,99,235,0.18)',
    black: '#16181c',
    red: '#c4363b',
    green: '#158045',
    yellow: '#b9780f',
    blue: '#2563eb',
    magenta: '#9333ea',
    cyan: '#0e7490',
    white: '#868d94',
    brightBlack: '#4b5157',
    brightRed: '#a3262b',
    brightGreen: '#0f6636',
    brightYellow: '#93600c',
    brightBlue: '#1d4ed8',
    brightMagenta: '#7e22ce',
    brightCyan: '#155e75',
    brightWhite: '#6e757c',
  },
};

/** The colours of scheme `name`; Cave for a name this version does not know. */
export function terminalTheme(name: string): ITheme {
  return Object.hasOwn(THEMES, name) ? THEMES[name as TerminalTheme] : THEMES.cave;
}
