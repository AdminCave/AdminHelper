<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import BellOff from '@lucide/svelte/icons/bell-off';
  import Check from '@lucide/svelte/icons/check';
  import CheckCheck from '@lucide/svelte/icons/check-check';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import Mail from '@lucide/svelte/icons/mail';
  import Button from './ui/Button.svelte';
  import Input from './ui/Input.svelte';
  import Menu, { type MenuItem } from './ui/Menu.svelte';
  import MetaList from './ui/MetaList.svelte';
  import Pill from './ui/Pill.svelte';
  import { t, currentLocale } from '$lib/i18n';
  import { navigate } from '$lib/router';
  import { notificationsApi } from '$lib/api/notifications';
  import type { IncidentDetail, NotificationItem } from '$lib/api/types';
  import { currentSession } from '$lib/stores/session';
  import { setTab } from '$lib/stores/monitoring';
  import { categoryLabel, channelLabel, shortTime, stateLabel } from '$lib/models/notifications';
  import {
    ackIncidents,
    addNote,
    markRead,
    markUnread,
    muteIncident,
    muteServer,
    reopenIncident,
    resolveIncident,
    unmuteIncident,
    unmuteServer,
  } from '$lib/stores/notifications';

  interface Props {
    item: NotificationItem;
  }

  let { item }: Props = $props();

  let loaded = $state<IncidentDetail | null>(null);
  let failed = $state(false);
  let note = $state('');
  let busy = $state(false);
  let seq = 0;

  // The row fields an action or a ping changes: when one moves, the detail loads again.
  const version = $derived(
    [
      item.incidentId,
      item.state,
      item.count,
      item.notifiedAt,
      item.ackedBy,
      item.resolvedBy,
      item.muted,
      item.mutedUntil,
    ].join('|'),
  );

  $effect(() => {
    const id = item.incidentId;
    void version;
    const mine = ++seq;
    failed = false;
    const session = currentSession();
    if (id == null || !session) return;
    notificationsApi.fetchIncident(session, id).then(
      (d) => {
        if (mine === seq) loaded = d;
      },
      () => {
        if (mine === seq) failed = true;
      },
    );
  });

  // A detail of the incident shown before stays out until this one's has loaded.
  const detail = $derived(loaded && loaded.id === item.incidentId ? loaded : null);
  const incidentId = $derived(item.incidentId ?? null);
  const tone = $derived<'crit' | 'warn' | 'accent'>(
    item.severity === 'critical' ? 'crit' : item.severity === 'warning' ? 'warn' : 'accent',
  );
  const serverName = $derived(
    detail?.servers.find((s) => s.id === item.sourceId)?.name ?? item.sourceId ?? '',
  );
  const stateText = $derived(stateLabel(item, $t, currentLocale()));

  const rows = $derived.by(() => {
    const locale = currentLocale();
    const when = detail?.firstAt ?? item.createdAt;
    const out: { key: string; value: string; mono?: boolean }[] = [
      { key: $t('notifications.time'), value: when ? new Date(when).toLocaleString(locale) : '' },
    ];
    if (detail) {
      out.push({
        key: $t('notifications.servers'),
        value: detail.servers.map((s) => s.name).join(', ') || '—',
      });
      const rules = [...new Set((detail.rules ?? []).map((r) => r.name))];
      out.push({ key: $t('notifications.rule'), value: rules.join(', ') || '—', mono: false });
      const channels = [
        ...detail.channels.filter((c) => c !== 'bell').map((c) => channelLabel(c, $t)),
        ...(detail.rules ?? []).map((r) =>
          r.ok
            ? channelLabel(r.channel, $t)
            : $t('notifications.channelFailed', { channel: channelLabel(r.channel, $t) }),
        ),
      ];
      out.push({
        key: $t('notifications.channels'),
        value: [...new Set(channels)].join(', ') || $t('notifications.bellOnly'),
        mono: false,
      });
    } else if (item.sourceType) {
      out.push({
        key: $t('notifications.source'),
        value: `${item.sourceType}${item.sourceId ? ` ${item.sourceId}` : ''}`,
      });
    }
    out.push({ key: $t('notifications.id'), value: `#${incidentId ?? item.id}` });
    return out;
  });

  function inOneHour(): string {
    return new Date(Date.now() + 3600_000).toISOString();
  }

  function tomorrowSeven(): string {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 7).toISOString();
  }

  const muteItems = $derived.by<MenuItem[]>(() => {
    if (incidentId === null) return [];
    const items: MenuItem[] = [
      {
        label: $t('notifications.mute1h'),
        onClick: () => void muteIncident(incidentId, inOneHour()),
      },
      {
        label: $t('notifications.muteTomorrow'),
        onClick: () => void muteIncident(incidentId, tomorrowSeven()),
      },
    ];
    const serverId = item.sourceType === 'server' ? item.sourceId : null;
    if (serverId) {
      items.push({
        label: $t('notifications.muteServer', { server: serverName }),
        onClick: () => void muteServer(serverId, new Date(Date.now() + 86_400_000).toISOString()),
      });
    }
    if (item.category === 'monitoring') {
      items.push({ separator: true }, { label: $t('notifications.editRule'), onClick: editRule });
    }
    return items;
  });

  function editRule() {
    setTab('alerts');
    navigate('/monitoring');
  }

  async function run(action: () => Promise<IncidentDetail | null>): Promise<IncidentDetail | null> {
    busy = true;
    try {
      const d = await action();
      if (d) {
        seq++;
        loaded = d;
      }
      return d;
    } finally {
      busy = false;
    }
  }

  async function ack(id: number) {
    busy = true;
    try {
      await ackIncidents([id]);
    } finally {
      busy = false;
    }
  }

  function unmute(id: number) {
    if (item.muteSource === 'server' && item.sourceId) void unmuteServer(item.sourceId);
    else void unmuteIncident(id);
  }

  async function sendNote(id: number) {
    const text = note.trim();
    if (!text) return;
    // A failed request (reported in the status bar) keeps the typed text for a retry.
    if (await run(() => addNote(id, text))) note = '';
  }
</script>

<article class="nd" aria-label={item.title}>
  <div class="nd-head">
    <Pill {tone}>{$t(`notifications.severity.${item.severity}`)}</Pill>
    <span class="nd-source">
      {categoryLabel(item.category, $t)}{serverName ? ` · ${serverName}` : ''}
    </span>
    {#if stateText}<Pill tone="muted">{stateText}</Pill>{/if}
  </div>
  <h2 class="nd-title">
    {item.title}{#if (item.count ?? 1) > 1}<span class="nd-count">×{item.count}</span>{/if}
  </h2>
  {#if item.body}<p class="nd-text">{item.body}</p>{/if}

  <div class="nd-actions">
    {#if incidentId !== null && detail?.canAct}
      {#if item.state === 'open'}
        <Button
          size="sm"
          variant="primary"
          iconLeft={Check}
          class="nd-ack"
          disabled={busy}
          onclick={() => ack(incidentId)}
        >
          {$t('notifications.ack')}
        </Button>
      {/if}
      {#if item.state === 'open' || item.state === 'acked'}
        <Button
          size="sm"
          variant="secondary"
          iconLeft={CheckCheck}
          class="nd-resolve"
          disabled={busy}
          onclick={() => run(() => resolveIncident(incidentId))}
        >
          {$t('notifications.resolve')}
        </Button>
      {/if}
      {#if item.state === 'resolved'}
        <Button
          size="sm"
          variant="secondary"
          iconLeft={RotateCcw}
          class="nd-reopen"
          disabled={busy}
          onclick={() => run(() => reopenIncident(incidentId))}
        >
          {$t('notifications.reopen')}
        </Button>
      {/if}
    {/if}
    {#if item.read}
      <Button
        size="sm"
        variant="ghost"
        iconLeft={Mail}
        class="nd-unread"
        onclick={() => markUnread([item.id])}
      >
        {$t('notifications.markUnread')}
      </Button>
    {:else}
      <Button
        size="sm"
        variant="ghost"
        iconLeft={Check}
        class="nd-read"
        onclick={() => markRead([item.id])}
      >
        {$t('notifications.markRead')}
      </Button>
    {/if}
    {#if incidentId !== null}
      {#if item.muted}
        <Button
          size="sm"
          variant="ghost"
          iconLeft={BellOff}
          class="nd-unmute"
          onclick={() => unmute(incidentId)}
        >
          {$t('notifications.unmute')}
        </Button>
      {:else}
        <Menu items={muteItems} align="end" width={240}>
          {#snippet trigger(p)}
            <Button {...p} class="nd-mute" variant="ghost" size="sm" iconLeft={BellOff}>
              {$t('notifications.mute')}
            </Button>
          {/snippet}
        </Menu>
      {/if}
    {/if}
  </div>
  {#if detail && !detail.canAct}
    <p class="nd-hint">{$t('notifications.noAct')}</p>
  {/if}
  {#if failed}
    <p class="nd-hint nd-failed">{$t('notifications.loadFailed')}</p>
  {/if}

  <MetaList {rows} />

  {#if detail}
    <section class="nd-history" aria-label={$t('notifications.historyHead')}>
      <h3 class="nd-head3">{$t('notifications.historyHead')}</h3>
      <ol class="nd-timeline">
        {#each detail.history as e (e.id)}
          <li class="nd-entry" data-kind={e.kind}>
            <div class="nd-entry-head">
              <span class="nd-entry-kind">{$t(`notifications.history.${e.kind}`)}</span>
              <span class="nd-entry-meta">
                {shortTime(e.at, currentLocale())} · {e.actor ?? $t('notifications.byHub')}
              </span>
            </div>
            {#if e.text}
              <div class="nd-entry-text">
                {e.kind === 'notified'
                  ? e.text
                      .split(',')
                      .map((c) => channelLabel(c.trim(), $t))
                      .join(', ')
                  : e.text}
              </div>
            {/if}
          </li>
        {/each}
      </ol>
    </section>
    {#if detail.canAct && incidentId !== null}
      <div class="nd-note">
        <div class="nd-note-row">
          <Input
            bind:value={note}
            size="sm"
            placeholder={$t('notifications.notePlaceholder')}
            disabled={busy}
            onkeydown={(e) => {
              if (e.key === 'Enter') void sendNote(incidentId);
            }}
          />
          <Button
            size="sm"
            variant="secondary"
            class="nd-add-note"
            disabled={busy || !note.trim()}
            onclick={() => sendNote(incidentId)}
          >
            {$t('notifications.addNote')}
          </Button>
        </div>
        <p class="nd-hint">{$t('notifications.noteHint')}</p>
      </div>
    {/if}
  {/if}
</article>

<style>
  .nd {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    padding: var(--sp-4);
  }
  .nd-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .nd-source {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .nd-title {
    margin: 0;
    font-size: var(--text-lg, 1.1em);
    overflow-wrap: anywhere;
  }
  .nd-count {
    margin-left: 6px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 0.8em;
  }
  .nd-text {
    margin: 0;
    white-space: pre-line;
  }
  .nd-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .nd-hint {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .nd-failed {
    color: var(--danger);
  }
  .nd-head3 {
    margin: 0 0 var(--sp-2);
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .nd-timeline {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin: 0;
    padding: 0 0 0 var(--sp-3);
    border-left: 2px solid var(--border);
    list-style: none;
  }
  .nd-entry-head {
    display: flex;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: var(--text-sm);
  }
  .nd-entry-kind {
    font-weight: 500;
  }
  .nd-entry-meta {
    color: var(--text-muted);
    font-size: 12px;
    white-space: nowrap;
  }
  .nd-entry-text {
    color: var(--text-muted);
    font-size: var(--text-sm);
    white-space: pre-line;
    overflow-wrap: anywhere;
  }
  .nd-note {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .nd-note-row {
    display: flex;
    gap: var(--sp-2);
  }
</style>
