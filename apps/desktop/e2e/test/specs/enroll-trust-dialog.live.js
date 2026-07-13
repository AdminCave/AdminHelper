// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E: the first-contact trust dialog (ERR_TLS_UNKNOWN_ISSUER). A fresh
// device with DEFAULT settings (allowSelfSignedCerts=false — seeded that way by
// the orchestrator for this spec only) contacts the standard install's own-PKI
// gateway: the enroll submit must NOT dead-end in a raw TLS error but open the
// trust dialog. Accepting persists the opt-in (the app writes settings.json —
// asserted by the orchestrator afterwards) and retries the enrollment; that the
// retry now PASSES the transport is proven by the next failure being the
// server-side rejection of the bogus token, not the unknown-issuer error. The
// decline path and persist-before-retry ordering are covered by the Vitest
// component tests (Login.trust.test.ts). Run by scripts/tests/desktop_e2e_crud.sh.

import { SERVER_URL, jsClick } from '../lib/live.js';

describe('AdminHelper desktop — first-contact trust dialog', () => {
  it('opens the trust dialog instead of a dead-end TLS error', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });
    await $('[data-action="enroll-switch"]').click();
    await $('.login-card input[type="url"]').waitForExist({ timeout: 10000 });
    await $('.login-card input[type="url"]').setValue(SERVER_URL);
    await $('.login-card input[type="text"]').setValue('adminhelper_prov_not-a-real-token');
    await $('.login-card button[type="submit"]').click();

    await $('[data-testid="trust-dialog"]').waitForExist({ timeout: 20000 });
    // The dialog replaces the inline error box — no dead end, no raw TLS code.
    if (await $('.login-card .login-error').isExisting()) {
      throw new Error('inline error shown although the trust dialog should have replaced it');
    }
  });

  it('accepting trusts the server (TOFU) and retries through the TLS layer', async () => {
    // jsClick: the WebDriver hit-test rejects the coordinate click on the
    // modal's action row (same interception the editor modals hit, see live.js).
    await jsClick(await $('[data-action="trust-accept"]'));
    await $('[data-testid="trust-dialog"]').waitForExist({ reverse: true, timeout: 20000 });

    // The retry passes the transport now: the next failure must be the
    // server-side token rejection, not the unknown-issuer TLS error.
    const err = await $('.login-card .login-error');
    await err.waitForExist({ timeout: 20000 });
    await browser.waitUntil(async () => (await err.getText()).trim().length > 0, {
      timeout: 20000,
      timeoutMsg: 'no server-side rejection surfaced after accepting the trust dialog',
    });
    const text = await err.getText();
    if (text.includes('ERR_TLS_UNKNOWN_ISSUER') || text.includes('vertrauenswürdigen CA')) {
      throw new Error(`retry still failed at the TLS layer: ${text}`);
    }
  });
});
