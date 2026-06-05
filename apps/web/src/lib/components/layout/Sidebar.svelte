<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { auth, currentUser, isAdmin } from '$lib/stores/auth';
  import { t, toggleLanguage, language } from '$lib/i18n';
  import { path as routerPath } from '$lib/router';

  interface NavEntry {
    page: string;
    label: string;
    icon: string;
    adminOnly: boolean;
    group?: 'top' | 'mid' | 'bot';
  }

  const items: NavEntry[] = [
    {
      page: 'connections',
      label: 'nav.connections',
      adminOnly: false,
      group: 'top',
      icon: 'M8 12h8M12 3v2m0 14v2M5.5 5.5l1.4 1.4m10.2 10.2l1.4 1.4M3 12h2m14 0h2M5.5 18.5l1.4-1.4m10.2-10.2l1.4-1.4',
    },
    {
      page: 'servers',
      label: 'nav.servers',
      adminOnly: true,
      group: 'mid',
      icon: 'M2 3h20v7H2zM2 14h20v7H2z',
    },
    {
      page: 'users',
      label: 'nav.users',
      adminOnly: true,
      group: 'mid',
      icon: 'M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 3a4 4 0 100 8 4 4 0 000-8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75',
    },
    {
      page: 'apikeys',
      label: 'nav.apikeys',
      adminOnly: true,
      group: 'mid',
      icon: 'M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.78 7.78 5.5 5.5 0 017.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4',
    },
    {
      page: 'hooks',
      label: 'nav.hooks',
      adminOnly: true,
      group: 'mid',
      icon: 'M13 2L3 14h9l-1 8 10-12h-9l1-8z',
    },
    {
      page: 'frp',
      label: 'nav.frp',
      adminOnly: true,
      group: 'mid',
      icon: 'M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71',
    },
    {
      page: 'ansible',
      label: 'nav.ansible',
      adminOnly: true,
      group: 'bot',
      icon: 'M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z',
    },
    {
      page: 'monitoring',
      label: 'nav.monitoring',
      adminOnly: true,
      group: 'bot',
      icon: 'M22 12h-4l-3 9L9 3l-3 9H2',
    },
  ];

  const visibleItems = $derived(items.filter((i) => !i.adminOnly || $isAdmin));

  function currentPage(loc: string): string {
    return (loc || '').replace(/^\//, '').split('/')[0] || 'connections';
  }
</script>

<aside class="sidebar">
  <div class="sidebar-brand">
    <img src="/assets/logo.svg" alt="Logo" class="logo-mark" />
    <div class="sidebar-brand-text">
      <div class="brand-title">Admin</div>
      <div class="brand-subtitle">Helper</div>
    </div>
  </div>

  <nav class="nav">
    {#each visibleItems as item, i (item.page)}
      {#if i > 0 && visibleItems[i - 1].group !== item.group}
        <div class="nav-divider"></div>
      {/if}
      <a
        class="nav-item"
        class:active={currentPage($routerPath) === item.page}
        href="#/{item.page}"
      >
        <i class="nav-icon">
          <svg viewBox="0 0 24 24"><path d={item.icon} /></svg>
        </i>
        <span>{$t(item.label)}</span>
      </a>
    {/each}
  </nav>

  <div class="sidebar-footer">
    <div class="sidebar-user">
      <div class="user-avatar">
        {$currentUser?.username?.charAt(0)?.toUpperCase() ?? '?'}
      </div>
      <div class="user-info">
        <div class="user-name">{$currentUser?.username ?? '-'}</div>
        <div class="user-role">
          {$currentUser?.is_admin ? $t('role.admin') : $t('role.user')}
        </div>
      </div>
    </div>
    <div style="display:flex;gap:6px;width:100%">
      <button class="btn small ghost" style="flex:1" onclick={() => auth.logout()}>
        {$t('nav.logout')}
      </button>
      <button
        class="btn small ghost"
        style="width:40px;flex-shrink:0;font-weight:600"
        onclick={toggleLanguage}
      >
        {$language === 'de' ? 'EN' : 'DE'}
      </button>
    </div>
  </div>
</aside>
