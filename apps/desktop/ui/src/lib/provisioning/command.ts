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
// A pasted command must never carry a line break or control character inside a value: the
// quoting would keep it literal, but the reader of the copied text could not see it.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/;

export interface ProvisionValues {
  serverUrl: string;
  serverId: string;
  caFp: string | null;
  token: string | null;
  // The desktop setting for self-signed certificates: `--insecure` only with it and without
  // a CA fingerprint (the trust path of the old Linux tab).
  allowInsecure: boolean;
}

const SHELLS: Record<string, { quote: (v: string) => string; join: string }> = {
  bash: { quote: shellQuote, join: ' \\\n  ' },
  sh: { quote: shellQuote, join: ' \\\n  ' },
  powershell: { quote: psQuote, join: ' `\n  ' },
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
  return parts.join(shell.join);
}
