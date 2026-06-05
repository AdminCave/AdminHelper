<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { auth, isAuthenticated } from '$lib/stores/auth';
  import { replace } from '$lib/router';
  import Router from '$lib/components/layout/Router.svelte';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';
  import Toast from '$lib/components/ui/Toast.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import Login from './pages/Login.svelte';
  import { routes } from './routes';

  let hydrated = $state(false);

  onMount(async () => {
    await auth.hydrate();
    hydrated = true;
  });

  $effect(() => {
    if (hydrated && $isAuthenticated && (location.hash === '' || location.hash === '#/')) {
      replace('/connections');
    }
  });
</script>

{#if !hydrated}
  <div class="boot-loader">
    <div class="spinner"></div>
  </div>
{:else if !$isAuthenticated}
  <Login />
{:else}
  <div class="server-layout">
    <Sidebar />
    <main class="main-content">
      <Router {routes} />
    </main>
  </div>
{/if}

<Toast />
<ConfirmDialog />

<style>
  .boot-loader {
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: var(--bg);
  }
  .spinner {
    width: 36px;
    height: 36px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
