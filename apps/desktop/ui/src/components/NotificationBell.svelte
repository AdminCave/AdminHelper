<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Bell from '@lucide/svelte/icons/bell';
  import BellOff from '@lucide/svelte/icons/bell-off';
  import Check from '@lucide/svelte/icons/check';
  import IconButton from './ui/IconButton.svelte';
  import Button from './ui/Button.svelte';
  import Menu, { type MenuItem } from './ui/Menu.svelte';
  import Tabs from './ui/Tabs.svelte';
  import { t, currentLocale } from '$lib/i18n';
  import { navigate } from '$lib/router';
  import { timeAgo } from '$lib/utils/timeAgo';
  import type { NotificationItem } from '$lib/api/types';
  import {
    categoryLabel,
    groupByDay,
    isOpen,
    matchesTab,
    stateLabel,
    type PanelTab,
  } from '$lib/models/notifications';
  import { dndUntil, endDnd, startDnd } from '$lib/stores/dnd';
  import {
    ackIncidents,
    notificationItems,
    unreadCount,
    panelOpen,
    togglePanel,
    closePanel,
    markAllRead,
    markRead,
  } from '$lib/stores/notifications';

  let tab = $state<PanelTab>('all');

  const items = $derived($notificationItems);
  const criticalUnread = $derived(items.some((n) => !n.read && n.severity === 'critical'));
  const tabs = $derived([
    { id: 'all', label: $t('notifications.tabAll'), count: items.length },
    {
      id: 'unread',
      label: $t('notifications.tabUnread'),
      count: items.filter((n) => !n.read).length,
    },
    { id: 'open', label: $t('notifications.tabOpen'), count: items.filter(isOpen).length },
  ]);
  const groups = $derived(groupByDay(items.filter((n) => matchesTab(n, tab))));
  const dndTime = $derived(
    $dndUntil === null
      ? ''
      : new Date($dndUntil).toLocaleTimeString(currentLocale(), {
          hour: '2-digit',
          minute: '2-digit',
        }),
  );
  const dndItems = $derived<MenuItem[]>([
    { label: $t('notifications.dnd1h'), onClick: () => startDnd('1h') },
    { label: $t('notifications.dnd4h'), onClick: () => startDnd('4h') },
    { label: $t('notifications.dndTomorrow'), onClick: () => startDnd('tomorrow') },
    ...($dndUntil === null
      ? []
      : [{ separator: true }, { label: $t('notifications.dndEnd'), onClick: endDnd }]),
  ]);

  function open(n: NotificationItem) {
    if (!n.read) void markRead([n.id]);
    closePanel();
    navigate(`/notifications/${n.id}`);
  }

  function showAll() {
    closePanel();
    navigate('/notifications');
  }
</script>

<div class="notif-wrap">
  <IconButton
    class={['notif-bell', $unreadCount > 0 && 'has-unread']}
    icon={$dndUntil === null ? Bell : BellOff}
    label={$t('notifications.title')}
    onclick={togglePanel}
    aria-expanded={$panelOpen}
  />
  {#if $unreadCount > 0}
    <span class="notif-badge" class:critical={criticalUnread} aria-hidden="true"
      >{$unreadCount > 99 ? '99+' : $unreadCount}</span
    >
  {/if}

  {#if $panelOpen}
    <!-- Full-screen transparent backdrop closes the panel on outside click. -->
    <button class="notif-backdrop" aria-label={$t('notifications.close')} onclick={closePanel}
    ></button>
    <div class="notif-panel" role="dialog" aria-label={$t('notifications.title')}>
      <header class="notif-panel-head">
        <span class="notif-panel-title">{$t('notifications.title')}</span>
        <Menu items={dndItems} align="end" width={220}>
          {#snippet trigger(p)}
            <Button {...p} class="notif-dnd" variant="ghost" size="sm" iconLeft={BellOff}>
              {$t('notifications.dnd')}
            </Button>
          {/snippet}
        </Menu>
      </header>
      {#if $dndUntil !== null}
        <div class="notif-dnd-note">
          <span>{$t('notifications.dndNote', { time: dndTime })}</span>
          <Button variant="ghost" size="sm" onclick={endDnd}>{$t('notifications.dndEnd')}</Button>
        </div>
      {/if}
      <div class="notif-tabs">
        <Tabs {tabs} bind:value={tab} label={$t('notifications.title')} />
      </div>
      <div class="notif-list">
        {#if groups.length === 0}
          <div class="notif-empty">{$t(`notifications.empty.${tab}`)}</div>
        {:else}
          {#each groups as g (g.bucket)}
            <div class="notif-group">{$t(`notifications.day.${g.bucket}`)}</div>
            {#each g.items as n (n.id)}
              <div class="notif-item" class:unread={!n.read}>
                <button type="button" class="notif-item-main" onclick={() => open(n)}>
                  <span class="notif-sev sev-{n.severity}" aria-hidden="true"></span>
                  <span class="notif-item-body">
                    <span class="notif-item-title"
                      >{n.title}{#if (n.count ?? 1) > 1}<span class="notif-item-count"
                          >×{n.count}</span
                        >{/if}</span
                    >
                    {#if n.body}<span class="notif-item-text">{n.body}</span>{/if}
                    <span class="notif-item-meta">
                      {[
                        $t(`notifications.severity.${n.severity}`),
                        categoryLabel(n.category, $t),
                        timeAgo(n.createdAt, $t),
                        stateLabel(n, $t, currentLocale()),
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </span>
                </button>
                {#if isOpen(n) && n.incidentId != null}
                  {@const incidentId = n.incidentId}
                  <Button
                    variant="ghost"
                    size="sm"
                    class="notif-item-ack"
                    onclick={() => ackIncidents([incidentId])}
                  >
                    {$t('notifications.ack')}
                  </Button>
                {/if}
                {#if !n.read}
                  <IconButton
                    class="notif-item-read"
                    icon={Check}
                    size="sm"
                    label={$t('notifications.markRead')}
                    onclick={() => markRead([n.id])}
                  />
                {/if}
              </div>
            {/each}
          {/each}
        {/if}
      </div>
      <footer class="notif-panel-foot">
        <Button variant="ghost" size="sm" disabled={$unreadCount === 0} onclick={markAllRead}>
          {$t('notifications.markAllRead')}
        </Button>
        <Button variant="ghost" size="sm" class="notif-show-all" onclick={showAll}>
          {$t('notifications.showAll')}
        </Button>
      </footer>
    </div>
  {/if}
</div>

<style>
  .notif-wrap {
    position: relative;
    display: inline-flex;
  }
  .notif-wrap :global(.notif-bell.has-unread) {
    color: var(--text);
  }
  .notif-badge {
    position: absolute;
    top: 0;
    right: 0;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    font-size: 10px;
    line-height: 16px;
    font-weight: 600;
    text-align: center;
    pointer-events: none;
  }
  .notif-badge.critical {
    background: var(--danger);
  }
  .notif-backdrop {
    position: fixed;
    inset: 0;
    z-index: 900;
    border: none;
    background: transparent;
    cursor: default;
  }
  .notif-panel {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 901;
    width: 380px;
    max-height: 70vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-elevated);
    border: 1px solid var(--border, rgba(127, 127, 127, 0.25));
    border-radius: var(--radius-sm);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
    overflow: hidden;
  }
  .notif-panel-head,
  .notif-panel-foot,
  .notif-dnd-note {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2, 8px);
    padding: var(--sp-2, 8px) var(--sp-3, 12px);
  }
  .notif-panel-head {
    border-bottom: 1px solid var(--border, rgba(127, 127, 127, 0.25));
  }
  .notif-panel-foot {
    border-top: 1px solid var(--border, rgba(127, 127, 127, 0.25));
  }
  .notif-panel-title {
    font-weight: 600;
  }
  .notif-dnd-note {
    background: var(--accent-muted);
    font-size: var(--text-sm);
  }
  .notif-tabs {
    padding: 0 var(--sp-3, 12px);
  }
  .notif-list {
    overflow-y: auto;
    flex: 1;
  }
  .notif-group {
    padding: var(--sp-2, 8px) var(--sp-3, 12px) var(--sp-1, 4px);
    color: var(--text-muted);
    font-size: var(--text-xs, 0.75em);
    font-weight: 600;
    text-transform: uppercase;
  }
  .notif-empty {
    padding: var(--sp-4, 16px);
    text-align: center;
    color: var(--text-muted);
  }
  .notif-item {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-1, 4px);
    padding-right: var(--sp-2, 8px);
    border-bottom: 1px solid var(--border, rgba(127, 127, 127, 0.15));
  }
  .notif-item.unread {
    background: var(--accent-muted);
  }
  .notif-item-main {
    display: flex;
    flex: 1;
    min-width: 0;
    gap: var(--sp-2, 8px);
    padding: var(--sp-3, 12px);
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .notif-item-main:hover {
    background: var(--surface-hover);
  }
  .notif-item :global(.notif-item-read),
  .notif-item :global(.notif-item-ack) {
    margin-top: var(--sp-2, 8px);
  }
  .notif-item-count {
    margin-left: 6px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 0.85em;
    font-weight: 400;
  }
  .notif-sev {
    flex: 0 0 auto;
    width: 8px;
    height: 8px;
    margin-top: 5px;
    border-radius: 50%;
    background: var(--text-muted);
  }
  .notif-sev.sev-critical {
    background: var(--danger);
  }
  .notif-sev.sev-warning {
    background: var(--warning);
  }
  .notif-sev.sev-info {
    background: var(--accent);
  }
  .notif-item-body {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }
  .notif-item-title {
    font-weight: 500;
  }
  .notif-item-text {
    color: var(--text-muted);
    font-size: 0.85em;
    margin-top: 2px;
    white-space: pre-line;
  }
  .notif-item-meta {
    color: var(--text-muted);
    font-size: 0.75em;
    margin-top: 4px;
  }
</style>
