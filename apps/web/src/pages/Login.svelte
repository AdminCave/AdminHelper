<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { auth } from '$lib/stores/auth';
  import { t, toggleLanguage, language } from '$lib/i18n';

  let username = $state('');
  let password = $state('');
  let error = $state('');
  let submitting = $state(false);

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    error = '';
    submitting = true;
    try {
      await auth.login(username, password);
    } catch (err) {
      if (err instanceof Error) {
        // A login 401 carries the server's credential message (the /auth/ path
        // skips the refresh-retry branch in client.ts), not a session expiry.
        error = err.message;
      } else {
        error = $t('login.failed');
      }
    } finally {
      submitting = false;
    }
  }
</script>

<div class="login-page">
  <div class="login-card">
    <div class="login-brand">
      <svg class="logo-mark" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true">
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M28 0C12.536 0 0 12.536 0 28v44c0 15.464 12.536 28 28 28h44c15.464 0 28-12.536 28-28V28C100 12.536 87.464 0 72 0H28Zm22 26.5L24.5 52a6 6 0 0 0 8.485 8.485L50 43.97l16.515 16.515A6 6 0 0 0 75 51.999L50 26.5ZM31 66a6 6 0 0 0 0 12h38a6 6 0 0 0 0-12H31Z"
        />
      </svg>
      <div>
        <div class="brand-title" style="font-weight:600">Admin</div>
        <div class="brand-subtitle" style="font-weight:300">Helper</div>
      </div>
      <button
        class="btn small ghost"
        style="margin-left:auto;width:40px;font-weight:600"
        onclick={toggleLanguage}
        type="button"
      >
        {$language === 'de' ? 'EN' : 'DE'}
      </button>
    </div>
    <form class="login-form" onsubmit={onSubmit}>
      <div class="field">
        <label for="loginUser">{$t('login.username')}</label>
        <input
          id="loginUser"
          type="text"
          autocomplete="username"
          required
          placeholder="admin"
          bind:value={username}
        />
      </div>
      <div class="field">
        <label for="loginPass">{$t('login.password')}</label>
        <input
          id="loginPass"
          type="password"
          autocomplete="current-password"
          required
          bind:value={password}
        />
      </div>
      {#if error}
        <div class="login-error show">{error}</div>
      {/if}
      <button type="submit" class="btn primary" disabled={submitting}>
        {$t('login.submit')}
      </button>
    </form>
  </div>
</div>
