<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { auth, currentUser, isAdmin } from '$lib/stores/auth';
  import { t, toggleLanguage, language } from '$lib/i18n';
  import { theme, toggleTheme } from '$lib/stores/theme';
  import { path as routerPath } from '$lib/router';
  import { routes } from '../../../routes';

  interface NavEntry {
    page: string;
    label: string;
    icon: string;
    group?: 'top' | 'mid' | 'bot';
  }

  const items: NavEntry[] = [
    {
      page: 'users',
      label: 'nav.users',
      group: 'mid',
      icon: 'M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 3a4 4 0 100 8 4 4 0 000-8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75',
    },
    {
      page: 'apikeys',
      label: 'nav.apikeys',
      group: 'mid',
      icon: 'M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.78 7.78 5.5 5.5 0 017.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4',
    },
    {
      page: 'hooks',
      label: 'nav.hooks',
      group: 'mid',
      icon: 'M13 2L3 14h9l-1 8 10-12h-9l1-8z',
    },
    {
      page: 'frp',
      label: 'nav.frp',
      group: 'mid',
      icon: 'M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71',
    },
    {
      page: 'audit',
      label: 'nav.audit',
      group: 'bot',
      icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
    },
  ];

  // adminOnly is the single source of truth in routes.ts; the sidebar reads it
  // from there so nav visibility and the router guard can never drift.
  const visibleItems = $derived(items.filter((i) => !routes['/' + i.page]?.adminOnly || $isAdmin));

  function currentPage(loc: string): string {
    return (loc || '').replace(/^\//, '').split('/')[0] || 'users';
  }
</script>

<aside class="sidebar">
  <div class="sidebar-brand">
    <svg class="logo-mark" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true">
      <path
        fill-rule="evenodd"
        clip-rule="evenodd"
        d="M28 0C12.536 0 0 12.536 0 28v44c0 15.464 12.536 28 28 28h44c15.464 0 28-12.536 28-28V28C100 12.536 87.464 0 72 0H28Zm22 26.5L24.5 52a6 6 0 0 0 8.485 8.485L50 43.97l16.515 16.515A6 6 0 0 0 75 51.999L50 26.5ZM31 66a6 6 0 0 0 0 12h38a6 6 0 0 0 0-12H31Z"
      />
    </svg>
    <div class="sidebar-brand-text">
      <div class="brand-title" style="font-weight:600">Admin</div>
      <div class="brand-subtitle" style="font-weight:300">Helper</div>
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
        style="width:40px;flex-shrink:0"
        onclick={toggleTheme}
        aria-label={$t('theme.toggle')}
        title={$t('theme.toggle')}
      >
        {#if $theme === 'dark'}
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        {:else}
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="4" />
            <path
              d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"
            />
          </svg>
        {/if}
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
