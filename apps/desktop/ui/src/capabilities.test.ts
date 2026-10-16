// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

/**
 * Dialog functions vs. the capabilities (R-0395).
 *
 * A function of `@tauri-apps/plugin-dialog` the window may not call rejects at
 * runtime, in the packaged app only: the unit tests mock the plugin. The reset
 * buttons asked through `confirm` while `capabilities/default.json` allowed
 * `save` alone, the rejection went nowhere and the buttons did nothing. Every
 * function a source under `src/` imports from the plugin has to be allowed.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// src -> the desktop component root
const DESKTOP = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const UI_SRC = join(DESKTOP, 'ui', 'src');
const PLUGIN = '@tauri-apps/plugin-dialog';

/**
 * Plugin function → the permissions that allow it (tauri-plugin-dialog 2.7.1,
 * `permissions/`): `allow-ask` and `allow-confirm` are aliases of
 * `allow-message`, all three JS functions send the `message` command, and
 * `default` grants message, save and open.
 */
const ALLOWED_BY: Record<string, string[]> = {
  save: ['dialog:allow-save', 'dialog:default'],
  open: ['dialog:allow-open', 'dialog:default'],
  message: ['dialog:allow-message', 'dialog:allow-ask', 'dialog:allow-confirm', 'dialog:default'],
  ask: ['dialog:allow-message', 'dialog:allow-ask', 'dialog:allow-confirm', 'dialog:default'],
  confirm: ['dialog:allow-message', 'dialog:allow-ask', 'dialog:allow-confirm', 'dialog:default'],
};

/** Every app source under ui/src: tests mock the plugin and never reach the window. */
function appSources(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) appSources(full, acc);
    else if ((full.endsWith('.ts') || full.endsWith('.svelte')) && !full.endsWith('.test.ts'))
      acc.push(full);
  }
  return acc;
}

const rel = (file: string): string => file.slice(DESKTOP.length + 1);

const NAMED_IMPORT = /import\s+(type\s+)?\{([^}]*)\}\s*from\s*['"]@tauri-apps\/plugin-dialog['"]/g;
const ANY_MENTION = /['"]@tauri-apps\/plugin-dialog['"]/g;

/** Plugin function → the files that import it, value imports only. */
function importedFunctions(): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const file of appSources(UI_SRC)) {
    const src = readFileSync(file, 'utf-8');
    for (const m of src.matchAll(NAMED_IMPORT)) {
      if (m[1]) continue;
      for (const spec of m[2].split(',')) {
        const name = spec.trim().split(/\s+as\s+/)[0];
        if (!name || name.startsWith('type ')) continue;
        used.set(name, [...(used.get(name) ?? []), rel(file)]);
      }
    }
  }
  return used;
}

function grantedPermissions(): Set<string> {
  const capability = JSON.parse(
    readFileSync(join(DESKTOP, 'src-tauri', 'capabilities', 'default.json'), 'utf-8'),
  ) as { permissions: (string | { identifier: string })[] };
  return new Set(capability.permissions.map((p) => (typeof p === 'string' ? p : p.identifier)));
}

describe(`${PLUGIN} functions vs. capabilities/default.json`, () => {
  it('finds the dialog functions the UI imports (non-empty guard)', () => {
    expect([...importedFunctions().keys()]).toContain('save');
  });

  it('imports the plugin by name only, so the scan sees every function', () => {
    // A namespace or dynamic import names no function: the check below would
    // pass without knowing what the window calls.
    const unscanned = appSources(UI_SRC)
      .filter((file) => {
        const src = readFileSync(file, 'utf-8');
        return (src.match(ANY_MENTION)?.length ?? 0) !== (src.match(NAMED_IMPORT)?.length ?? 0);
      })
      .map(rel);
    expect(unscanned).toEqual([]);
  });

  it('allows every dialog function the UI imports', () => {
    const granted = grantedPermissions();
    const refused = [...importedFunctions()]
      .filter(([name]) => !(ALLOWED_BY[name] ?? []).some((p) => granted.has(p)))
      .map(([name, files]) => `${name} (${files.join(', ')})`)
      .sort();
    expect(refused).toEqual([]);
  });
});
