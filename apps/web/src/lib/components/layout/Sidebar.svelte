<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component } from 'svelte';
  import ClipboardCheck from '@lucide/svelte/icons/clipboard-check';
  import KeyRound from '@lucide/svelte/icons/key-round';
  import Link from '@lucide/svelte/icons/link';
  import LogOut from '@lucide/svelte/icons/log-out';
  import Moon from '@lucide/svelte/icons/moon';
  import ShieldCheck from '@lucide/svelte/icons/shield-check';
  import Sun from '@lucide/svelte/icons/sun';
  import Users from '@lucide/svelte/icons/users';
  import Zap from '@lucide/svelte/icons/zap';
  import { auth, currentUser, isAdmin } from '$lib/stores/auth';
  import { t, toggleLanguage, language } from '$lib/i18n';
  import { theme, toggleTheme } from '$lib/stores/theme';
  import { path as routerPath } from '$lib/router';
  import IconButton from '$lib/components/ui/IconButton.svelte';
  import { routes } from '../../../routes';

  interface NavEntry {
    page: string;
    label: string;
    icon: Component<{ size?: number }>;
    group: 'mid' | 'bot';
  }

  const items: NavEntry[] = [
    { page: 'users', label: 'nav.users', group: 'mid', icon: Users },
    { page: 'apikeys', label: 'nav.apikeys', group: 'mid', icon: KeyRound },
    { page: 'hooks', label: 'nav.hooks', group: 'mid', icon: Zap },
    { page: 'frp', label: 'nav.frp', group: 'mid', icon: Link },
    { page: 'certificates', label: 'nav.certificates', group: 'bot', icon: ShieldCheck },
    { page: 'audit', label: 'nav.audit', group: 'bot', icon: ClipboardCheck },
  ];

  // adminOnly is the single source of truth in routes.ts; the sidebar reads it
  // from there so nav visibility and the router guard can never drift.
  const visibleItems = $derived(items.filter((i) => !routes['/' + i.page]?.adminOnly || $isAdmin));

  function currentPage(loc: string): string {
    return (loc || '').replace(/^\//, '').split('/')[0] || 'users';
  }
</script>

<aside class="sidebar">
  <div class="brand">
    <svg class="logo" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true">
      <path
        fill-rule="evenodd"
        clip-rule="evenodd"
        d="M28 0C12.536 0 0 12.536 0 28v44c0 15.464 12.536 28 28 28h44c15.464 0 28-12.536 28-28V28C100 12.536 87.464 0 72 0H28Zm22 26.5L24.5 52a6 6 0 0 0 8.485 8.485L50 43.97l16.515 16.515A6 6 0 0 0 75 51.999L50 26.5ZM31 66a6 6 0 0 0 0 12h38a6 6 0 0 0 0-12H31Z"
      />
    </svg>
    <div class="brand-text">Admin<span class="brand-light">Helper</span></div>
  </div>

  <nav class="nav">
    {#each visibleItems as item, i (item.page)}
      {#if i > 0 && visibleItems[i - 1].group !== item.group}
        <div class="divider"></div>
      {/if}
      {@const active = currentPage($routerPath) === item.page}
      <a class="item" class:active aria-current={active ? 'page' : undefined} href="#/{item.page}">
        <item.icon size={20} />
        <span class="label">{$t(item.label)}</span>
      </a>
    {/each}
  </nav>

  <div class="footer">
    <div class="user">
      <div class="avatar" aria-hidden="true">
        {$currentUser?.username?.charAt(0)?.toUpperCase() ?? '?'}
      </div>
      <div class="user-info">
        <div class="user-name">{$currentUser?.username ?? '-'}</div>
        <div class="user-role">
          {$currentUser?.is_admin ? $t('role.admin') : $t('role.user')}
        </div>
      </div>
      <IconButton
        icon={LogOut}
        label={$t('nav.logout')}
        title={$t('nav.logout')}
        onclick={() => auth.logout()}
      />
    </div>
    <div class="tools">
      <IconButton
        icon={$theme === 'dark' ? Moon : Sun}
        label={$t('theme.toggle')}
        title={$t('theme.toggle')}
        onclick={toggleTheme}
      />
      <button class="lang" type="button" onclick={toggleLanguage}>
        {$language === 'de' ? 'EN' : 'DE'}
      </button>
    </div>
  </div>
</aside>

<style>
  .sidebar {
    width: 240px;
    flex-shrink: 0;
    position: sticky;
    top: 0;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow-y: auto;
    border-right: 1px solid var(--border);
    background: var(--bg);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .logo {
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    color: var(--text-strong);
  }
  .brand-text {
    color: var(--text-strong);
    font-size: 19px;
    font-weight: 600;
    letter-spacing: -0.03em;
    white-space: nowrap;
  }
  .brand-light {
    font-weight: 300;
  }
  .nav {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-3) var(--space-2);
  }
  .item {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: 10px var(--space-3);
    border-radius: var(--radius-md);
    color: var(--text-muted);
    font-size: var(--text-sm);
    font-weight: 500;
    text-decoration: none;
    transition:
      background var(--dur-fast) var(--ease-out),
      color var(--dur-fast) var(--ease-out);
  }
  .item:hover {
    background: var(--hover);
    color: var(--text);
  }
  .item:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  /* Active: bold text and a bar at the sidebar's edge, no fill (as in the desktop). */
  .item.active {
    color: var(--text-strong);
    font-weight: 600;
  }
  .item.active:hover {
    background: transparent;
  }
  .item.active::before {
    content: '';
    position: absolute;
    left: calc(-1 * var(--space-2));
    top: 9px;
    bottom: 9px;
    width: 3px;
    border-radius: var(--radius-pill);
    background: var(--text-strong);
  }
  .label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .divider {
    height: 1px;
    margin: var(--space-2) var(--space-3);
    background: var(--border);
  }
  .footer {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border-top: 1px solid var(--border);
  }
  .user {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .avatar {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    border-radius: var(--radius-pill);
    background: var(--surface-raised);
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .user-info {
    flex: 1;
    min-width: 0;
  }
  .user-name {
    overflow: hidden;
    color: var(--text);
    font-size: var(--text-sm);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .user-role {
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .tools {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }
  .lang {
    height: 32px;
    padding: 0 var(--space-2);
    border: none;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: var(--text-sm);
    font-weight: 600;
    cursor: pointer;
  }
  .lang:hover {
    background: var(--hover);
    color: var(--text);
  }
  .lang:focus-visible {
    outline: none;
    box-shadow: var(--ring-shadow);
  }
  @media (max-width: 768px) {
    .sidebar {
      width: 200px;
    }
  }
</style>
