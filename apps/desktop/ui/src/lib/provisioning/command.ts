// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Builds the copyable command from a catalog entry (GET /api/provisioning/platforms). The server
// sends a fixed head and named arguments, never quoted text: every value is quoted here, per
// shell. Anything this desktop does not know — a shell, a value kind, an argument mode — yields
// no command rather than a guess.

import type { ProvisionCommandSpec } from '$lib/api/types';
import { psQuote } from '$lib/utils/powershell';
import { shellQuote } from '$lib/utils/shell';

// The forms the server issues: `adminhelper_prov_` + token_urlsafe, and a uuid4. Only the
// character class for the token, so another prefix on the server would not break the dialog.
// No leading `-`: the token must never be a value a shell or the script reads as an option.
export const TOKEN_FORM = /^[A-Za-z0-9_][A-Za-z0-9_-]*$/;
export const UUID_FORM = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// A flag from the catalog goes into the command unquoted, so it must be a plain long option.
const FLAG_FORM = /^--[a-z][a-z0-9-]*$/;
// A pasted command must never carry a character its reader cannot see as what it is, in the
// head or in a value: control and format characters (Cc, Cf), every other character Unicode
// says to render invisibly, line and paragraph separators, a space other than U+0020 (it
// looks like a word break in the head but is none), and a lone surrogate. The quoting would
// keep them literal, but the shown text would lie.
const CONTROL = /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}\p{Default_Ignorable_Code_Point}]|(?! )\p{Zs}/u;

export interface ProvisionValues {
  serverUrl: string;
  serverId: string;
  caFp: string | null;
  token: string | null;
  // The desktop setting for self-signed certificates: `--insecure` only with it and without
  // a CA fingerprint (the trust path of the old Linux tab).
  allowInsecure: boolean;
}

interface Shell {
  quote: (v: string) => string;
  join: string;
  // Feeds a quoted value to the head's stdin.
  pipe: (quoted: string) => string;
}

const POSIX: Shell = {
  quote: shellQuote,
  join: ' \\\n  ',
  pipe: (q) => `printf '%s\\n' ${q} | `,
};
const SHELLS: Record<string, Shell> = {
  bash: POSIX,
  sh: POSIX,
  powershell: { quote: psQuote, join: ' `\n  ', pipe: (q) => `${q} | ` },
};

/** The command text, or null when it cannot be built safely. */
export function buildCommand(
  spec: ProvisionCommandSpec,
  values: ProvisionValues,
  automation: boolean,
): string | null {
  const shell = SHELLS[spec.shell];
  if (!shell || !spec.base || CONTROL.test(spec.base)) return null;
  if (!UUID_FORM.test(values.serverId)) return null;
  const parts = [spec.base];
  let stdin = '';
  for (const arg of spec.args) {
    if (!FLAG_FORM.test(arg.flag)) return null;
    if (arg.mode === 'interactive' && automation) continue;
    if (arg.mode === 'automation' && !automation) continue;
    if (arg.mode !== null && arg.mode !== 'interactive' && arg.mode !== 'automation') return null;
    let value: string | null;
    switch (arg.value) {
      case 'flag':
        parts.push(arg.flag);
        continue;
      case 'insecure':
        if (!values.caFp && values.allowInsecure) parts.push(arg.flag);
        continue;
      case 'serverUrl':
        value = values.serverUrl;
        break;
      case 'serverId':
        value = values.serverId;
        break;
      case 'caFp':
        value = values.caFp;
        break;
      case 'token':
        // The token only ever lands in the text in automation mode; otherwise it is asked
        // for hidden on the host.
        if (!automation) return null;
        value = values.token !== null && TOKEN_FORM.test(values.token) ? values.token : null;
        break;
      case 'tokenStdin':
        // Piped in rather than passed: an argument would sit in the host's process list
        // while the provisioning runs.
        if (!automation || values.token === null || !TOKEN_FORM.test(values.token)) return null;
        if (stdin) return null;
        stdin = shell.pipe(shell.quote(values.token));
        parts.push(arg.flag);
        continue;
      default:
        return null;
    }
    if (!value) {
      if (arg.optional) continue;
      return null;
    }
    if (CONTROL.test(value)) return null;
    // Windows PowerShell 5.1 passes an embedded `"` to a native .exe broken (it does not escape
    // it in the command line it builds), and the catalog calls the agent .exe directly.
    if (spec.shell === 'powershell' && value.includes('"')) return null;
    parts.push(`${arg.flag} ${shell.quote(value)}`);
  }
  return stdin + parts.join(shell.join);
}
