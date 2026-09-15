// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

/**
 * Tauri IPC inventory (harness 8a, T11).
 *
 * Three lists have to agree and none of them is checked by a compiler: the
 * commands `commands.rs` defines, the ones `main.rs` hands to
 * `generate_handler!`, and the names `bridge/index.ts` passes to `invoke()`.
 * A command that is defined but not registered is dead Rust; one the UI calls
 * without registration fails at runtime with "command not found" — in the
 * packaged app, in front of a user.
 *
 * The parsers read source text, so each one carries a minimum count: an empty
 * parse would make every set comparison below trivially true.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// src/lib/bridge -> the desktop component root
const DESKTOP = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const read = (...p: string[]): string => readFileSync(join(DESKTOP, ...p), 'utf-8');

/** Commands not called from the UI, with the reason each one may stay. */
const UNCALLED_ALLOWLIST: Record<string, string> = {
  enroll_device: 'no UI caller; roadmap row REF — wire it up or remove it',
};

function definedCommands(): Set<string> {
  const src = read('src-tauri', 'src', 'commands.rs');
  // The attribute may carry arguments (#[tauri::command(async)]), and rustfmt
  // keeps the fn on the next line — allow both.
  const re = /#\[tauri::command[^\]]*\]\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-z0-9_]+)/g;
  return new Set([...src.matchAll(re)].map((m) => m[1]));
}

function registeredCommands(): Set<string> {
  const src = read('src-tauri', 'src', 'main.rs');
  const block = /generate_handler!\[([\s\S]*?)\]/.exec(src);
  if (!block) throw new Error('generate_handler![…] not found in main.rs');
  return new Set(
    block[1]
      .split(',')
      .map((s) => s.trim())
      .filter((s) => /^[a-z0-9_]+$/.test(s)),
  );
}

/** Every .ts/.svelte file under ui/src, so the convention below can be checked. */
function uiSources(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) uiSources(full, acc);
    else if (full.endsWith('.ts') || full.endsWith('.svelte')) acc.push(full);
  }
  return acc;
}

function invokedCommands(): Set<string> {
  const src = read('ui', 'src', 'lib', 'bridge', 'index.ts');
  const re = /invoke\s*(?:<[^>]*>)?\(\s*'([a-z0-9_]+)'/g;
  return new Set([...src.matchAll(re)].map((m) => m[1]));
}

describe('tauri IPC inventory', () => {
  it('parses all three sources (non-empty guard)', () => {
    expect(definedCommands().size).toBeGreaterThanOrEqual(30);
    expect(registeredCommands().size).toBeGreaterThanOrEqual(30);
    expect(invokedCommands().size).toBeGreaterThanOrEqual(30);
  });

  it('registers exactly the commands it defines', () => {
    const defined = definedCommands();
    const registered = registeredCommands();
    expect([...registered].filter((c) => !defined.has(c)).sort()).toEqual([]);
    expect([...defined].filter((c) => !registered.has(c)).sort()).toEqual([]);
  });

  it('keeps every invoke() in bridge/index.ts', () => {
    // The inventory reads one file. That is only complete while the convention
    // holds — an invoke() in a component would be outside the guard, and a typo
    // there reaches the packaged app as "command not found" in front of a user.
    const bridge = join(DESKTOP, 'ui', 'src', 'lib', 'bridge', 'index.ts');
    const strays = uiSources(join(DESKTOP, 'ui', 'src'))
      .filter((f) => f !== bridge && !f.endsWith('.test.ts'))
      .filter((f) => /\binvoke\s*(<[^>]*>)?\(\s*['"`]/.test(readFileSync(f, 'utf-8')))
      .map((f) => f.slice(DESKTOP.length + 1));
    expect(strays).toEqual([]);
  });

  it('never invokes a command that is not registered', () => {
    const registered = registeredCommands();
    const unknown = [...invokedCommands()].filter((c) => !registered.has(c)).sort();
    expect(unknown).toEqual([]);
  });

  it('has no registered command without a caller beyond the allowlist', () => {
    const invoked = invokedCommands();
    const uncalled = [...registeredCommands()].filter((c) => !invoked.has(c)).sort();
    expect(uncalled).toEqual(Object.keys(UNCALLED_ALLOWLIST).sort());
  });
});
