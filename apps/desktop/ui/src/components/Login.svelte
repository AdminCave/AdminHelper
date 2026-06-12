<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { login } from '$lib/stores/session';
  import { enrollWithToken } from '$lib/bridge';
  import { t } from '$lib/i18n';

  let { onBack }: { onBack?: () => void } = $props();

  let mode = $state<'login' | 'enroll'>('login');
  let serverUrl = $state('');
  let username = $state('');
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
      error = err instanceof Error ? err.message : String(err);
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
      error = err instanceof Error ? err.message : String(err);
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
          <div class="login-error">{error}</div>
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
          <div class="login-error">{error}</div>
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
