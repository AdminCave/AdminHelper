<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { get } from 'svelte/store';
  import { login, setAllowSelfSignedCerts, setMode, settings } from '$lib/stores/session';
  import { enrollWithToken, resetServerCertPin, resetDeviceIdentity } from '$lib/bridge';
  import { t } from '$lib/i18n';
  import { confirm } from '@tauri-apps/plugin-dialog';

  // Pre-fill the server URL + username from the last successful login so only
  // the password has to be entered on each start (a password is required every
  // time the app is opened).
  const remembered = get(settings);

  let mode = $state<'login' | 'enroll'>('login');
  let serverUrl = $state(remembered?.serverUrl ?? '');
  let username = $state(remembered?.lastUsername ?? '');
  let password = $state('');
  let enrollToken = $state('');
  let error = $state('');
  let info = $state('');
  let busy = $state(false);

  // Trust dialog for ERR_TLS_UNKNOWN_ISSUER (error.rs): the standard install
  // serves its own-PKI gateway leaf, so the very first contact fails public-CA
  // validation by design while "allow self-signed certificates" is off — and
  // the settings modal hosting that checkbox is unreachable before login. The
  // dialog offers the opt-in right here and retries the interrupted action.
  let trustPrompt = $state<'login' | 'enroll' | null>(null);
  // The original message, shown inline (code stripped) if the user declines.
  let trustError = $state('');

  function switchMode(next: 'login' | 'enroll'): void {
    mode = next;
    error = '';
    info = '';
  }

  // A pinned-certificate / enrolled-CA mismatch (server reinstall or MITM) is a
  // dead end here otherwise: the only reset actions live in the settings modal,
  // which is unreachable until logged in. Detect it and offer the matching reset
  // right on the login screen. Match the backend's stable, language-independent
  // error codes (not its German prose, which is free to change / be localized):
  // ERR_CA_PIN_MISMATCH is the enrolled-CA case (reset device identity),
  // ERR_TOFU_PIN_MISMATCH the self-signed leaf case (reset pin). The codes arrive
  // buried in the reqwest source chain, so match them anywhere in the string.
  let caPinError = $derived(error.includes('ERR_CA_PIN_MISMATCH'));
  let pinError = $derived(error.includes('ERR_TOFU_PIN_MISMATCH') || caPinError);
  // Never show the machine-readable code to the user; keep only the human text.
  let displayError = $derived(
    error.replace(/ERR_(?:(?:CA|TOFU)_PIN_MISMATCH|TLS_UNKNOWN_ISSUER):\s*/g, ''),
  );

  async function resetCertTrust(): Promise<void> {
    const target = serverUrl.trim();
    if (!target) {
      error = $t('login.resetPin.missingUrl');
      return;
    }
    // A pin mismatch is exactly the signature of an active MITM, and this is where
    // it actually surfaces — require the same explicit warning the settings modal
    // does before pinning whatever cert the server currently presents (3.20).
    const ok = await confirm($t('login.resetPin.confirmMitm'), {
      title: caPinError ? $t('login.resetDeviceId') : $t('login.resetPin'),
      kind: 'warning',
    });
    if (!ok) return;
    busy = true;
    try {
      // The enrolled-CA case must also drop the stale device cert (which is what
      // build_client presents); resetDeviceIdentity clears identity AND pin.
      if (caPinError) {
        await resetDeviceIdentity(target);
      } else {
        await resetServerCertPin(target);
      }
      error = '';
      info = $t('login.resetPin.done');
    } catch (err) {
      error = errMsg(err);
    } finally {
      busy = false;
    }
  }

  // Escape hatch: use the client purely locally (connections only, no server,
  // no auth). Without this the login screen is a dead end once the app is in
  // server mode — the mode switch otherwise lives only inside the app shell.
  async function useLocal(): Promise<void> {
    error = '';
    info = '';
    busy = true;
    try {
      await setMode('local');
    } catch (err) {
      error = errMsg(err);
    } finally {
      busy = false;
    }
  }

  async function doLogin(): Promise<void> {
    await login(serverUrl.trim(), username.trim(), password);
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
      serverUrl.trim(),
      enrollToken.trim(),
      get(settings)?.allowSelfSignedCerts ?? false,
    );
    enrollToken = '';
    info = $t('login.enroll.done');
    mode = 'login';
  }

  // An unknown issuer on first contact opens the trust dialog instead of a
  // dead-end error; everything else surfaces inline as before.
  function surfaceError(err: unknown, retry: 'login' | 'enroll'): void {
    const msg = errMsg(err);
    if (msg.includes('ERR_TLS_UNKNOWN_ISSUER')) {
      trustError = msg;
      trustPrompt = retry;
    } else {
      error = msg;
    }
  }

  async function handleSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
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
    error = '';
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
      error = errMsg(err);
    } finally {
      busy = false;
    }
  }

  function declineServerCert(): void {
    // Keep the full message — displayError strips the machine-readable code.
    error = trustError;
    trustPrompt = null;
  }
</script>

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
    <h2>{$t('login.title')}</h2>
    <p class="login-subtitle">{$t('login.subtitle')}</p>

    {#if info}
      <div class="login-info">{info}</div>
    {/if}

    {#if mode === 'login'}
      <form autocomplete="off" onsubmit={handleSubmit}>
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
        <label class="field">
          <span>{$t('login.username')}</span>
          <input type="text" bind:value={username} required disabled={busy} />
        </label>
        <label class="field">
          <span>{$t('login.password')}</span>
          <input type="password" bind:value={password} required disabled={busy} />
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
          {busy ? $t('login.signingIn') : $t('login.signIn')}
        </button>
      </form>
      <button
        type="button"
        class="btn ghost login-secondary"
        data-action="enroll-switch"
        onclick={() => switchMode('enroll')}
        disabled={busy}
      >
        {$t('login.enroll.switch')}
      </button>
      <button type="button" class="btn ghost login-secondary" onclick={useLocal} disabled={busy}>
        {$t('login.useLocal')}
      </button>
    {:else}
      <form autocomplete="off" onsubmit={handleEnroll}>
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
</div>

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

<style>
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
