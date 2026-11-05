<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { ArrowUpRight, Globe, Monitor, Pencil, SquareTerminal, Star } from '@lucide/svelte';
  import type { Component } from 'svelte';
  import type { Connection, ConnectionKind, ConnectionSession } from '$lib/bridge/types';
  import { commandPreview, type Reach } from '$lib/models/connectionList';
  import { DEFAULT_PORTS, toCardMeta } from '$lib/models/connection';
  import { recentSessions, sessionsVersion } from '$lib/stores/connections';
  import { timeAgo } from '$lib/utils/timeAgo';
  import { t } from '$lib/i18n';
  import Button from '../ui/Button.svelte';
  import CodeBlock from '../ui/CodeBlock.svelte';
  import Dot from '../ui/Dot.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Tag from '../ui/Tag.svelte';
  import { reachView } from './ConnectionTable.svelte';

  interface Props {
    conn: Connection | null;
    favorite: boolean;
    reach: Reach;
    tunnel: string | null;
    server: string | null;
    onConnect: (c: Connection) => void;
    onEdit: (c: Connection) => void;
    onFavorite: (c: Connection) => void;
  }

  let { conn, favorite, reach, tunnel, server, onConnect, onEdit, onFavorite }: Props = $props();

  const KIND_ICONS: Record<ConnectionKind, Component<{ size?: number }>> = {
    ssh: SquareTerminal,
    rdp: Monitor,
    web: Globe,
  };
  const KIND_LABELS: Record<ConnectionKind, string> = {
    ssh: 'filters.ssh',
    rdp: 'filters.rdp',
    web: 'filters.web',
  };
  const LANGS: Record<ConnectionKind, string> = { ssh: 'ssh', rdp: 'xfreerdp', web: 'url' };

  let user = $derived(
    conn?.username ? (conn.domain ? `${conn.domain}\\${conn.username}` : conn.username) : null,
  );
  let command = $derived(conn ? commandPreview(conn) : '');
  let rv = $derived(reachView(reach));

  // The last sessions of the selected connection; reloaded whenever a connect writes a session
  // or an RDP end closes one.
  let sessions = $state<ConnectionSession[] | null>(null);
  let sessionsFailed = $state(false);
  $effect(() => {
    const id = conn?.id;
    void $sessionsVersion;
    sessions = null;
    sessionsFailed = false;
    if (!id) return;
    let stale = false;
    recentSessions(id, 5).then(
      (list) => {
        if (!stale) sessions = list;
      },
      () => {
        if (!stale) sessionsFailed = true;
      },
    );
    return () => {
      stale = true;
    };
  });

  function duration(s: ConnectionSession): string {
    if (!s.endedAt) return '—';
    const ms = Date.parse(s.endedAt) - Date.parse(s.startedAt);
    if (Number.isNaN(ms) || ms < 0) return '—';
    const mins = Math.floor(ms / 60_000);
    if (mins < 1) return $t('connections.insp.sessions.underMinute');
    if (mins < 60) return $t('connections.insp.sessions.minutes', { count: mins });
    return $t('connections.insp.sessions.hours', { h: Math.floor(mins / 60), m: mins % 60 });
  }
</script>

<aside class="insp" aria-label={$t('connections.insp')} data-testid="conn-inspector">
  {#if !conn}
    <p class="insp-empty">{$t('connections.insp.empty')}</p>
  {:else}
    {@const Icon = KIND_ICONS[conn.kind]}
    <div class="insp-head">
      <span class="insp-tile"><Icon size={22} /></span>
      <div class="insp-title">
        <h2>{conn.name || $t('list.noName')}</h2>
        <div class="insp-target">{conn.kind === 'web' ? conn.url || '-' : toCardMeta(conn)}</div>
      </div>
      <button
        type="button"
        class="insp-star"
        class:on={favorite}
        aria-pressed={favorite}
        aria-label={$t(favorite ? 'connections.favorite.remove' : 'connections.favorite.add')}
        title={$t(favorite ? 'connections.favorite.remove' : 'connections.favorite.add')}
        onclick={() => onFavorite(conn)}
      >
        <Star size={15} fill={favorite ? 'currentColor' : 'none'} />
      </button>
      <IconButton
        size="sm"
        variant="secondary"
        icon={Pencil}
        label={$t('action.edit')}
        onclick={() => onEdit(conn)}
      />
    </div>

    <Button
      variant="primary"
      fullWidth
      iconRight={conn.kind === 'web' ? ArrowUpRight : undefined}
      onclick={() => onConnect(conn)}
      >{$t(conn.kind === 'web' ? 'connections.open' : 'action.connect')}</Button
    >

    <dl class="insp-meta">
      <dt>{$t('connections.insp.kind')}</dt>
      <dd>{$t(KIND_LABELS[conn.kind])}</dd>
      {#if conn.kind === 'web'}
        <dt>{$t('connections.insp.url')}</dt>
        <dd class="mono">{conn.url || '-'}</dd>
      {:else}
        <dt>{$t('connections.insp.host')}</dt>
        <dd class="mono">{conn.host || '-'}</dd>
        <dt>{$t('connections.insp.port')}</dt>
        <dd class="mono">{conn.port ?? DEFAULT_PORTS[conn.kind]}</dd>
        <dt>{$t('connections.insp.user')}</dt>
        <dd class="mono">{user ?? '-'}</dd>
      {/if}
      {#if conn.keyPath}
        <dt>{$t('connections.insp.key')}</dt>
        <dd class="mono">{conn.keyPath}</dd>
      {/if}
      {#if tunnel}
        <dt>{$t('connections.insp.tunnel')}</dt>
        <dd><Dot st="info" size={7} /> {tunnel}</dd>
      {/if}
      {#if server}
        <dt>{$t('connections.insp.server')}</dt>
        <dd>{server}</dd>
      {/if}
      <dt>{$t('connections.insp.reach')}</dt>
      <dd class="mono" data-testid="insp-reach">
        <Dot st={rv.st} size={7} />
        {rv.key ? $t(rv.key, { ms: rv.ms ?? '' }) : $t('connections.insp.unknown')}
      </dd>
      <dt>{$t('connections.insp.last')}</dt>
      <dd>{timeAgo(conn.lastUsed, $t)}</dd>
    </dl>

    {#if conn.tags.length > 0}
      <div class="insp-tags">
        {#each conn.tags as tag (tag)}<Tag size="sm">{tag}</Tag>{/each}
      </div>
    {/if}

    {#if command}
      <section>
        <h3 class="eyebrow">{$t('connections.insp.command')}</h3>
        <CodeBlock code={command} lang={LANGS[conn.kind]} />
      </section>
    {/if}

    <section data-testid="insp-sessions">
      <h3 class="eyebrow">{$t('connections.insp.sessions')}</h3>
      {#if sessionsFailed}
        <p class="insp-muted">{$t('connections.insp.sessions.failed')}</p>
      {:else if sessions && sessions.length === 0}
        <p class="insp-muted">{$t('connections.insp.sessions.empty')}</p>
      {:else if sessions}
        <ul class="insp-sessions">
          {#each sessions as s (s.id)}
            <li>
              <span title={s.startedAt}>{timeAgo(s.startedAt, $t)}</span>
              <span class="mono">{duration(s)}</span>
              <span class="insp-device">{s.device ?? '—'}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    {#if conn.notes?.trim()}
      <section>
        <h3 class="eyebrow">{$t('connections.insp.notes')}</h3>
        <p class="insp-notes">{conn.notes}</p>
      </section>
    {/if}
  {/if}
</aside>

<style>
  .insp {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 20px;
  }
  .insp-empty {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted);
  }
  .insp-head {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .insp-tile {
    display: inline-grid;
    flex: 0 0 48px;
    height: 48px;
    place-items: center;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--text-muted);
  }
  .insp-title {
    flex: 1;
    min-width: 0;
  }
  h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text-strong);
    overflow-wrap: anywhere;
  }
  .insp-target {
    margin-top: 3px;
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-subtle);
    overflow-wrap: anywhere;
  }
  .insp-meta {
    display: grid;
    grid-template-columns: minmax(90px, 120px) 1fr;
    gap: 9px 16px;
    margin: 0;
    font-size: var(--text-sm);
  }
  dt {
    color: var(--text-subtle);
  }
  dd {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    margin: 0;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .insp-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .insp-star {
    display: inline-grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-subtle);
    cursor: pointer;
  }
  .insp-star.on {
    color: var(--text-strong);
  }
  h3 {
    margin: 0 0 8px;
  }
  .insp-muted {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted);
  }
  .insp-sessions {
    display: grid;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-sm);
  }
  .insp-sessions li {
    display: grid;
    grid-template-columns: minmax(90px, 120px) 70px 1fr;
    gap: 8px;
    color: var(--text);
  }
  .insp-device {
    color: var(--text-muted);
    overflow-wrap: anywhere;
  }
  .insp-notes {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-muted);
    white-space: pre-wrap;
  }
</style>
