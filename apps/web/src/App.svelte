<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import type { User } from '$lib/api/types';
  import { auth, currentUser, isAuthenticated } from '$lib/stores/auth';
  import { showToast } from '$lib/stores/notifications';
  import { tNow } from '$lib/i18n';
  import { watchIdle } from '$lib/idle';
  import { replace } from '$lib/router';
  import Router from '$lib/components/layout/Router.svelte';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';
  import Toast from '$lib/components/ui/Toast.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import Login from './pages/Login.svelte';
  import { routes } from './routes';

  let hydrated = $state(false);
  // The user auth.hydrate() brought back from the refresh cookie. A login sets a new object, so
  // only the session of the page load compares equal, also after a sign-out and login in this tab.
  let restoredUser: User | null = null;

  onMount(async () => {
    await auth.hydrate();
    restoredUser = get(currentUser);
    hydrated = true;
  });

  $effect(() => {
    if (hydrated && $isAuthenticated && (location.hash === '' || location.hash === '#/')) {
      replace('/users');
    }
  });

  // One watch per session: signing out, or in as another user, stops it.
  $effect(() => {
    // Not before restoredUser is known: a watch started for the restored session as a fresh one
    // would overwrite the stored time of the last activity before it was read.
    if (!hydrated) return;
    const user = $currentUser;
    const minutes = user?.idle_timeout_minutes;
    return watchIdle(
      minutes,
      () => {
        void auth.logout();
        // 0 keeps the notice until it is closed: nobody is at the screen when it appears.
        showToast(tNow('toast.session.idle', { minutes }), 'info', 0);
      },
      { restored: user !== null && user === restoredUser },
    );
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
