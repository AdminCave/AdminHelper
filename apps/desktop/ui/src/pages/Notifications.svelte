<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import Check from '@lucide/svelte/icons/check';
  import CheckCheck from '@lucide/svelte/icons/check-check';
  import EyeOff from '@lucide/svelte/icons/eye-off';
  import NotificationDetail from '../components/NotificationDetail.svelte';
  import Button from '../components/ui/Button.svelte';
  import Checkbox from '../components/ui/Checkbox.svelte';
  import SearchField from '../components/ui/SearchField.svelte';
  import Segmented from '../components/ui/Segmented.svelte';
  import EmptyState from '../components/ui/EmptyState.svelte';
  import { t, currentLocale } from '$lib/i18n';
  import { navigate, segments } from '$lib/router';
  import { timeAgo } from '$lib/utils/timeAgo';
  import type { NotificationSeverity } from '$lib/api/types';
  import {
    categoriesOf,
    categoryLabel,
    filterItems,
    groupByDay,
    isOpen,
    matchesMailbox,
    stateLabel,
    type Mailbox,
  } from '$lib/models/notifications';
  import {
    ackIncidents,
    centerItems,
    centerHasMore,
    hide,
    notificationItems,
    loadCenter,
    markRead,
  } from '$lib/stores/notifications';

  const MAILBOXES: Mailbox[] = ['inbox', 'open', 'acked', 'resolved', 'muted', 'all'];
  // The narrow layout's switch keeps the three a reader needs most; the rail holds all six.
  const SWITCH: Mailbox[] = ['inbox', 'open', 'all'];
  const SEVERITIES: NotificationSeverity[] = ['critical', 'warning', 'info'];

  let mailbox = $state<Mailbox>('inbox');
  let severity = $state<NotificationSeverity | null>(null);
  let category = $state<string | null>(null);
  let query = $state('');
  let picked = $state<number[]>([]);
  let skipped = $state(0);

  onMount(() => void loadCenter());

  // The bell's feed carries what arrived after the page loaded (a toast opens it here), the
  // center list what lies further back; the feed's copy is the fresher one. Newest first, as
  // the feed sorts.
  const all = $derived.by(() => {
    const fresh = $notificationItems.map((n) => n.id);
    return [...$notificationItems, ...$centerItems.filter((n) => !fresh.includes(n.id))].sort(
      (a, b) => b.id - a.id,
    );
  });
  const inMailbox = $derived(all.filter((n) => matchesMailbox(n, mailbox)));
  const shown = $derived(filterItems(all, { mailbox, severity, category, query }));
  const groups = $derived(groupByDay(shown));
  const categories = $derived(categoriesOf(inMailbox));
  const selectedId = $derived(Number($segments[1]));
  const selected = $derived(all.find((n) => n.id === selectedId) ?? null);
  // Only what the filter shows counts: a row picked before the filter changed is not sent unseen.
  const pickedShown = $derived(shown.filter((n) => picked.includes(n.id)));
  const pickedUnread = $derived(pickedShown.filter((n) => !n.read).map((n) => n.id));
  // Incidents, not rows: two picked rows of one incident acknowledge it once.
  const pickedOpen = $derived([
    ...new Set(
      pickedShown
        .filter(isOpen)
        .map((n) => n.incidentId)
        .filter((id): id is number => id != null),
    ),
  ]);

  const mailboxCount = (m: Mailbox) => all.filter((n) => matchesMailbox(n, m)).length;
  const severityCount = (s: NotificationSeverity) =>
    inMailbox.filter((n) => n.severity === s).length;

  function pick(id: number, on: boolean) {
    picked = on ? [...picked, id] : picked.filter((x) => x !== id);
    skipped = 0;
  }

  async function markPicked() {
    await markRead(pickedUnread);
    picked = [];
  }

  async function ackPicked() {
    const res = await ackIncidents(pickedOpen);
    if (!res) return;
    picked = [];
    skipped = res.skipped.length;
  }

  async function hidePicked() {
    if (await hide(pickedShown.map((n) => n.id))) picked = [];
  }
</script>

<div class="nc-page">
  <aside class="nc-rail" aria-label={$t('notifications.filters')}>
    <div class="nc-rail-head">{$t('notifications.mailbox')}</div>
    {#each MAILBOXES as m (m)}
      <button
        type="button"
        class="nc-rail-item"
        class:active={mailbox === m}
        data-mailbox={m}
        onclick={() => (mailbox = m)}
      >
        <span>{$t(`notifications.mailbox.${m}`)}</span><span class="nc-count"
          >{mailboxCount(m)}</span
        >
      </button>
    {/each}
    <div class="nc-rail-head">{$t('notifications.severityHead')}</div>
    {#each SEVERITIES as s (s)}
      <button
        type="button"
        class="nc-rail-item"
        class:active={severity === s}
        data-severity={s}
        onclick={() => (severity = severity === s ? null : s)}
      >
        <span
          ><span class="nc-sev sev-{s}" aria-hidden="true"></span>{$t(
            `notifications.severity.${s}`,
          )}</span
        ><span class="nc-count">{severityCount(s)}</span>
      </button>
    {/each}
    {#if categories.length}
      <div class="nc-rail-head">{$t('notifications.categoryHead')}</div>
      {#each categories as c (c.category)}
        <button
          type="button"
          class="nc-rail-item"
          class:active={category === c.category}
          data-category={c.category}
          onclick={() => (category = category === c.category ? null : c.category)}
        >
          <span>{categoryLabel(c.category, $t)}</span><span class="nc-count">{c.count}</span>
        </button>
      {/each}
    {/if}
  </aside>

  <div class="nc-main">
    <div class="nc-toolbar">
      <div class="nc-search">
        <SearchField
          bind:value={query}
          placeholder={$t('notifications.search')}
          label={$t('notifications.search')}
          size="sm"
          fullWidth
        />
      </div>
      <div class="nc-mailbox-switch">
        <Segmented
          label={$t('notifications.mailbox')}
          value={mailbox}
          options={SWITCH.map((m) => ({ value: m, label: $t(`notifications.mailbox.${m}`) }))}
          onChange={(v) => (mailbox = v as Mailbox)}
        />
      </div>
      {#if pickedShown.length}
        <div class="nc-bulk">
          {#if pickedUnread.length}
            <Button
              size="sm"
              variant="secondary"
              iconLeft={Check}
              class="nc-mark-picked"
              onclick={markPicked}
            >
              {$t('notifications.markPicked', { count: pickedUnread.length })}
            </Button>
          {/if}
          {#if pickedOpen.length}
            <Button
              size="sm"
              variant="secondary"
              iconLeft={CheckCheck}
              class="nc-ack-picked"
              onclick={ackPicked}
            >
              {$t('notifications.ackPicked', { count: pickedOpen.length })}
            </Button>
          {/if}
          <Button
            size="sm"
            variant="secondary"
            iconLeft={EyeOff}
            class="nc-hide-picked"
            onclick={hidePicked}
          >
            {$t('notifications.hidePicked', { count: pickedShown.length })}
          </Button>
          <Button size="sm" variant="ghost" class="nc-unpick" onclick={() => (picked = [])}>
            {$t('notifications.unpick')}
          </Button>
        </div>
      {/if}
    </div>
    {#if skipped}
      <div class="nc-note" role="status">{$t('notifications.ackSkipped', { count: skipped })}</div>
    {/if}

    <div class="nc-scroll">
      {#if groups.length === 0}
        <div class="nc-empty">
          <EmptyState title={$t('notifications.empty.all')} framed={false} />
        </div>
      {:else}
        {#each groups as g (g.bucket)}
          <div class="nc-group">{$t(`notifications.day.${g.bucket}`)}</div>
          {#each g.items as n (n.id)}
            <div class="nc-row" class:unread={!n.read} class:selected={n.id === selectedId}>
              <Checkbox
                ariaLabel={$t('notifications.pick', { title: n.title })}
                checked={picked.includes(n.id)}
                onChange={(on) => pick(n.id, on)}
              />
              <button
                type="button"
                class="nc-row-main"
                onclick={() => navigate(`/notifications/${n.id}`)}
              >
                <span class="nc-sev sev-{n.severity}" aria-hidden="true"></span>
                <span class="nc-row-title"
                  >{n.title}{#if (n.count ?? 1) > 1}<span class="nc-row-count">×{n.count}</span
                    >{/if}</span
                >
                {#if stateLabel(n, $t, currentLocale())}
                  <span class="nc-row-state">{stateLabel(n, $t, currentLocale())}</span>
                {/if}
                <span class="nc-row-meta"
                  >{categoryLabel(n.category, $t)} · {timeAgo(n.createdAt, $t)}</span
                >
              </button>
            </div>
          {/each}
        {/each}
      {/if}
      <!-- Also under an empty result: the match may sit in the part not loaded yet. -->
      {#if $centerHasMore}
        <div class="nc-more">
          <Button size="sm" variant="ghost" onclick={() => loadCenter(false)}>
            {$t('notifications.loadMore')}
          </Button>
        </div>
      {/if}
    </div>
  </div>

  <div class="nc-detail">
    {#if selected}
      {#key selected.id}
        <NotificationDetail item={selected} />
      {/key}
    {:else}
      <div class="nc-empty">
        <EmptyState title={$t('notifications.noneSelected')} framed={false} />
      </div>
    {/if}
  </div>
</div>

<style>
  .nc-page {
    container-type: inline-size;
    display: flex;
    height: 100%;
    min-height: 0;
  }
  .nc-rail {
    display: none;
    flex: 0 0 220px;
    flex-direction: column;
    gap: 2px;
    padding: var(--sp-3);
    overflow-y: auto;
    border-right: 1px solid var(--border);
  }
  .nc-rail-head {
    padding: var(--sp-3) var(--sp-2) var(--sp-1);
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .nc-rail-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--sp-2);
    padding: 6px var(--sp-2);
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
  }
  .nc-rail-item:hover {
    background: var(--surface-hover);
  }
  .nc-rail-item.active {
    background: var(--accent-muted);
  }
  .nc-count {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-subtle);
  }
  .nc-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }
  .nc-toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    padding: var(--sp-3) var(--sp-4);
    border-bottom: 1px solid var(--border);
  }
  .nc-search {
    flex: 1 1 220px;
    min-width: 180px;
    max-width: 420px;
  }
  .nc-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding-bottom: var(--sp-4);
  }
  .nc-group {
    padding: var(--sp-3) var(--sp-4) var(--sp-1);
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .nc-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-left: var(--sp-4);
    border-bottom: 1px solid var(--border);
  }
  .nc-row.unread {
    background: var(--accent-muted);
  }
  .nc-row.selected {
    box-shadow: inset 3px 0 0 var(--accent);
  }
  .nc-row-main {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex: 1;
    min-width: 0;
    padding: var(--sp-2) var(--sp-4) var(--sp-2) 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .nc-row-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .nc-row-meta {
    color: var(--text-muted);
    font-size: 12px;
    white-space: nowrap;
  }
  .nc-sev {
    display: inline-block;
    flex: 0 0 auto;
    width: 8px;
    height: 8px;
    margin-right: 6px;
    border-radius: 50%;
    background: var(--text-muted);
  }
  .nc-sev.sev-critical {
    background: var(--danger);
  }
  .nc-sev.sev-warning {
    background: var(--warning);
  }
  .nc-sev.sev-info {
    background: var(--accent);
  }
  .nc-more {
    display: flex;
    justify-content: center;
    padding: var(--sp-3);
  }
  .nc-empty {
    padding: var(--sp-5);
  }
  .nc-detail {
    display: none;
    flex: 0 0 340px;
    min-height: 0;
    overflow-y: auto;
    border-left: 1px solid var(--border);
  }
  .nc-bulk {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .nc-note {
    padding: var(--sp-2) var(--sp-4);
    border-bottom: 1px solid var(--border);
    background: var(--warning-bg);
    font-size: var(--text-sm);
  }
  .nc-row-count {
    margin-left: 6px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .nc-row-state {
    color: var(--text-muted);
    font-size: 12px;
    white-space: nowrap;
  }

  /* A container query only reaches descendants, hence nothing on .nc-page itself here. */
  @container (min-width: 900px) {
    .nc-detail {
      display: block;
    }
  }
  /* From 1180 px the filters live in the rail, and the mailbox switch in the toolbar goes. */
  @container (min-width: 1180px) {
    .nc-rail {
      display: flex;
    }
    .nc-mailbox-switch {
      display: none;
    }
  }
</style>
