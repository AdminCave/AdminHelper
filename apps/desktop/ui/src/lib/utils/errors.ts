// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/** An unknown thrown value as the user reads it: its message without the codes. */
export function errMsg(err: unknown): string {
  return withoutErrorCodes(errRaw(err));
}

/** The raw message of an unknown thrown value, codes included: only for the code that
 * branches on them (the login screen). */
export function errRaw(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// The stable codes the backend puts in front of a message so the UI can key off them
// (error.rs, auth.rs; ERR_CERT_USER_MISMATCH and ERR_CERT_REVOKED come from the server).
// They are for the code, not the user; they can sit anywhere in a message, buried in
// the reqwest source chain. errMsg drops them, so no message shows them by accident
// (R-0276); errRaw keeps them.
const ERROR_CODES =
  /ERR_(?:(?:CA|TOFU)_PIN_MISMATCH|TLS_UNKNOWN_ISSUER|MTLS_CERT_REQUIRED|CERT_USER_MISMATCH|CERT_REVOKED):\s*/g;

/** A backend message as the user reads it: the human text without the codes. */
export function withoutErrorCodes(msg: string): string {
  return msg.replace(ERROR_CODES, '');
}

/** Sentinel the session layer throws when the JWT expired (surfaced by refresh);
 * callers suppress the error toast when errMsg(err) matches it. */
export const SESSION_EXPIRED = 'SESSION_EXPIRED';
