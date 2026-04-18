<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import { path, navigate } from '$lib/router';
  import { session, settings, logout } from '$lib/stores/session';
  import { searchTerm } from '$lib/stores/connections';
  import { markRdpError } from '$lib/stores/connectFlow';
  import { markTerminated, markError, startIfServerMode } from '$lib/stores/tunnel';
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
    label: string;
    href: string;
    serverOnly?: boolean;
  }

  const navItems: NavItem[] = [
    { id: 'dashboard', label: 'Dashboard', href: '/dashboard' },
    { id: 'connections', label: 'Verbindungen', href: '/connections' },
    { id: 'monitoring', label: 'Monitoring', href: '/monitoring', serverOnly: true },
    { id: 'ansible', label: 'Ansible', href: '/ansible', serverOnly: true },
  ];

  let isServerMode = $derived($settings?.mode === 'server' && $session !== null);
  let visibleNav = $derived(navItems.filter((n) => !n.serverOnly || isServerMode));

  let currentId = $derived.by<NavItem['id']>(() => {
    const p = $path;
    if (p.startsWith('/connections')) return 'connections';
    if (p.startsWith('/monitoring')) return 'monitoring';
    if (p.startsWith('/ansible')) return 'ansible';
    return 'dashboard';
  });

  let title = $derived(navItems.find((n) => n.id === currentId)?.label ?? 'Dashboard');

  function go(item: NavItem): void {
    navigate(item.href);
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
        await listen<string>('rdp-error', (e) =>
          markRdpError(String(e.payload ?? 'RDP-Authentifizierung fehlgeschlagen')),
        ),
      );
    } catch (err) {
      console.warn('Tauri-Event-Listener konnten nicht registriert werden', err);
    }
  });

  onDestroy(() => {
    stopSyncTimer();
    unlisteners.forEach((fn) => {
      try { fn(); } catch { /* ignore */ }
    });
  });
</script>

<div class="app-shell">
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
        >
          <span class="sidebar-label">{item.label}</span>
        </button>
      {/each}
    </nav>

    <div class="sidebar-spacer"></div>

    <TunnelIndicator />

    <div class="sidebar-bottom">
      <div class="sidebar-version">v0.18.0-dev</div>
    </div>
  </aside>

  <header class="content-header">
    <div class="content-header-left">
      <h1 class="page-title">{title}</h1>
    </div>
    <div class="content-header-right">
      {#if currentId === 'connections'}
        <label class="search-box">
          <input
            type="search"
            placeholder="Name, Host, URL"
            bind:value={$searchTerm}
          />
        </label>
      {/if}
      {#if $session}
        <span style="color: var(--text-muted); margin: 0 var(--sp-3);">
          {$session.username}
        </span>
        <button class="btn ghost small" onclick={() => logout()}>Abmelden</button>
      {:else if $settings}
        <span style="color: var(--text-muted);">Modus: {$settings.mode}</span>
      {/if}
      <button class="btn ghost small" onclick={openSettings} title="Einstellungen">⚙</button>
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
