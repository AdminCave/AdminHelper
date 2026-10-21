// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// errMsg is the message a user reads: the backend's codes are gone wherever they sit
// (R-0276). errRaw keeps them for the one place that branches on them.

import { describe, it, expect } from 'vitest';
import { errMsg, errRaw, SESSION_EXPIRED } from './errors';

const CODES = [
  'ERR_CA_PIN_MISMATCH',
  'ERR_TOFU_PIN_MISMATCH',
  'ERR_TLS_UNKNOWN_ISSUER',
  'ERR_MTLS_CERT_REQUIRED',
  'ERR_CERT_USER_MISMATCH',
  'ERR_CERT_REVOKED',
];

const CHAIN = 'error sending request: client error (Connect): ';

describe('errMsg', () => {
  it.each(CODES)('drops %s deep in a reqwest chain and keeps the prose', (code) => {
    const message = errMsg(new Error(`${CHAIN}${code}: Die Meldung bleibt vollständig`));
    expect(message).toBe(`${CHAIN}Die Meldung bleibt vollständig`);
  });

  it('drops a code at the start of the message', () => {
    expect(errMsg(new Error('ERR_CERT_REVOKED: This device certificate is no longer valid.'))).toBe(
      'This device certificate is no longer valid.',
    );
  });

  it('leaves the session sentinel and an HTTP status prefix as they are', () => {
    expect(errMsg(new Error(SESSION_EXPIRED))).toBe(SESSION_EXPIRED);
    expect(errMsg(new Error('HTTP 409: conflict'))).toBe('HTTP 409: conflict');
  });

  it('takes a thrown value that is not an Error as text', () => {
    expect(errMsg('Enrollment am ca-issuer fehlgeschlagen (401)')).toBe(
      'Enrollment am ca-issuer fehlgeschlagen (401)',
    );
    expect(errMsg(42)).toBe('42');
  });
});

describe('errRaw', () => {
  it('keeps the codes for the code that branches on them', () => {
    const raw = `${CHAIN}ERR_CA_PIN_MISMATCH: Server-CA passt nicht`;
    expect(errRaw(new Error(raw))).toBe(raw);
    expect(errRaw(raw)).toBe(raw);
  });
});
