// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/** Normalize an unknown thrown value to a message string. */
export function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// The stable codes the backend puts in front of a message so the UI can key off
// them (error.rs, auth.rs). They are for the code, not the user; they can sit
// anywhere in a message, buried in the reqwest source chain.
const ERROR_CODES = /ERR_(?:(?:CA|TOFU)_PIN_MISMATCH|TLS_UNKNOWN_ISSUER|MTLS_CERT_REQUIRED):\s*/g;

/** A backend message as the user reads it: the human text without the codes. */
export function withoutErrorCodes(msg: string): string {
  return msg.replace(ERROR_CODES, '');
}

/** Sentinel the session layer throws when the JWT expired (surfaced by refresh);
 * callers suppress the error toast when errMsg(err) matches it. */
export const SESSION_EXPIRED = 'SESSION_EXPIRED';
