<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { auth } from '$lib/stores/auth';
  import { t, toggleLanguage, language } from '$lib/i18n';
  import { ApiError } from '$lib/api/types';

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
      if (err instanceof ApiError && err.status === 401) {
        error = $t('session.expired');
      } else if (err instanceof Error) {
        error = err.message;
      } else {
        error = 'Login failed';
      }
    } finally {
      submitting = false;
    }
  }
</script>

<div class="login-page">
  <div class="login-card">
    <div class="login-brand">
      <img src="/assets/logo.svg" alt="Logo" class="logo-mark" />
      <div>
        <div class="brand-title">Admin</div>
        <div class="brand-subtitle">Helper</div>
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
