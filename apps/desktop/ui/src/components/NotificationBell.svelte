<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import { timeAgo } from '$lib/utils/timeAgo';
  import {
    notificationItems,
    unreadCount,
    panelOpen,
    togglePanel,
    closePanel,
    markAllRead,
  } from '$lib/stores/notifications';

  const BELL_ICON =
    'M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5S10.5 3.17 10.5 4v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z';
</script>

<div class="notif-wrap">
  <button
    class="notif-bell"
    class:has-unread={$unreadCount > 0}
    onclick={togglePanel}
    title={$t('notifications.title')}
    aria-label={$t('notifications.title')}
  >
    <svg viewBox="0 0 24 24" width="20" height="20"><path d={BELL_ICON} /></svg>
    {#if $unreadCount > 0}
      <span class="notif-badge">{$unreadCount > 99 ? '99+' : $unreadCount}</span>
    {/if}
  </button>

  {#if $panelOpen}
    <!-- Full-screen transparent backdrop closes the panel on outside click. -->
    <button class="notif-backdrop" aria-label={$t('notifications.close')} onclick={closePanel}
    ></button>
    <div class="notif-panel" role="dialog" aria-label={$t('notifications.title')}>
      <header class="notif-panel-head">
        <span class="notif-panel-title">{$t('notifications.title')}</span>
        {#if $notificationItems.length > 0}
          <button class="btn ghost small" onclick={markAllRead}>
            {$t('notifications.markAllRead')}
          </button>
        {/if}
      </header>
      <div class="notif-list">
        {#if $notificationItems.length === 0}
          <div class="notif-empty">{$t('notifications.empty')}</div>
        {:else}
          {#each $notificationItems as n (n.id)}
            <div class="notif-item" class:unread={!n.read}>
              <span class="notif-sev sev-{n.severity}" aria-hidden="true"></span>
              <div class="notif-item-body">
                <div class="notif-item-title">{n.title}</div>
                {#if n.body}<div class="notif-item-text">{n.body}</div>{/if}
                <div class="notif-item-meta">{timeAgo(n.createdAt, $t)}</div>
              </div>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .notif-wrap {
    position: relative;
    display: inline-flex;
  }
  .notif-bell {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    background: transparent;
    color: var(--text-muted, #888);
    cursor: pointer;
    border-radius: var(--radius, 6px);
  }
  .notif-bell:hover {
    background: var(--bg-hover, rgba(127, 127, 127, 0.12));
    color: var(--text, #eee);
  }
  .notif-bell.has-unread {
    color: var(--text, #eee);
  }
  .notif-badge {
    position: absolute;
    top: 2px;
    right: 2px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: 8px;
    background: var(--danger, #e5484d);
    color: #fff;
    font-size: 10px;
    line-height: 16px;
    font-weight: 600;
    text-align: center;
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
    width: 360px;
    max-height: 70vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-elevated, #1e1e1e);
    border: 1px solid var(--border, rgba(127, 127, 127, 0.25));
    border-radius: var(--radius, 8px);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
    overflow: hidden;
  }
  .notif-panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-3, 12px);
    border-bottom: 1px solid var(--border, rgba(127, 127, 127, 0.25));
  }
  .notif-panel-title {
    font-weight: 600;
  }
  .notif-list {
    overflow-y: auto;
  }
  .notif-empty {
    padding: var(--sp-4, 16px);
    text-align: center;
    color: var(--text-muted, #888);
  }
  .notif-item {
    display: flex;
    gap: var(--sp-2, 8px);
    padding: var(--sp-3, 12px);
    border-bottom: 1px solid var(--border, rgba(127, 127, 127, 0.15));
  }
  .notif-item.unread {
    background: var(--bg-hover, rgba(80, 130, 220, 0.08));
  }
  .notif-sev {
    flex: 0 0 auto;
    width: 8px;
    height: 8px;
    margin-top: 5px;
    border-radius: 50%;
    background: var(--text-muted, #888);
  }
  .notif-sev.sev-critical {
    background: var(--danger, #e5484d);
  }
  .notif-sev.sev-warning {
    background: var(--warning, #f5a623);
  }
  .notif-sev.sev-info {
    background: var(--info, #5082dc);
  }
  .notif-item-body {
    min-width: 0;
    flex: 1;
  }
  .notif-item-title {
    font-weight: 500;
  }
  .notif-item-text {
    color: var(--text-muted, #aaa);
    font-size: 0.85em;
    margin-top: 2px;
    white-space: pre-line;
  }
  .notif-item-meta {
    color: var(--text-muted, #888);
    font-size: 0.75em;
    margin-top: 4px;
  }
</style>
