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

/** A command's refusal as the backend sends it ({code, message, status}, error.rs): the
 * code is for the code that branches, the message for the user. */
export class IpcError extends Error {
  readonly code: string | undefined;
  readonly status: number | undefined;

  constructor(message: string, code?: string, status?: number) {
    super(message);
    this.name = 'IpcError';
    this.code = code;
    this.status = status;
  }
}

// How much of a refusal of unknown form its message keeps.
const MAX_RAW = 300;

/** The Error a refused invoke() rejects with: the backend's object as IpcError, Tauri's own
 * text refusals (invalid args, unknown command) as a plain Error, anything else as an
 * Error whose message shows the value, never "[object Object]". */
export function fromIpc(raw: unknown): Error {
  if (raw instanceof Error) return raw;
  if (typeof raw === 'string') return new Error(raw);
  if (
    raw &&
    typeof raw === 'object' &&
    'code' in raw &&
    'message' in raw &&
    typeof raw.code === 'string' &&
    typeof raw.message === 'string'
  ) {
    const status = 'status' in raw ? httpStatus(raw.status) : undefined;
    return new IpcError(raw.message, raw.code, status);
  }
  return new Error(shown(raw));
}

function httpStatus(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 100 && value <= 599
    ? value
    : undefined;
}

function shown(raw: unknown): string {
  let text: string | undefined;
  try {
    text = JSON.stringify(raw);
  } catch {
    // A cycle or a BigInt: the plain string form below.
  }
  text ??= String(raw);
  return text.length > MAX_RAW ? `${text.slice(0, MAX_RAW - 1)}…` : text;
}

/** The backend's code of a refusal, or undefined for any other thrown value. */
export function errCode(err: unknown): string | undefined {
  return err instanceof IpcError ? err.code : undefined;
}

/** The HTTP status of a refusal that carries one, or undefined. */
export function errStatus(err: unknown): number | undefined {
  return err instanceof IpcError ? err.status : undefined;
}

/** The code of a refusal whose session is gone (AppError::SessionExpired, error.rs): the
 * login screen follows, so callers report no error for it. */
export const SESSION_EXPIRED = 'ERR_SESSION_EXPIRED';

export function isSessionExpired(err: unknown): boolean {
  return errCode(err) === SESSION_EXPIRED;
}
