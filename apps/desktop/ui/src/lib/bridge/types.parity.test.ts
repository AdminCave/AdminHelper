// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

/**
 * Serde structs vs. bridge/types.ts (harness 8a, T12).
 *
 * types.ts says "When models.rs changes, update this file manually" — and that
 * is exactly the instruction nothing enforced: `ResolvedConnection` carried four
 * fields in Rust and three in TypeScript, so `tunnelType` silently arrived as
 * `undefined` in the UI.
 *
 * Compared are FIELD NAMES on the wire, per type. Optionality deliberately is
 * not: serde models a missing value as `Option<T>` and TypeScript as `?` or
 * `| null`, and those three do not line up one-to-one — comparing them would
 * produce noise, not drift.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// src/lib/bridge -> the desktop component root
const DESKTOP = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const RUST_FILES = ['models.rs', 'tunnel.rs', 'ansible.rs'];

/** serde types in other modules, with the reason each stays out of the scan. */
const NOT_ON_THE_BRIDGE: Record<string, string> = {
  EnrollGrant: 'enrollment.rs — wire type of the /enroll HTTP call, never an IPC result',
  EnrollRequest: 'enrollment.rs — request body sent to the issuer',
  IssuedIdentity: 'enrollment.rs — issuer response, consumed inside Rust',
};

/** Rust types with no TypeScript counterpart, and why each one may stay. */
const RUST_ONLY_ALLOWLIST: Record<string, string> = {
  RdpErrorPayload: 'event payload, not a command result — never crosses bridge/index.ts',
};

const rustSource = (file: string): string =>
  readFileSync(join(DESKTOP, 'src-tauri', 'src', file), 'utf-8');
const tsSource = (): string =>
  readFileSync(join(DESKTOP, 'ui', 'src', 'lib', 'bridge', 'types.ts'), 'utf-8');

const toCamel = (s: string): string =>
  s.replace(/_([a-z0-9])/g, (_m, c: string) => c.toUpperCase());

function applyRenameAll(name: string, renameAll: string | null): string {
  if (renameAll === 'camelCase') return toCamel(name);
  if (renameAll === 'lowercase') return name.toLowerCase();
  return name;
}

interface RustType {
  kind: 'struct' | 'enum';
  members: string[];
}

/** Serde structs and enums with their wire-level member names. */
function rustTypes(): Map<string, RustType> {
  const out = new Map<string, RustType>();
  for (const file of RUST_FILES) {
    const src = rustSource(file);
    const decl =
      /#\[derive\(([^)]*)\)\]\s*((?:#\[serde\([^)]*\)\]\s*)*)pub (struct|enum) (\w+)[^{]*\{([\s\S]*?)\n\}/g;
    for (const m of src.matchAll(decl)) {
      const [, derives, attrs, kind, name, body] = m;
      if (!/\bSerialize\b|\bDeserialize\b/.test(derives)) continue;
      const renameAll = /rename_all\s*=\s*"([^"]+)"/.exec(attrs)?.[1] ?? null;

      const members: string[] = [];
      // Attributes accumulate until the member they belong to is reached.
      let pending = '';
      for (const raw of body.split('\n')) {
        const line = raw.trim();
        if (line.startsWith('//') || line === '') continue;
        if (line.startsWith('#[')) {
          pending += line;
          continue;
        }
        const rename = /rename\s*=\s*"([^"]+)"/.exec(pending)?.[1];
        const field = kind === 'struct' ? /^pub (\w+)\s*:/.exec(line) : /^(\w+)\s*,?$/.exec(line);
        if (field) members.push(rename ?? applyRenameAll(field[1], renameAll));
        pending = '';
      }
      out.set(name, { kind: kind as 'struct' | 'enum', members });
    }
  }
  return out;
}

/** TypeScript interfaces (field names) and union type aliases (literals). */
function tsTypes(): Map<string, string[]> {
  const src = tsSource();
  const out = new Map<string, string[]>();
  for (const m of src.matchAll(/export interface (\w+)\s*\{([\s\S]*?)\n\}/g)) {
    const fields = [...m[2].matchAll(/^\s*(\w+)\??\s*:/gm)].map((f) => f[1]);
    out.set(m[1], fields);
  }
  for (const m of src.matchAll(/export type (\w+) = ([^;]+);/g)) {
    const literals = [...m[2].matchAll(/'([^']+)'/g)].map((l) => l[1]);
    if (literals.length) out.set(m[1], literals);
  }
  return out;
}

describe('serde <-> bridge/types.ts parity', () => {
  it('scans every serde type under src-tauri, or names why not', () => {
    // RUST_FILES is hand-kept. Without this, a bridge-crossing struct added to
    // any other module sits outside the guard — the same drift class the missing
    // tunnelType was, one file over, and the size floors below cannot see it.
    const dir = join(DESKTOP, 'src-tauri', 'src');
    const decl = /#\[derive\(([^)]*)\)\]\s*(?:#\[serde\([^)]*\)\]\s*)*pub (?:struct|enum) (\w+)/g;
    const unscanned: string[] = [];
    for (const entry of readdirSync(dir)) {
      if (!entry.endsWith('.rs') || RUST_FILES.includes(entry)) continue;
      const src = readFileSync(join(dir, entry), 'utf-8');
      for (const m of src.matchAll(decl)) {
        if (!/\bSerialize\b|\bDeserialize\b/.test(m[1])) continue;
        if (!(m[2] in NOT_ON_THE_BRIDGE)) unscanned.push(`${entry}:${m[2]}`);
      }
    }
    expect(unscanned).toEqual([]);
  });

  it('parses both sides (non-empty guard)', () => {
    const rust = rustTypes();
    const ts = tsTypes();
    expect(rust.size).toBeGreaterThanOrEqual(10);
    expect(ts.size).toBeGreaterThanOrEqual(10);
    // A struct that parsed to zero members would make its comparison vacuous.
    for (const [name, t] of rust)
      expect(t.members.length, `${name} parsed empty`).toBeGreaterThan(0);
  });

  it('has a TypeScript counterpart for every serde type', () => {
    const ts = tsTypes();
    const missing = [...rustTypes().keys()]
      .filter((n) => !ts.has(n) && !(n in RUST_ONLY_ALLOWLIST))
      .sort();
    expect(missing).toEqual([]);
  });

  it('agrees on the field names of every struct', () => {
    const ts = tsTypes();
    const drift: Record<string, { rustOnly: string[]; tsOnly: string[] }> = {};
    for (const [name, t] of rustTypes()) {
      if (t.kind !== 'struct' || !ts.has(name)) continue;
      const tsFields = new Set(ts.get(name));
      const rustOnly = t.members.filter((f) => !tsFields.has(f)).sort();
      const tsOnly = [...tsFields].filter((f) => !t.members.includes(f)).sort();
      if (rustOnly.length || tsOnly.length) drift[name] = { rustOnly, tsOnly };
    }
    expect(drift).toEqual({});
  });

  it('agrees on the variants of every enum', () => {
    const ts = tsTypes();
    const drift: Record<string, { rustOnly: string[]; tsOnly: string[] }> = {};
    for (const [name, t] of rustTypes()) {
      if (t.kind !== 'enum' || !ts.has(name)) continue;
      const tsLiterals = new Set(ts.get(name));
      const rustOnly = t.members.filter((v) => !tsLiterals.has(v)).sort();
      const tsOnly = [...tsLiterals].filter((v) => !t.members.includes(v)).sort();
      if (rustOnly.length || tsOnly.length) drift[name] = { rustOnly, tsOnly };
    }
    expect(drift).toEqual({});
  });
});
