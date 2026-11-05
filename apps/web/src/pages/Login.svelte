<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { auth } from '$lib/stores/auth';
  import { t, toggleLanguage, language } from '$lib/i18n';
  import Button from '$lib/components/ui/Button.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import Panel from '$lib/components/ui/Panel.svelte';

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
    <Panel pad={32}>
      <div class="head">
        <svg class="logo" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true">
          <path
            fill-rule="evenodd"
            clip-rule="evenodd"
            d="M28 0C12.536 0 0 12.536 0 28v44c0 15.464 12.536 28 28 28h44c15.464 0 28-12.536 28-28V28C100 12.536 87.464 0 72 0H28Zm22 26.5L24.5 52a6 6 0 0 0 8.485 8.485L50 43.97l16.515 16.515A6 6 0 0 0 75 51.999L50 26.5ZM31 66a6 6 0 0 0 0 12h38a6 6 0 0 0 0-12H31Z"
          />
        </svg>
        <div class="brand-text">Admin<span class="brand-light">Helper</span></div>
        <Button variant="ghost" size="sm" class="lang" onclick={toggleLanguage}>
          {$language === 'de' ? 'EN' : 'DE'}
        </Button>
      </div>
      <form class="login-form" onsubmit={onSubmit}>
        <FormField label={$t('login.username')} id="loginUser">
          <Input bind:value={username} autocomplete="username" placeholder="admin" required />
        </FormField>
        <FormField label={$t('login.password')} id="loginPass">
          <Input bind:value={password} type="password" autocomplete="current-password" required />
        </FormField>
        {#if error}
          <div class="login-error" role="alert">{error}</div>
        {/if}
        <Button
          type="submit"
          variant="primary"
          fullWidth
          loading={submitting}
          disabled={submitting}
        >
          {$t('login.submit')}
        </Button>
      </form>
    </Panel>
  </div>
</div>

<style>
  .login-page {
    position: fixed;
    inset: 0;
    z-index: 10;
    display: grid;
    place-items: center;
    padding: var(--space-6);
    background: var(--bg);
  }
  .login-card {
    width: min(420px, 100%);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-pop);
  }
  .head {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-bottom: var(--space-6);
  }
  .logo {
    width: 40px;
    height: 40px;
    flex-shrink: 0;
    color: var(--text-strong);
  }
  .brand-text {
    color: var(--text-strong);
    font-size: 21px;
    font-weight: 600;
    letter-spacing: -0.03em;
  }
  .brand-light {
    font-weight: 300;
  }
  .head :global(.lang) {
    margin-left: auto;
  }
  .login-form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .login-error {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--danger-border);
    border-radius: var(--radius-md);
    background: var(--danger-bg);
    color: var(--danger);
    font-size: var(--text-sm);
  }
</style>
