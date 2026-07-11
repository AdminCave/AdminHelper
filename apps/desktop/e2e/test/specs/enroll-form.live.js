// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E: the decoupled-enrollment (ADR 0003) login-screen journey. A brand-new
// device redeems an admin-minted token to obtain its own mTLS cert WITHOUT a prior
// login — the bootstrap path under enforced mTLS. This spec locks down the FORM
// itself against a REAL server: switch into enroll mode, submit a token, and — for
// an invalid token — see an error surfaced (not a silent no-op). The orchestrator
// seeds allowSelfSignedCerts=true, so the self-signed TLS handshake to the enroll
// plane on :8444 succeeds and the bogus token is rejected server-side rather than
// the request dying at the transport (the assertion only checks that *some* error
// is shown — matching login-error.live.js — since the failure is deterministic
// either way). The happy path (a consumable one-time token that mints a real cert)
// belongs to the full enrollment suite. Run by scripts/tests/desktop_e2e_crud.sh
// (and reachable ad hoc via scripts/tests/crabbox_desktopbox.sh <spec>).

import { SERVER_URL } from '../lib/live.js';

describe('AdminHelper desktop — decoupled enrollment form', () => {
  it('switches from the login form to the enroll-token form', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });
    // By stable action id, not a positional index: the three secondary buttons
    // (enroll / use-local / back) are otherwise indistinguishable structurally.
    await $('[data-action="enroll-switch"]').click();
    // The enroll form replaces the login form: a server-URL field + a token field.
    await $('.login-card input[type="url"]').waitForExist({ timeout: 10000 });
    await $('.login-card input[type="text"]').waitForExist({ timeout: 10000 });
    // A url+text pair also exists in login mode (serverUrl + username), so the
    // switch is only proven by the password field being gone.
    await $('.login-card input[type="password"]').waitForExist({ reverse: true, timeout: 10000 });
  });

  it('surfaces the server rejection for an invalid token', async () => {
    await $('.login-card input[type="url"]').setValue(SERVER_URL);
    await $('.login-card input[type="text"]').setValue('adminhelper_prov_not-a-real-token');
    await $('.login-card button[type="submit"]').click();
    // The rejection is rendered in the login-error box and is non-empty.
    const err = await $('.login-card .login-error');
    await err.waitForExist({ timeout: 20000 });
    await browser.waitUntil(async () => (await err.getText()).trim().length > 0, {
      timeout: 20000,
      timeoutMsg: 'the enroll error box stayed empty for an invalid token',
    });
  });

  it('switches back to the login form', async () => {
    await $('[data-action="enroll-back"]').click();
    await $('.login-card input[type="password"]').waitForExist({ timeout: 10000 });
  });
});
