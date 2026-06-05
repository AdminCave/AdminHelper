<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { hydrate, ready, needsLogin } from '$lib/stores/session';
  import { t } from '$lib/i18n';
  import Login from './components/Login.svelte';
  import AppShell from './components/AppShell.svelte';

  onMount(() => {
    hydrate();
  });
</script>

{#if !$ready}
  <div class="app-shell" style="display: flex; align-items: center; justify-content: center;">
    <div style="color: var(--text-muted);">{$t('loading.generic')}</div>
  </div>
{:else if $needsLogin}
  <Login />
{:else}
  <AppShell />
{/if}
