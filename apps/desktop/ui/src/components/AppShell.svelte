<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount, onDestroy, type Component } from 'svelte';
  import ArrowLeftRight from '@lucide/svelte/icons/arrow-left-right';
  import Cable from '@lucide/svelte/icons/cable';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import CircleCheck from '@lucide/svelte/icons/circle-check';
  import Layers from '@lucide/svelte/icons/layers';
  import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
  import Moon from '@lucide/svelte/icons/moon';
  import Search from '@lucide/svelte/icons/search';
  import Server from '@lucide/svelte/icons/server';
  import Settings from '@lucide/svelte/icons/settings';
  import Sun from '@lucide/svelte/icons/sun';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import { getVersion } from '@tauri-apps/api/app';
  import { path as routePath, navigate } from '$lib/router';
  import { session, settings } from '$lib/stores/session';
  import { searchTerm } from '$lib/stores/connections';
  import { markRdpError } from '$lib/stores/connectFlow';
  import { markTerminated, markError, startIfServerMode } from '$lib/stores/tunnel';
  import { context, openLauncher } from '$lib/stores/workspace';
  import { reportError } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import { t, tNow } from '$lib/i18n';
  import { theme, toggleTheme } from '$lib/stores/theme';
  import Dashboard from '../pages/Dashboard.svelte';
  import Connections from '../pages/Connections.svelte';
  import Infrastructure from '../pages/Infrastructure.svelte';
  import Monitoring from '../pages/Monitoring.svelte';
  import Ansible from '../pages/Ansible.svelte';
  import ConnectionEditor from './ConnectionEditor.svelte';
  import PasswordPrompt from './PasswordPrompt.svelte';
  import SettingsModal from './SettingsModal.svelte';
  import StatusBar from './StatusBar.svelte';
  import TunnelIndicator from './TunnelIndicator.svelte';
  import NotificationBell from './NotificationBell.svelte';
  import {
    openSettings,
    logoutAndReload,
    listenForSessionExpiry,
    startSyncTimer,
    stopSyncTimer,
  } from '$lib/stores/settings';
  import {
    activateNotifications,
    deactivateNotifications,
    setNewNotificationHandler,
  } from '$lib/stores/notifications';
  import { notifyOs } from '$lib/osNotify';

  interface NavItem {
    id: 'dashboard' | 'connections' | 'infrastructure' | 'monitoring' | 'ansible';
    labelKey: string;
    href: string;
    icon: Component<{ class?: string }>;
    serverOnly?: boolean;
  }

  const navItems: NavItem[] = [
    {
      id: 'dashboard',
      labelKey: 'nav.dashboard',
      href: '/dashboard',
      icon: LayoutDashboard,
    },
    {
      id: 'connections',
      labelKey: 'nav.connections',
      href: '/connections',
      icon: Cable,
    },
    {
      id: 'infrastructure',
      labelKey: 'nav.infrastructure',
      href: '/infrastructure',
      icon: Server,
      serverOnly: true,
    },
    {
      id: 'monitoring',
      labelKey: 'nav.monitoring',
      href: '/monitoring',
      icon: CircleCheck,
      serverOnly: true,
    },
    {
      id: 'ansible',
      labelKey: 'nav.ansible',
      href: '/ansible',
      icon: Layers,
      serverOnly: true,
    },
  ];

  let isServerMode = $derived($settings?.mode === 'server' && $session !== null);
  let visibleNav = $derived(navItems.filter((n) => !n.serverOnly || isServerMode));
  let collapsed = $state(false);

  let routeId = $derived.by<NavItem['id']>(() => {
    const p = $routePath;
    if (p.startsWith('/connections')) return 'connections';
    if (p.startsWith('/infrastructure')) return 'infrastructure';
    if (p.startsWith('/monitoring')) return 'monitoring';
    if (p.startsWith('/ansible')) return 'ansible';
    return 'dashboard';
  });
  // A server-only page has nothing to show without a server session, in a local or a sync
  // workspace: its route shows the dashboard instead.
  let currentId = $derived(visibleNav.some((n) => n.id === routeId) ? routeId : 'dashboard');

  let title = $derived($t(navItems.find((n) => n.id === currentId)?.labelKey ?? 'nav.dashboard'));
  // The workspace this window serves (R-0431); null only when its context did not load.
  let workspace = $derived($context?.workspace ?? null);

  function toLauncher(): void {
    openLauncher().catch((err) => reportError(errMsg(err)));
  }

  // Poll the notification feed app-wide while a server session is active. The
  // effect re-runs when the server or the user changes; cleanup stops the timer and resets state.
  // Keyed on both, not on the session object: `session` re-emits an equal object on every
  // settings save (refreshSettings), and a restart there would empty the feed and drop the OS
  // notifications of entries arriving in the gap (R-0663). The string key compares by value.
  let notificationKey = $derived(
    $session ? JSON.stringify([$session.serverUrl, $session.username]) : null,
  );
  $effect(() => {
    if (notificationKey) {
      void activateNotifications();
    }
    return () => deactivateNotifications();
  });

  // Route new feed entries to OS notifications only while the user opted in.
  $effect(() => {
    setNewNotificationHandler($settings?.osNotifications ? notifyOs : null);
  });

  function go(item: NavItem): void {
    navigate(item.href);
  }

  function toggleCollapse(): void {
    collapsed = !collapsed;
  }

  const unlisteners: UnlistenFn[] = [];
  // If AppShell is destroyed (logout → login screen) before the async listen() calls below
  // resolve, onDestroy has already iterated the still-empty unlisteners array; the late-resolving
  // handlers would then never be removed and accumulate across login/logout cycles (4.100).
  let destroyed = false;

  // Read the real app version from tauri.conf.json at runtime (the CI-checked pin)
  // instead of a hand-maintained string that silently drifts (audit 2.17).
  let appVersion = $state('');

  onMount(async () => {
    getVersion()
      .then((v) => (appVersion = v))
      .catch(() => {});
    if (isServerMode) {
      void startIfServerMode();
    }
    if ($settings?.mode === 'sync') {
      startSyncTimer();
    }
    try {
      const fns = await Promise.all([
        listen('frpc-terminated', () => markTerminated()),
        listen<string>('frpc-error', (e) => markError(String(e.payload ?? 'frpc error'))),
        listen<string | { correlationId?: string; message?: string }>('rdp-error', (e) => {
          const payload = e.payload;
          if (typeof payload === 'string' || payload == null) {
            markRdpError(null, String(payload ?? tNow('error.rdpAuth')));
          } else {
            markRdpError(payload.correlationId ?? null, payload.message ?? tNow('error.rdpAuth'));
          }
        }),
        listenForSessionExpiry(),
      ]);
      // Destroyed while awaiting? Unregister immediately instead of leaking the handlers (4.100).
      if (destroyed) {
        fns.forEach((fn) => fn());
        return;
      }
      unlisteners.push(...fns);
    } catch (err) {
      console.warn('Tauri-Event-Listener konnten nicht registriert werden', err);
    }
  });

  onDestroy(() => {
    destroyed = true;
    stopSyncTimer();
    unlisteners.forEach((fn) => {
      try {
        fn();
      } catch {
        /* ignore */
      }
    });
  });
</script>

<div
  class="app-shell"
  class:sidebar-collapsed={collapsed}
  class:workspace-stripe={workspace !== null}
  style:--workspace-color={workspace?.color}
>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="sidebar-logo">
        <svg width="36" height="36" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true">
          <path
            fill-rule="evenodd"
            clip-rule="evenodd"
            d="M28 0C12.536 0 0 12.536 0 28v44c0 15.464 12.536 28 28 28h44c15.464 0 28-12.536 28-28V28C100 12.536 87.464 0 72 0H28Zm22 26.5L24.5 52a6 6 0 0 0 8.485 8.485L50 43.97l16.515 16.515A6 6 0 0 0 75 51.999L50 26.5ZM31 66a6 6 0 0 0 0 12h38a6 6 0 0 0 0-12H31Z"
          />
        </svg>
      </div>
      <div class="sidebar-brand-text">
        <div class="sidebar-title" style="font-weight:600">Admin</div>
        <div class="sidebar-subtitle" style="font-weight:300">Helper</div>
      </div>
    </div>

    {#if workspace}
      <!-- The title names the workspace too: the collapsed sidebar shows only the dot. -->
      <button
        class="workspace-chip"
        onclick={toLauncher}
        title={$t('workspace.chip.title', { name: workspace.name })}
      >
        <span class="workspace-dot" style:background={workspace.color}></span>
        <span class="workspace-chip-name">{workspace.name}</span>
      </button>
    {/if}

    <nav class="sidebar-nav">
      {#each visibleNav as item (item.id)}
        <button
          class="sidebar-item"
          class:active={currentId === item.id}
          data-nav={item.id}
          onclick={() => go(item)}
          title={$t(item.labelKey)}
        >
          <item.icon class="sidebar-icon" />
          <span class="sidebar-label">{$t(item.labelKey)}</span>
        </button>
      {/each}
    </nav>

    <div class="sidebar-spacer"></div>

    <TunnelIndicator />

    <div class="sidebar-bottom">
      <button class="sidebar-item" onclick={openSettings} title={$t('settings.label')}>
        <Settings class="sidebar-icon" />
        <span class="sidebar-label">{$t('settings.label')}</span>
      </button>
      <!-- After the settings and without an aria-label: the live specs take the first item here
           for the settings and the one with an aria-label for the theme toggle. -->
      <button class="sidebar-item" onclick={toLauncher} title={$t('workspace.openLauncher')}>
        <ArrowLeftRight class="sidebar-icon" />
        <span class="sidebar-label">{$t('workspace.openLauncher')}</span>
      </button>
      <button
        class="sidebar-item"
        onclick={toggleTheme}
        title={$t('theme.toggle')}
        aria-label={$t('theme.toggle')}
      >
        {#if $theme === 'dark'}
          <Moon class="sidebar-icon" />
        {:else}
          <Sun class="sidebar-icon" />
        {/if}
        <span class="sidebar-label">{$t('theme.toggle')}</span>
      </button>
      <div class="sidebar-version">v{appVersion}</div>
    </div>

    <button
      class="sidebar-collapse-btn"
      onclick={toggleCollapse}
      aria-label={collapsed ? $t('sidebar.expand') : $t('sidebar.collapse')}
    >
      <ChevronLeft size={16} />
    </button>
  </aside>

  <header class="content-header">
    <div class="content-header-left">
      <h1 class="page-title">{title}</h1>
    </div>
    <div class="content-header-right">
      {#if currentId === 'connections'}
        <label class="search-box">
          <Search class="search-icon" size={16} />
          <input type="search" placeholder={$t('search.placeholder')} bind:value={$searchTerm} />
        </label>
      {/if}
      {#if $session}
        <NotificationBell />
        <span style="color: var(--text-muted); margin: 0 var(--sp-3);">
          {$session.username}
        </span>
        <button class="btn ghost small" onclick={() => logoutAndReload()}>{$t('nav.logout')}</button
        >
      {/if}
    </div>
  </header>

  <main class="content-main">
    <section class="content-section">
      {#if currentId === 'dashboard'}
        <Dashboard />
      {:else if currentId === 'connections'}
        <Connections />
      {:else if currentId === 'infrastructure'}
        <Infrastructure />
      {:else if currentId === 'monitoring'}
        <Monitoring />
      {:else if currentId === 'ansible'}
        <Ansible />
      {/if}
    </section>
  </main>
</div>

<ConnectionEditor />
<PasswordPrompt />
<SettingsModal />
<StatusBar />
