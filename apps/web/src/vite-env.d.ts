// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="svelte" />
/// <reference types="vite/client" />

// Geist ist ein reines CSS-Paket (kein JS/Types-Entry) — der Side-Effect-Import
// in main.ts braucht eine Ambient-Deklaration, sonst findet svelte-check (strict)
// keine Typdeklaration und bricht ab.
declare module '@fontsource-variable/geist';
declare module '@fontsource-variable/geist-mono';
