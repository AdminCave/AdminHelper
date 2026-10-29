<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errCode, errRaw, withoutErrorCodes } from '$lib/utils/errors';
  import { get } from 'svelte/store';
  import { login, setAllowSelfSignedCerts, settings } from '$lib/stores/session';
  import { context, openLauncher, reloadContextForUrl } from '$lib/stores/workspace';
  import {
    enrollWithToken,
    resetServerCertPin,
    resetDeviceIdentity,
    type ResetOutcome,
  } from '$lib/bridge';
  import { t } from '$lib/i18n';
  import { takeLoginNotice } from '$lib/utils/loginNotice';
  import { confirmDialog } from './ui/ConfirmDialog.svelte';

  // Pre-fill the server URL + username from the last successful login so only
  // the password has to be entered on each start (a password is required every
  // time the app is opened).
  const remembered = get(settings);

  // The workspace this window serves (R-0431); null only when its context did not load.
  let workspace = $derived($context?.workspace ?? null);
  // Its URL as the window shows it (user, query values and fragment masked). Rust takes it for
  // the URL the workspace keeps, so a sign-in, a registration and a reset send it as shown; the
  // user enters one only while the workspace has none.
  let fixedUrl = $derived(workspace?.url ?? null);

  function targetUrl(): string {
    return fixedUrl ?? serverUrl.trim();
  }

  let mode = $state<'login' | 'enroll'>('login');
  let serverUrl = $state(remembered?.serverUrl ?? '');
  let username = $state(remembered?.lastUsername ?? '');
  let password = $state('');
  let enrollToken = $state('');
  let error = $state('');
  // The code of the refusal behind `error`: the helpers below branch on it, never on the
  // text, which can carry the server's words (R-0709).
  let errorCode = $state<string | undefined>();
  // What a reload that ended the session left to say (session expired, R-0430).
  let info = $state(takeLoginNotice());
  let busy = $state(false);

  // Trust dialog for ERR_TLS_UNKNOWN_ISSUER (error.rs): the standard install
  // serves its own-PKI gateway leaf, so the very first contact fails public-CA
  // validation by design while "allow self-signed certificates" is off — and
  // the settings modal hosting that checkbox is unreachable before login. The
  // dialog offers the opt-in right here and retries the interrupted action.
  let trustPrompt = $state<'login' | 'enroll' | null>(null);
  // The original message, shown inline (code stripped) if the user declines.
  let trustError = $state('');

  function showError(text: string, code?: string): void {
    error = text;
    errorCode = code;
  }

  function switchMode(next: 'login' | 'enroll'): void {
    mode = next;
    showError('');
    info = '';
  }

  // A pinned-certificate / enrolled-CA mismatch (server reinstall or MITM) is a
  // dead end here otherwise: the only reset actions live in the settings modal,
  // which is unreachable until logged in. Detect it and offer the matching reset
  // right on the login screen. Branch on the backend's stable code:
  // ERR_CA_PIN_MISMATCH is the enrolled-CA case (reset device identity),
  // ERR_TOFU_PIN_MISMATCH the self-signed leaf case (reset pin).
  let caPinError = $derived(errorCode === 'ERR_CA_PIN_MISMATCH');
  let pinError = $derived(errorCode === 'ERR_TOFU_PIN_MISMATCH' || caPinError);
  // Under enforced mTLS a device without a certificate is turned away at the
  // gateway before the login (auth.rs, R-0222): name that and offer the token
  // form instead of the raw message.
  let mtlsRequired = $derived(errorCode === 'ERR_MTLS_CERT_REQUIRED');
  // Under mTLS the device certificate belongs to one user (R-0223): signing in as
  // another one is refused. Name that and offer to register the device anew.
  let certUserMismatch = $derived(errorCode === 'ERR_CERT_USER_MISMATCH');
  // A certificate the server no longer admits (R-0224): revoked, or not recorded once
  // the transition is over. The way out is the same, a reset and a new registration.
  let certRevoked = $derived(errorCode === 'ERR_CERT_REVOKED');
  // Never show the machine-readable code to the user; keep only the human text.
  let displayError = $derived(withoutErrorCodes(error));

  async function resetCertTrust(): Promise<void> {
    const target = targetUrl();
    if (!target) {
      showError($t('login.resetPin.missingUrl'));
      return;
    }
    // A pin mismatch is exactly the signature of an active MITM, and this is where
    // it actually surfaces — require the same explicit warning the settings modal
    // does before pinning whatever cert the server currently presents (3.20).
    const ok = await confirmDialog($t('login.resetPin.confirmMitm'), {
      confirmLabel: caPinError ? $t('login.resetDeviceId') : $t('login.resetPin'),
    });
    if (!ok) return;
    busy = true;
    try {
      // The enrolled-CA case must also drop the stale device cert (which is what
      // build_client presents); resetDeviceIdentity clears identity AND pin.
      let outcome: ResetOutcome | undefined;
      if (caPinError) {
        outcome = await resetDeviceIdentity(target);
      } else {
        await resetServerCertPin(target);
      }
      showError('');
      info = resetInfo('login.resetPin.done', outcome);
    } catch (err) {
      showError(errRaw(err), errCode(err));
    } finally {
      busy = false;
    }
  }

  // The message after a reset, with the hint when the server did not revoke it.
  function resetInfo(doneKey: string, outcome: ResetOutcome | undefined): string {
    const done = $t(doneKey);
    return outcome === 'localOnly' ? `${done} ${$t('login.resetDeviceId.localOnly')}` : done;
  }

  // Drops this device's identity so it can be registered anew: for the user who signs
  // in (another user's certificate) or after the server stopped admitting it. No MITM
  // warning as for a pin mismatch: the server is the one the user trusts.
  async function resetIdentity(confirmKey: string, doneKey: string): Promise<void> {
    const target = targetUrl();
    if (!target) {
      showError($t('login.resetPin.missingUrl'));
      return;
    }
    const ok = await confirmDialog($t(confirmKey), { confirmLabel: $t('login.resetDeviceId') });
    if (!ok) return;
    busy = true;
    try {
      const outcome = await resetDeviceIdentity(target);
      showError('');
      info = resetInfo(doneKey, outcome);
    } catch (err) {
      showError(errRaw(err), errCode(err));
    } finally {
      busy = false;
    }
  }

  // The way out of the login screen: the kind of a workspace is fixed, another server or no
  // server at all is another workspace, which the launcher opens.
  function toLauncher(): void {
    showError('');
    info = '';
    openLauncher().catch((err) => {
      showError(errRaw(err), errCode(err));
    });
  }

  async function doLogin(): Promise<void> {
    await login(targetUrl(), username.trim(), password);
    serverUrl = '';
    username = '';
    password = '';
  }

  // Decoupled enrollment (ADR 0003): redeem an admin-issued token to fetch a
  // client cert WITHOUT logging in — the bootstrap path under enforced mTLS.
  // Passes allowSelfSignedCerts through like the login path does — otherwise
  // enrollment from the login screen (the bootstrap path meant for fresh
  // devices) can fail the TLS handshake against a self-signed server even
  // though the user opted in (4.101).
  async function doEnroll(): Promise<void> {
    await enrollWithToken(
      targetUrl(),
      enrollToken.trim(),
      get(settings)?.allowSelfSignedCerts ?? false,
    );
    // A workspace without a URL took the one it registered at: the login shows it from now on.
    await reloadContextForUrl();
    enrollToken = '';
    info = $t('login.enroll.done');
    mode = 'login';
  }

  // An unknown issuer on first contact opens the trust dialog instead of a
  // dead-end error; everything else surfaces inline as before.
  function surfaceError(err: unknown, retry: 'login' | 'enroll'): void {
    const msg = errRaw(err);
    const code = errCode(err);
    if (code === 'ERR_TLS_UNKNOWN_ISSUER') {
      trustError = msg;
      trustPrompt = retry;
    } else {
      showError(msg, code);
    }
  }

  async function handleSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    showError('');
    info = '';
    busy = true;
    try {
      await doLogin();
    } catch (err) {
      surfaceError(err, 'login');
    } finally {
      busy = false;
    }
  }

  async function handleEnroll(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    showError('');
    info = '';
    busy = true;
    try {
      await doEnroll();
    } catch (err) {
      surfaceError(err, 'enroll');
    } finally {
      busy = false;
    }
  }

  // "Trust anyway": persist the opt-in (the TOFU pin replaces public-CA
  // validation from here on — doLogin/doEnroll read the store, so the retry
  // picks it up), then retry what the handshake interrupted.
  async function trustServerCert(): Promise<void> {
    const retry = trustPrompt;
    trustPrompt = null;
    busy = true;
    try {
      await setAllowSelfSignedCerts(true);
      if (retry === 'login') {
        await doLogin();
      } else {
        await doEnroll();
      }
    } catch (err) {
      showError(errRaw(err), errCode(err));
    } finally {
      busy = false;
    }
  }

  function declineServerCert(): void {
    // Keep the full message — displayError strips the machine-readable code.
    showError(trustError, 'ERR_TLS_UNKNOWN_ISSUER');
    trustPrompt = null;
  }
</script>

{#snippet serverUrlField()}
  {#if fixedUrl === null}
    <label class="field">
      <span>{$t('login.serverUrl')}</span>
      <input
        type="url"
        placeholder={$t('login.serverUrl.placeholder')}
        bind:value={serverUrl}
        required
        disabled={busy}
      />
    </label>
  {:else}
    <div class="field">
      <span>{$t('login.serverUrl')}</span>
      <p class="login-url" data-testid="workspace-url">{fixedUrl}</p>
    </div>
  {/if}
{/snippet}

<div class="login-screen">
  <div class="login-card">
    <div class="login-logo" aria-label="AdminHelper Logo">
      <svg width="48" height="48" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true">
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M28 0C12.536 0 0 12.536 0 28v44c0 15.464 12.536 28 28 28h44c15.464 0 28-12.536 28-28V28C100 12.536 87.464 0 72 0H28Zm22 26.5L24.5 52a6 6 0 0 0 8.485 8.485L50 43.97l16.515 16.515A6 6 0 0 0 75 51.999L50 26.5ZM31 66a6 6 0 0 0 0 12h38a6 6 0 0 0 0-12H31Z"
        />
      </svg>
    </div>
    {#if workspace}
      <h2 class="login-workspace">
        {$t('login.signInTo')}
        <span class="workspace-dot" style:background={workspace.color} aria-hidden="true"></span>
        <span class="login-workspace-name">{workspace.name}</span>
      </h2>
    {:else}
      <h2>{$t('login.title')}</h2>
      <p class="login-subtitle">{$t('login.subtitle')}</p>
    {/if}

    {#if info}
      <div class="login-info">{info}</div>
    {/if}

    {#if mode === 'login'}
      <form autocomplete="off" onsubmit={handleSubmit}>
        {@render serverUrlField()}
        <label class="field">
          <span>{$t('login.username')}</span>
          <input type="text" bind:value={username} required disabled={busy} />
        </label>
        <label class="field">
          <span>{$t('login.password')}</span>
          <input type="password" bind:value={password} required disabled={busy} />
        </label>

        {#if mtlsRequired}
          <div class="login-error" data-msg="mtls-required">{$t('login.mtlsRequired')}</div>
          <button
            type="button"
            class="btn ghost login-secondary"
            data-action="mtls-enroll"
            onclick={() => switchMode('enroll')}
            disabled={busy}
          >
            {$t('login.enroll.switch')}
          </button>
        {:else if certUserMismatch}
          <div class="login-error" data-msg="cert-user-mismatch">
            {$t('login.certUserMismatch')}
          </div>
          <button
            type="button"
            class="btn ghost login-secondary"
            data-action="cert-user-reset"
            onclick={() =>
              resetIdentity('login.certUserMismatch.confirm', 'login.certUserMismatch.done')}
            disabled={busy}
          >
            {$t('login.resetDeviceId')}
          </button>
        {:else if certRevoked}
          <div class="login-error" data-msg="cert-revoked">{$t('login.certRevoked')}</div>
          <button
            type="button"
            class="btn ghost login-secondary"
            data-action="cert-revoked-reset"
            onclick={() => resetIdentity('login.certRevoked.confirm', 'login.certRevoked.done')}
            disabled={busy}
          >
            {$t('login.resetDeviceId')}
          </button>
        {:else if error}
          <div class="login-error">{displayError}</div>
          {#if pinError}
            <button
              type="button"
              class="btn ghost login-secondary"
              onclick={resetCertTrust}
              disabled={busy}
            >
              {caPinError ? $t('login.resetDeviceId') : $t('login.resetPin')}
            </button>
          {/if}
        {/if}

        <button type="submit" class="btn accent login-btn" disabled={busy}>
          {busy ? $t('login.signingIn') : $t('login.signIn')}
        </button>
      </form>
      <!-- The mTLS hint carries the same button; one is enough. -->
      {#if !mtlsRequired}
        <button
          type="button"
          class="btn ghost login-secondary"
          data-action="enroll-switch"
          onclick={() => switchMode('enroll')}
          disabled={busy}
        >
          {$t('login.enroll.switch')}
        </button>
      {/if}
      <button
        type="button"
        class="btn ghost login-secondary"
        data-action="open-launcher"
        onclick={toLauncher}
        disabled={busy}
      >
        {$t('workspace.openLauncher')}
      </button>
    {:else}
      <form autocomplete="off" onsubmit={handleEnroll}>
        {@render serverUrlField()}
        <label class="field">
          <span>{$t('login.enroll.token')}</span>
          <input
            type="text"
            placeholder={$t('login.enroll.token.placeholder')}
            bind:value={enrollToken}
            required
            disabled={busy}
          />
        </label>

        {#if error}
          <div class="login-error">{displayError}</div>
          {#if pinError}
            <button
              type="button"
              class="btn ghost login-secondary"
              onclick={resetCertTrust}
              disabled={busy}
            >
              {caPinError ? $t('login.resetDeviceId') : $t('login.resetPin')}
            </button>
          {/if}
        {/if}

        <button type="submit" class="btn accent login-btn" disabled={busy}>
          {busy ? $t('login.enroll.working') : $t('login.enroll.submit')}
        </button>
      </form>
      <button
        type="button"
        class="btn ghost login-secondary"
        data-action="enroll-back"
        onclick={() => switchMode('login')}
        disabled={busy}
      >
        {$t('login.enroll.back')}
      </button>
    {/if}
  </div>
  <!-- Inside .login-screen on purpose: its z-index 300 and opaque background cover any sibling. -->
  {#if trustPrompt}
    <div
      class="trust-overlay"
      role="dialog"
      aria-modal="true"
      data-testid="trust-dialog"
      tabindex="-1"
      onclick={(e) => {
        if (e.target === e.currentTarget) declineServerCert();
      }}
      onkeydown={(e) => {
        if (e.key === 'Escape') declineServerCert();
      }}
    >
      <div class="trust-panel">
        <h3 class="trust-title">{$t('login.trust.title')}</h3>
        <p class="trust-body">{$t('login.trust.body')}</p>
        <div class="trust-actions">
          <button
            type="button"
            class="btn ghost"
            data-action="trust-cancel"
            onclick={declineServerCert}
          >
            {$t('action.cancel')}
          </button>
          <button
            type="button"
            class="btn accent"
            data-action="trust-accept"
            onclick={trustServerCert}
          >
            {$t('login.trust.accept')}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .login-workspace {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--sp-2);
    margin-bottom: var(--sp-5);
  }
  .login-workspace-name {
    overflow-wrap: anywhere;
  }
  /* A value inside .field, whose global rule styles labels: no caps, spacing or
     muted colour — paths and queries are case-sensitive. */
  .login-url {
    margin: 0;
    font-size: var(--text-sm);
    text-transform: none;
    letter-spacing: normal;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .trust-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 60;
    padding: var(--sp-4);
  }
  .trust-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 460px;
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .trust-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .trust-body {
    color: var(--text-muted);
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
  }
  .trust-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--sp-2);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--border);
  }
</style>
