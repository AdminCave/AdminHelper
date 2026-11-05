<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount, onDestroy, type Component } from 'svelte';
  import { get } from 'svelte/store';
  import ArrowLeftRight from '@lucide/svelte/icons/arrow-left-right';
  import Cable from '@lucide/svelte/icons/cable';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronsUpDown from '@lucide/svelte/icons/chevrons-up-down';
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
  import { connections } from '$lib/stores/connections';
  import { initiateConnect, markRdpError } from '$lib/stores/connectFlow';
  import { openEditor } from '$lib/stores/editor';
  import { buildEntries } from '$lib/palette';
  import { markTerminated, markError, startIfServerMode } from '$lib/stores/tunnel';
  import { context, openLauncher } from '$lib/stores/workspace';
  import { reportError, showNotice, type ToastTone } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import { t, tNow } from '$lib/i18n';
  import { theme, toggleTheme } from '$lib/stores/theme';
  import {
    PAGE_TAB,
    closeTerminal,
    showTab,
    terminals,
    type TerminalSession,
  } from '$lib/stores/terminals';
  import { terminalPrefs } from '$lib/stores/terminalPrefs';
  import Dashboard from '../pages/Dashboard.svelte';
  import Connections from '../pages/Connections.svelte';
  import Infrastructure from '../pages/Infrastructure.svelte';
  import Monitoring from '../pages/Monitoring.svelte';
  import Ansible from '../pages/Ansible.svelte';
  import Notifications from '../pages/Notifications.svelte';
  import ConnectionEditor from './ConnectionEditor.svelte';
  import PasswordPrompt from './PasswordPrompt.svelte';
  import SettingsModal from './SettingsModal.svelte';
  import StatusBar from './StatusBar.svelte';
  import CommandPalette from './CommandPalette.svelte';
  import StatusFooter from './StatusFooter.svelte';
  import TunnelIndicator from './TunnelIndicator.svelte';
  import NotificationBell from './NotificationBell.svelte';
  import SessionTabs from './terminal/SessionTabs.svelte';
  import SshTerminal from './terminal/SshTerminal.svelte';
  import Avatar from './ui/Avatar.svelte';
  import { confirmDialog } from './ui/ConfirmDialog.svelte';
  import Kbd from './ui/Kbd.svelte';
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
  import { allows } from '$lib/stores/dnd';
  import type { NotificationItem } from '$lib/api/types';

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
  // The center page (R-1078) needs a server session and has no sidebar entry: the bell and the
  // palette lead there.
  let onNotifications = $derived(isServerMode && $routePath.startsWith('/notifications'));

  let pageTitle = $derived(
    $t(
      onNotifications
        ? 'notifications.title'
        : (navItems.find((n) => n.id === currentId)?.labelKey ?? 'nav.dashboard'),
    ),
  );
  // Sessions of the embedded terminal (R-1069) are tabs after the page; one in front names
  // itself in the header.
  let activeSession = $derived($terminals.sessions.find((s) => s.key === $terminals.active));
  let title = $derived(activeSession?.connection.name ?? pageTitle);
  let subtitle = $derived(activeSession ? `SSH · ${activeSession.connection.host}` : null);
  // The workspace this window serves (R-0431); null only when its context did not load.
  let workspace = $derived($context?.workspace ?? null);

  function toLauncher(): void {
    openLauncher().catch((err) => reportError(errMsg(err)));
  }

  let paletteOpen = $state(false);
  const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.userAgent);
  // Pages as in the sidebar, so the palette never offers what this mode cannot show.
  let paletteEntries = $derived(
    buildEntries({
      connections: $connections,
      pages: [
        ...visibleNav.map((n) => ({ id: n.id, label: $t(n.labelKey), href: n.href })),
        ...(isServerMode
          ? [{ id: 'notifications', label: $t('notifications.title'), href: '/notifications' }]
          : []),
      ],
      actions: [
        { id: 'newConnection', label: $t('connections.new'), run: () => openEditor(null) },
        { id: 'settings', label: $t('settings.label'), run: openSettings },
        { id: 'theme', label: $t('theme.toggle'), run: toggleTheme },
        { id: 'workspace', label: $t('workspace.openLauncher'), run: toLauncher },
      ],
      connect: (c) => void initiateConnect(c),
      navigate,
    }),
  );

  // Ctrl+K / Cmd+K works from inside input fields too: it is the way out of one. Not over another
  // dialog: the palette would open beneath it and take the typing (a password) out of view.
  // e.code keeps the shortcut on layouts whose K key types another letter. Not from inside a
  // terminal: there Ctrl+K belongs to the shell, which cuts the line with it.
  function onWindowKeydown(e: KeyboardEvent): void {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    if (e.code !== 'KeyK' && e.key.toLowerCase() !== 'k') return;
    if (e.target instanceof Element && e.target.closest('.xterm')) return;
    if (document.querySelector('[aria-modal="true"]')) return;
    e.preventDefault();
    paletteOpen = true;
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

  // New feed entries become toasts and, while the user opted in, OS notifications; do not
  // disturb holds both back for this window, a critical entry always comes through (R-1078).
  const NOTICE_TONE: Record<NotificationItem['severity'], ToastTone> = {
    info: 'info',
    warning: 'warning',
    critical: 'danger',
  };
  function onNewNotifications(items: NotificationItem[], os: boolean): void {
    const shown = items.filter((n) => allows(n.severity));
    for (const n of shown) {
      showNotice({
        title: n.title,
        body: n.body,
        tone: NOTICE_TONE[n.severity],
        sticky: n.severity === 'critical',
        onOpen: () => navigate(`/notifications/${n.id}`),
      });
    }
    if (os && shown.length) void notifyOs(shown);
  }
  $effect(() => {
    const os = !!$settings?.osNotifications;
    setNewNotificationHandler((items) => onNewNotifications(items, os));
  });

  // The sidebar shows the page, also the one already open behind a session.
  function go(item: NavItem): void {
    showTab(PAGE_TAB);
    navigate(item.href);
  }

  // A page opened another way, from the palette or a notice, comes to the front too.
  $effect(() => {
    void $routePath;
    showTab(PAGE_TAB);
  });

  // A running session ends only after the question, when the options ask it; an ended one
  // closes at once.
  async function endSession(s: TerminalSession): Promise<void> {
    if (s.status !== 'disconnected' && get(terminalPrefs).confirmClose) {
      const ok = await confirmDialog(tNow('terminal.confirmEnd', { name: s.connection.name }), {
        confirmLabel: tNow('terminal.close'),
      });
      if (!ok) return;
    }
    closeTerminal(s.key);
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

<svelte:window onkeydown={onWindowKeydown} />

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
      <div class="sidebar-brand-text">Admin<span class="sidebar-brand-light">Helper</span></div>
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
        <ChevronsUpDown class="workspace-chip-caret" size={13} />
      </button>
    {/if}

    <nav class="sidebar-nav">
      {#each visibleNav as item (item.id)}
        <button
          class="sidebar-item"
          class:active={!onNotifications && currentId === item.id}
          aria-current={!onNotifications && currentId === item.id ? 'page' : undefined}
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
      {#if subtitle}<span class="page-subtitle">{subtitle}</span>{/if}
    </div>
    <div class="content-header-right">
      <!-- Not .btn.ghost.small: the live specs take the first of those for the sign-out. -->
      <button
        class="header-palette-btn"
        onclick={() => (paletteOpen = true)}
        title={$t('palette.open')}
        aria-label={$t('palette.open')}
        aria-keyshortcuts={isMac ? 'Meta+K' : 'Control+K'}
      >
        <Search size={14} />
        <Kbd>{isMac ? '⌘K' : $t('palette.shortcut')}</Kbd>
      </button>
      {#if $session}
        <NotificationBell />
        <span class="header-user">
          <Avatar name={$session.username} size="sm" />
          <span class="header-user-name">{$session.username}</span>
        </span>
        <button class="btn ghost small" onclick={() => logoutAndReload()}>{$t('nav.logout')}</button
        >
      {/if}
    </div>
  </header>

  <!-- The page and every session stay mounted behind the tab in front: a page keeps its state,
       a terminal its scrollback and its program. -->
  <div class="content-area">
    <SessionTabs
      sessions={$terminals.sessions}
      active={$terminals.active}
      pageLabel={pageTitle}
      onSelect={showTab}
      onClose={(s) => void endSession(s)}
    />
    <main class="content-main" class:hidden={activeSession !== undefined}>
      <section class="content-section">
        {#if onNotifications}
          <Notifications />
        {:else if currentId === 'dashboard'}
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
    {#each $terminals.sessions as s (s.key)}
      <div class="terminal-pane" class:hidden={s.key !== $terminals.active} data-session={s.key}>
        <SshTerminal session={s} onClose={() => void endSession(s)} />
      </div>
    {/each}
  </div>

  <StatusFooter />
</div>

<ConnectionEditor />
<PasswordPrompt />
<SettingsModal />
<StatusBar />
<CommandPalette open={paletteOpen} entries={paletteEntries} onClose={() => (paletteOpen = false)} />

<style>
  /* The row under the header: the tabs of the sessions over the page or a terminal. */
  .content-area {
    grid-column: 2;
    grid-row: 2;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .content-main {
    flex: 1;
    min-height: 0;
  }
  .terminal-pane {
    flex: 1;
    min-height: 0;
  }
  .hidden {
    display: none;
  }
  .page-subtitle {
    overflow: hidden;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 12px;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
</style>
