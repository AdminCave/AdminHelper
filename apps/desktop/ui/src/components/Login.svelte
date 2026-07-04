<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { get } from 'svelte/store';
  import { login, setMode, settings } from '$lib/stores/session';
  import { enrollWithToken, resetServerCertPin, resetDeviceIdentity } from '$lib/bridge';
  import { t } from '$lib/i18n';

  let { onBack }: { onBack?: () => void } = $props();

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
  let displayError = $derived(error.replace(/ERR_(?:CA|TOFU)_PIN_MISMATCH:\s*/g, ''));

  async function resetCertTrust(): Promise<void> {
    const target = serverUrl.trim();
    if (!target) {
      error = $t('login.resetPin.missingUrl');
      return;
    }
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

  async function handleSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    info = '';
    busy = true;
    try {
      await login(serverUrl.trim(), username.trim(), password);
      serverUrl = '';
      username = '';
      password = '';
    } catch (err) {
      error = errMsg(err);
    } finally {
      busy = false;
    }
  }

  // Decoupled enrollment (ADR 0003): redeem an admin-issued token to fetch a
  // client cert WITHOUT logging in — the bootstrap path under enforced mTLS.
  async function handleEnroll(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    info = '';
    busy = true;
    try {
      await enrollWithToken(serverUrl.trim(), enrollToken.trim());
      enrollToken = '';
      info = $t('login.enroll.done');
      mode = 'login';
    } catch (err) {
      error = errMsg(err);
    } finally {
      busy = false;
    }
  }
</script>

<div class="login-screen">
  <div class="login-card">
    <div class="login-logo" aria-label="AdminHelper Logo">
      <img src="/logo.svg" alt="AdminHelper" width="48" height="48" />
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
        onclick={() => switchMode('login')}
        disabled={busy}
      >
        {$t('login.enroll.back')}
      </button>
    {/if}

    {#if onBack}
      <button type="button" class="btn ghost login-back" onclick={onBack}>
        {$t('login.back')}
      </button>
    {/if}
  </div>
</div>
