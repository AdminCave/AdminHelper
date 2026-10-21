// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import type { SyncMode, WorkspaceDraft } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { WORKSPACE_NAME_MAX, WORKSPACE_PALETTE, hostOf, validateDraft } from './workspace';

// src/lib/models -> the desktop component root
const DESKTOP = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');

const draft = (kind: SyncMode, name: string, url?: string | null): WorkspaceDraft => ({
  kind,
  name,
  color: WORKSPACE_PALETTE[0],
  url,
});

const errorOf = (d: WorkspaceDraft, opts?: { urlRequired?: boolean }): string | undefined => {
  const result = validateDraft(d, opts);
  expect(result.ok).toBe(result.error === undefined);
  return result.error;
};

beforeAll(() => {
  setLanguage('en');
});

describe('WORKSPACE_PALETTE', () => {
  it('is the palette of workspace.rs, colour by colour and in its order', () => {
    // save_workspace rejects a colour outside the Rust palette.
    const source = readFileSync(join(DESKTOP, 'src-tauri', 'src', 'workspace.rs'), 'utf-8');
    const block = source.match(/pub const PALETTE: &\[&str\] = &\[([^\]]*)\];/);
    expect(block).not.toBeNull();
    const rust = [...(block?.[1] ?? '').matchAll(/"(#[0-9a-f]{6})"/g)].map((m) => m[1]);
    expect(rust.length).toBeGreaterThan(0);
    expect([...WORKSPACE_PALETTE]).toEqual(rust);
  });
});

describe('validateDraft: name', () => {
  it('takes a name and trims it before it counts', () => {
    expect(errorOf(draft('local', 'Kunde A'))).toBeUndefined();
    expect(errorOf(draft('local', `  ${'a'.repeat(WORKSPACE_NAME_MAX)}  `))).toBeUndefined();
  });

  it('rejects a blank name', () => {
    expect(errorOf(draft('local', ''))).toBe(tNow('validation.name.empty'));
    expect(errorOf(draft('local', '   '))).toBe(tNow('validation.name.empty'));
  });

  it('rejects a name over the limit and says the limit', () => {
    const error = errorOf(draft('local', 'a'.repeat(WORKSPACE_NAME_MAX + 1)));
    expect(error).toBe(tNow('validation.workspaceName.tooLong', { max: WORKSPACE_NAME_MAX }));
    expect(error).toContain(String(WORKSPACE_NAME_MAX));
  });

  it('counts characters as Rust does, not UTF-16 units', () => {
    // Each emoji is two UTF-16 units; .length would see 80 and reject.
    expect(errorOf(draft('local', '😀'.repeat(WORKSPACE_NAME_MAX)))).toBeUndefined();
    expect(errorOf(draft('local', '😀'.repeat(WORKSPACE_NAME_MAX + 1)))).toBe(
      tNow('validation.workspaceName.tooLong', { max: WORKSPACE_NAME_MAX }),
    );
  });

  it('rejects control characters, also at the ends where trim would drop them', () => {
    const control = tNow('validation.workspaceName.control');
    expect(errorOf(draft('local', 'Kunde\tA'))).toBe(control);
    expect(errorOf(draft('local', 'Kunde A\n'))).toBe(control);
    expect(errorOf(draft('local', 'Kunde\u0000A'))).toBe(control);
  });
});

describe('validateDraft: URL by kind (the rules of validateSettings)', () => {
  it('a server workspace needs https://, http:// only on loopback', () => {
    expect(errorOf(draft('server', 'A', 'https://ah.example.com'))).toBeUndefined();
    expect(errorOf(draft('server', 'A', '  https://ah.example.com  '))).toBeUndefined();
    expect(errorOf(draft('server', 'A', 'http://localhost:8443'))).toBeUndefined();
    expect(errorOf(draft('server', 'A', 'http://127.0.0.1'))).toBeUndefined();
    expect(errorOf(draft('server', 'A', 'http://ah.example.com'))).toBe(
      tNow('validation.serverUrl.https'),
    );
  });

  it('a server workspace needs a URL', () => {
    expect(errorOf(draft('server', 'A', ''))).toBe(tNow('validation.serverUrl.required'));
    expect(errorOf(draft('server', 'A', '   '))).toBe(tNow('validation.serverUrl.required'));
    expect(errorOf(draft('server', 'A', null))).toBe(tNow('validation.serverUrl.required'));
  });

  it('a sync workspace needs an https:// URL, also on loopback', () => {
    expect(errorOf(draft('sync', 'A', 'https://ah.example.com/sync.json'))).toBeUndefined();
    expect(errorOf(draft('sync', 'A', 'http://localhost/sync.json'))).toBe(
      tNow('validation.syncUrl.https'),
    );
    expect(errorOf(draft('sync', 'A', undefined))).toBe(tNow('validation.syncUrl.required'));
  });

  it('a local workspace has no URL to check', () => {
    expect(errorOf(draft('local', 'A', null))).toBeUndefined();
  });

  it('checks the name before the URL', () => {
    expect(errorOf(draft('server', ' ', 'http://ah.example.com'))).toBe(
      tNow('validation.name.empty'),
    );
  });

  it('without urlRequired a blank URL passes, a typed one is still checked', () => {
    // The edit of a migrated server workspace without a URL: it keeps none.
    const optional = { urlRequired: false };
    expect(errorOf(draft('server', 'A', null), optional)).toBeUndefined();
    expect(errorOf(draft('server', 'A', '   '), optional)).toBeUndefined();
    expect(errorOf(draft('sync', 'A', undefined), optional)).toBeUndefined();
    expect(errorOf(draft('server', 'A', 'http://ah.example.com'), optional)).toBe(
      tNow('validation.serverUrl.https'),
    );
    expect(errorOf(draft('sync', 'A', 'http://ah.example.com/c.json'), optional)).toBe(
      tNow('validation.syncUrl.https'),
    );
    expect(errorOf(draft('server', ' ', null), optional)).toBe(tNow('validation.name.empty'));
    // The default stays: a URL is required.
    expect(errorOf(draft('server', 'A', null), { urlRequired: true })).toBe(
      tNow('validation.serverUrl.required'),
    );
  });
});

describe('hostOf', () => {
  it('gives the host of a URL, without scheme, port, path or user', () => {
    expect(hostOf('https://ah.example.com')).toBe('ah.example.com');
    expect(hostOf('https://admin:pw@ah.example.com:8443/api?x=1')).toBe('ah.example.com');
    expect(hostOf('  https://ah.example.com/  ')).toBe('ah.example.com');
  });

  it('gives the host as Rust lists it: lower case, IPv6 in brackets', () => {
    expect(hostOf('https://AH.Example.COM')).toBe('ah.example.com');
    expect(hostOf('http://[::1]:8000')).toBe('[::1]');
    expect(hostOf('http://192.0.2.10:8000')).toBe('192.0.2.10');
  });

  it('gives null without a URL or a host', () => {
    expect(hostOf(null)).toBeNull();
    expect(hostOf(undefined)).toBeNull();
    expect(hostOf('')).toBeNull();
    expect(hostOf('ah.example.com')).toBeNull();
    expect(hostOf('https://')).toBeNull();
    expect(hostOf('file:///etc/passwd')).toBeNull();
  });
});
