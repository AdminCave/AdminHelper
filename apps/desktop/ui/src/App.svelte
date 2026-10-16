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
  import ConfirmDialog from './components/ui/ConfirmDialog.svelte';

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

<!-- The login screen (z-index 300) and the settings overlay cover the dialog's own
     layer (50): lifted here, a question always sits above the screen that asks it. -->
<div class="confirm-layer">
  <ConfirmDialog />
</div>

<style>
  .confirm-layer {
    position: relative;
    z-index: 310;
  }
</style>
