// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

import { describe, it, expect } from 'vitest';
import { execFileSync } from 'child_process';
import type { ProvisionCommandArg, ProvisionCommandSpec } from '$lib/api/types';
import { buildCommand, type ProvisionValues } from './command';

const ID = '3f2b8c1e-5d4a-4b6f-9e2d-7a1c0b9e8f42';
const TOKEN = 'adminhelper_prov_AbC-_9z';
const VALUES: ProvisionValues = {
  serverUrl: 'https://srm.example:8443',
  serverId: ID,
  caFp: 'ab'.repeat(32),
  token: TOKEN,
  allowInsecure: false,
};

function arg(
  flag: string,
  value: string,
  more: Partial<ProvisionCommandArg> = {},
): ProvisionCommandArg {
  return { flag, value, optional: false, mode: null, ...more };
}

const INSTALL: ProvisionCommandSpec = {
  action: 'install',
  shell: 'bash',
  base: 'curl -fsSL https://example/agent-install.sh | sudo bash -s --',
  args: [
    arg('--server', 'serverUrl'),
    arg('--server-id', 'serverId'),
    arg('--ca-fp', 'caFp', { optional: true }),
    arg('--token', 'token', { mode: 'automation' }),
  ],
};

// A printf head instead of the installer: running the built text in a real shell shows
// exactly the argv the installer would get.
function argv(shell: 'bash' | 'dash', spec: ProvisionCommandSpec, values: ProvisionValues) {
  const text = buildCommand({ ...spec, base: "printf '[%s]\\n'" }, values, true);
  expect(text).not.toBeNull();
  return execFileSync(shell, ['-c', text as string], { encoding: 'utf8' });
}

// What the copied text could hide from its reader: one per Unicode class the check covers.
const INVISIBLE: [string, string][] = [
  ['a C1 control', '\u0085'],
  ['a line separator', '\u2028'],
  ['a paragraph separator', '\u2029'],
  ['a direction override', '\u202e'],
  ['a direction isolate', '\u2067'],
  ['a direction mark', '\u200f'],
  ['an Arabic letter mark', '\u061c'],
  ['a zero-width space', '\u200b'],
  ['a zero-width joiner', '\u200d'],
  ['a word joiner', '\u2060'],
  ['a byte order mark', '\ufeff'],
  ['a soft hyphen', '\u00ad'],
  ['a lone surrogate', '\ud800'],
  ['a Hangul filler', '\u3164'],
  ['a variation selector', '\ufe0f'],
  ['a combining grapheme joiner', '\u034f'],
  ['a no-break space', '\u00a0'],
  ['an ideographic space', '\u3000'],
];

describe('buildCommand', () => {
  it('builds the interactive bash command without the token', () => {
    expect(buildCommand(INSTALL, VALUES, false)).toBe(
      'curl -fsSL https://example/agent-install.sh | sudo bash -s -- \\\n' +
        '  --server https://srm.example:8443 \\\n' +
        `  --server-id ${ID} \\\n` +
        `  --ca-fp ${'ab'.repeat(32)}`,
    );
  });

  it('puts the token in only in automation mode', () => {
    expect(buildCommand(INSTALL, VALUES, true)).toContain(`--token ${TOKEN}`);
    expect(buildCommand(INSTALL, VALUES, false)).not.toContain(TOKEN);
  });

  it('drops interactive-only arguments in automation mode', () => {
    const spec = { ...INSTALL, args: [arg('--token-stdin', 'flag', { mode: 'interactive' })] };
    expect(buildCommand(spec, VALUES, false)).toContain('--token-stdin');
    expect(buildCommand(spec, VALUES, true)).not.toContain('--token-stdin');
  });

  it('pipes the token in front of a PowerShell head, never as an argument', () => {
    const spec: ProvisionCommandSpec = {
      action: 'reregister',
      shell: 'powershell',
      base: "& 'C:\\Program Files\\AdminHelper Agent\\adminhelper-agent.exe' provision",
      args: [
        arg('--server-id', 'serverId'),
        arg('--token-stdin', 'flag', { mode: 'interactive' }),
        arg('--token-stdin', 'tokenStdin', { mode: 'automation' }),
      ],
    };
    expect(buildCommand(spec, VALUES, true)).toBe(
      `'${TOKEN}' | & 'C:\\Program Files\\AdminHelper Agent\\adminhelper-agent.exe' provision \`\n` +
        `  --server-id '${ID}' \`\n` +
        '  --token-stdin',
    );
    expect(buildCommand(spec, VALUES, false)).not.toContain(TOKEN);
  });

  it.each(['bash', 'dash'] as const)('%s hands the piped token to the head on stdin', (shell) => {
    const spec: ProvisionCommandSpec = {
      ...INSTALL,
      shell: 'sh',
      // A head that reads one line from stdin and prints it, then its own arguments.
      base: `sh -c 'read -r t; printf "[%s]\\n" "$t" "$@"' -`,
      args: [arg('--token-stdin', 'tokenStdin', { mode: 'automation' })],
    };
    const text = buildCommand(spec, VALUES, true);
    expect(text).not.toBeNull();
    // The flag stays in the head's argv, the token only in what the pipe writes.
    expect((text as string).split('|')[1]).not.toContain(TOKEN);
    expect(execFileSync(shell, ['-c', text as string], { encoding: 'utf8' })).toBe(
      `[${TOKEN}]\n[--token-stdin]\n`,
    );
  });

  it.each<[string, Partial<ProvisionValues>, boolean]>([
    ['outside automation mode', {}, false],
    ['without a token', { token: null }, true],
    ['with a token of another form', { token: '-x' }, true],
  ])('builds no piped token %s', (_name, values, automation) => {
    const spec = { ...INSTALL, args: [arg('--token-stdin', 'tokenStdin')] };
    expect(buildCommand(spec, { ...VALUES, ...values }, automation)).toBeNull();
  });

  it('never builds a token argument outside automation mode', () => {
    const spec = { ...INSTALL, args: [arg('--token', 'token')] };
    expect(buildCommand(spec, VALUES, false)).toBeNull();
  });

  it('skips a missing optional value and fails on a missing required one', () => {
    expect(buildCommand(INSTALL, { ...VALUES, caFp: null }, false)).not.toContain('--ca-fp');
    expect(buildCommand(INSTALL, { ...VALUES, token: null }, true)).toBeNull();
  });

  it('adds --insecure only without a CA fingerprint and with the setting', () => {
    const spec = {
      ...INSTALL,
      args: [arg('--ca-fp', 'caFp', { optional: true }), arg('--insecure', 'insecure')],
    };
    expect(buildCommand(spec, { ...VALUES, allowInsecure: true }, false)).not.toContain(
      '--insecure',
    );
    expect(buildCommand(spec, { ...VALUES, caFp: null }, false)).not.toContain('--insecure');
    expect(buildCommand(spec, { ...VALUES, caFp: null, allowInsecure: true }, false)).toContain(
      '--insecure',
    );
  });

  it.each([
    ['an unknown shell', { ...INSTALL, shell: 'fish' }],
    ['an unknown value kind', { ...INSTALL, args: [arg('--x', 'password')] }],
    ['an unknown mode', { ...INSTALL, args: [arg('--x', 'flag', { mode: 'later' })] }],
    ['a flag that is not a long option', { ...INSTALL, args: [arg('--x;id', 'flag')] }],
    ['a flag with a space', { ...INSTALL, args: [arg('--x y', 'flag')] }],
    ['a head with a line break', { ...INSTALL, base: 'curl x\nid' }],
    ['an empty head', { ...INSTALL, base: '' }],
    ...INVISIBLE.map(([name, ch]): [string, ProvisionCommandSpec] => [
      `a head with ${name}`,
      { ...INSTALL, base: `curl x${ch}y` },
    ]),
  ])('builds nothing for %s', (_, spec) => {
    expect(buildCommand(spec as ProvisionCommandSpec, VALUES, true)).toBeNull();
  });

  it.each<[string, Partial<ProvisionValues>]>([
    ['a server id that is no uuid', { serverId: '$(id)' }],
    ['a token in another form', { token: '-x' }],
    ['a token with a quote', { token: "a'b" }],
    ['a URL with a line break', { serverUrl: 'https://a\nid' }],
    ['a fingerprint with a control character', { caFp: 'ab\u0007' }],
    ...INVISIBLE.map(([name, ch]): [string, Partial<ProvisionValues>] => [
      `a URL with ${name}`,
      { serverUrl: `https://a${ch}b` },
    ]),
  ])('builds nothing for %s', (_, bad) => {
    expect(buildCommand(INSTALL, { ...VALUES, ...bad }, true)).toBeNull();
  });

  it('still builds a head with plain spaces and a value with an emoji', () => {
    const text = buildCommand(
      INSTALL,
      { ...VALUES, serverUrl: 'https://a.example/\u{1f600}' },
      true,
    );
    expect(text).toContain("'https://a.example/\u{1f600}'");
  });

  it.each(['bash', 'dash'] as const)('%s reads every hostile value back as itself', (shell) => {
    const url = 'https://a\'b"c$(id)`id`;|&<>*?~ $HOME\\x';
    const out = argv(shell, { ...INSTALL, shell: 'sh' }, { ...VALUES, serverUrl: url });
    expect(out).toBe(
      `[--server]\n[${url}]\n[--server-id]\n[${ID}]\n[--ca-fp]\n[${'ab'.repeat(32)}]\n[--token]\n[${TOKEN}]\n`,
    );
  });

  it('quotes for PowerShell and breaks lines with a backtick', () => {
    const spec: ProvisionCommandSpec = {
      action: 'reregister',
      shell: 'powershell',
      base: "& 'C:\\Program Files\\AdminHelper Agent\\adminhelper-agent.exe' provision",
      args: [arg('--url', 'serverUrl'), arg('--server-id', 'serverId')],
    };
    expect(buildCommand(spec, { ...VALUES, serverUrl: "https://a'b$(x)`y" }, false)).toBe(
      "& 'C:\\Program Files\\AdminHelper Agent\\adminhelper-agent.exe' provision `\n" +
        "  --url 'https://a''b$(x)`y' `\n" +
        `  --server-id '${ID}'`,
    );
  });

  // Windows PowerShell 5.1 hands an embedded `"` to a native .exe broken; bash quotes it fine.
  it('refuses a value with a double quote for PowerShell only', () => {
    const ps: ProvisionCommandSpec = {
      action: 'reregister',
      shell: 'powershell',
      base: "& 'C:\\Program Files\\AdminHelper Agent\\adminhelper-agent.exe' provision",
      args: [arg('--url', 'serverUrl'), arg('--server-id', 'serverId')],
    };
    const url = 'https://srm.example/a"b';
    expect(buildCommand(ps, { ...VALUES, serverUrl: url }, false)).toBeNull();
    expect(buildCommand(INSTALL, { ...VALUES, serverUrl: url }, false)).toContain(`'${url}'`);
  });
});
