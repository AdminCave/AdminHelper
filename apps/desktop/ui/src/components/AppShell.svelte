<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import { path as routePath, navigate } from '$lib/router';
  import { session, settings, logout } from '$lib/stores/session';
  import { searchTerm } from '$lib/stores/connections';
  import { markRdpError } from '$lib/stores/connectFlow';
  import { markTerminated, markError, startIfServerMode } from '$lib/stores/tunnel';
  import { t, tNow } from '$lib/i18n';
  import Dashboard from '../pages/Dashboard.svelte';
  import Connections from '../pages/Connections.svelte';
  import Monitoring from '../pages/Monitoring.svelte';
  import Ansible from '../pages/Ansible.svelte';
  import ConnectionEditor from './ConnectionEditor.svelte';
  import PasswordPrompt from './PasswordPrompt.svelte';
  import SettingsModal from './SettingsModal.svelte';
  import StatusBar from './StatusBar.svelte';
  import TunnelIndicator from './TunnelIndicator.svelte';
  import { openSettings, startSyncTimer, stopSyncTimer } from '$lib/stores/settings';

  interface NavItem {
    id: 'dashboard' | 'connections' | 'monitoring' | 'ansible';
    labelKey: string;
    href: string;
    icon: string;
    serverOnly?: boolean;
  }

  const navItems: NavItem[] = [
    {
      id: 'dashboard',
      labelKey: 'nav.dashboard',
      href: '/dashboard',
      icon: 'M4 13h6a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1zm0 8h6a1 1 0 0 0 1-1v-4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v4a1 1 0 0 0 1 1zm10 0h6a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1zm0-18v4a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1z',
    },
    {
      id: 'connections',
      labelKey: 'nav.connections',
      href: '/connections',
      icon: 'M21 2H3a1 1 0 0 0-1 1v18a1 1 0 0 0 1 1h18a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1zm-1 18H4V4h16v16zM7 7h2v2H7V7zm0 4h2v2H7v-2zm0 4h2v2H7v-2zm4-8h6v2h-6V7zm0 4h6v2h-6v-2zm0 4h6v2h-6v-2z',
    },
    {
      id: 'monitoring',
      labelKey: 'nav.monitoring',
      href: '/monitoring',
      icon: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z',
      serverOnly: true,
    },
    {
      id: 'ansible',
      labelKey: 'nav.ansible',
      href: '/ansible',
      icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
      serverOnly: true,
    },
  ];

  let isServerMode = $derived($settings?.mode === 'server' && $session !== null);
  let visibleNav = $derived(navItems.filter((n) => !n.serverOnly || isServerMode));
  let collapsed = $state(false);

  let currentId = $derived.by<NavItem['id']>(() => {
    const p = $routePath;
    if (p.startsWith('/connections')) return 'connections';
    if (p.startsWith('/monitoring')) return 'monitoring';
    if (p.startsWith('/ansible')) return 'ansible';
    return 'dashboard';
  });

  let title = $derived($t(navItems.find((n) => n.id === currentId)?.labelKey ?? 'nav.dashboard'));
  let modeBadge = $derived($t(`settings.mode.${$settings?.mode ?? 'local'}`));

  function go(item: NavItem): void {
    navigate(item.href);
  }

  function toggleCollapse(): void {
    collapsed = !collapsed;
  }

  const unlisteners: UnlistenFn[] = [];

  onMount(async () => {
    if (isServerMode) {
      void startIfServerMode();
    }
    if ($settings?.mode === 'sync') {
      startSyncTimer();
    }
    try {
      unlisteners.push(
        await listen('frpc-terminated', () => markTerminated()),
        await listen<string>('frpc-error', (e) => markError(String(e.payload ?? 'frpc error'))),
        await listen<string | { correlationId?: string; message?: string }>('rdp-error', (e) => {
          const payload = e.payload;
          if (typeof payload === 'string' || payload == null) {
            markRdpError(null, String(payload ?? tNow('error.rdpAuth')));
          } else {
            markRdpError(payload.correlationId ?? null, payload.message ?? tNow('error.rdpAuth'));
          }
        }),
      );
    } catch (err) {
      console.warn('Tauri-Event-Listener konnten nicht registriert werden', err);
    }
  });

  onDestroy(() => {
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

<div class="app-shell" class:sidebar-collapsed={collapsed}>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="sidebar-logo">
        <img src="/logo.svg" alt="AdminHelper" width="36" height="36" />
      </div>
      <div class="sidebar-brand-text">
        <div class="sidebar-title">Admin</div>
        <div class="sidebar-subtitle">Helper</div>
      </div>
    </div>

    <nav class="sidebar-nav">
      {#each visibleNav as item (item.id)}
        <button
          class="sidebar-item"
          class:active={currentId === item.id}
          onclick={() => go(item)}
          title={$t(item.labelKey)}
        >
          <svg class="sidebar-icon" viewBox="0 0 24 24"><path d={item.icon} /></svg>
          <span class="sidebar-label">{$t(item.labelKey)}</span>
        </button>
      {/each}
    </nav>

    <div class="sidebar-spacer"></div>

    <TunnelIndicator />

    <div class="sidebar-bottom">
      <button class="sidebar-item" onclick={openSettings} title={$t('settings.label')}>
        <svg class="sidebar-icon" viewBox="0 0 24 24">
          <path
            d="M12 8.75a3.25 3.25 0 1 0 0 6.5 3.25 3.25 0 0 0 0-6.5Zm8.25 3.25c0-.46-.04-.9-.11-1.34l2.01-1.57-1.8-3.12-2.45.99a7.9 7.9 0 0 0-2.32-1.34l-.37-2.6H9.79l-.37 2.6a7.9 7.9 0 0 0-2.32 1.34l-2.45-.99-1.8 3.12 2.01 1.57c-.07.44-.11.88-.11 1.34 0 .46.04.9.11 1.34l-2.01 1.57 1.8 3.12 2.45-.99c.69.57 1.48 1 2.32 1.34l.37 2.6h4.42l.37-2.6c.84-.34 1.63-.77 2.32-1.34l2.45.99 1.8-3.12-2.01-1.57c.07-.44.11-.88.11-1.34Z"
          />
        </svg>
        <span class="sidebar-label">{$t('settings.label')}</span>
        <span class="sidebar-badge">{modeBadge}</span>
      </button>
      <div class="sidebar-version">v0.24.0</div>
    </div>

    <button
      class="sidebar-collapse-btn"
      onclick={toggleCollapse}
      aria-label={collapsed ? $t('sidebar.expand') : $t('sidebar.collapse')}
    >
      <svg viewBox="0 0 24 24" width="16" height="16">
        <path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z" />
      </svg>
    </button>
  </aside>

  <header class="content-header">
    <div class="content-header-left">
      <h1 class="page-title">{title}</h1>
    </div>
    <div class="content-header-right">
      {#if currentId === 'connections'}
        <label class="search-box">
          <svg class="search-icon" viewBox="0 0 24 24" width="16" height="16">
            <path
              d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"
            />
          </svg>
          <input type="search" placeholder={$t('search.placeholder')} bind:value={$searchTerm} />
        </label>
      {/if}
      {#if $session}
        <span style="color: var(--text-muted); margin: 0 var(--sp-3);">
          {$session.username}
        </span>
        <button class="btn ghost small" onclick={() => logout()}>{$t('nav.logout')}</button>
      {/if}
    </div>
  </header>

  <main class="content-main">
    <section class="content-section">
      {#if currentId === 'dashboard'}
        <Dashboard />
      {:else if currentId === 'connections'}
        <Connections />
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
