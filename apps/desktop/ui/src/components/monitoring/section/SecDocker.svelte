<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { containerDetails, type DockerContainer } from '$lib/models/checkDetails';
  import { worstStatus } from '$lib/models/monitoring';
  import { spanText } from '$lib/models/monitoringText';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import MonSectionIcon from './MonSectionIcon.svelte';
  import Tag from '../../ui/Tag.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  // Spelled out: the i18n "no unused keys" guard only sees quoted keys.
  const ERROR_KEY = new Map<string, string>([
    ['daemon_unreachable', 'monitoring.docker.error.daemon_unreachable'],
    ['timeout', 'monitoring.docker.error.timeout'],
    ['cli_failed', 'monitoring.docker.error.cli_failed'],
    ['parse_failed', 'monitoring.docker.error.parse_failed'],
  ]);
  const REASON_KEY = new Map<string, string>([
    ['oom', 'monitoring.docker.reason.oom'],
    ['start_failed', 'monitoring.docker.reason.start_failed'],
    ['restarting', 'monitoring.docker.reason.restarting'],
    ['dead', 'monitoring.docker.reason.dead'],
    ['unhealthy', 'monitoring.docker.reason.unhealthy'],
    ['paused', 'monitoring.docker.reason.paused'],
    ['created', 'monitoring.docker.reason.created'],
    ['stopped', 'monitoring.docker.reason.stopped'],
    ['unknown_state', 'monitoring.docker.reason.unknown_state'],
  ]);
  // stopped is neutral: ended on purpose, neither green nor a problem.
  const LEVEL = { critical: 'crit', warning: 'warn', ok: 'ok', stopped: 'none' } as const;
  const DOT = {
    crit: 'mon-critical',
    warn: 'mon-warning',
    ok: 'mon-ok',
    none: 'mon-unknown',
  } as const;
  // Problems first in their own order, as before; stopped containers last.
  const ORDER = { crit: 0, warn: 0, ok: 1, none: 2 } as const;
  // A compose project takes the level of its worst container.
  const SEVERITY = { crit: 0, warn: 1, ok: 2, none: 3 } as const;

  type Container = DockerContainer;
  type Level = keyof typeof DOT;
  interface Note {
    key: string;
    vars: Record<string, unknown>;
  }
  interface Row {
    key: string;
    c: Container;
    level: Level;
    // null without a reason: the raw state, as before R-0419.
    note: Note | null;
  }
  interface Group {
    // null: the containers without a compose project.
    project: string | null;
    rows: Row[];
    level: Level;
    running: number;
  }
  interface Info {
    // The error's text key when the agent could not read docker; no rows then.
    unavailable: string | null;
    rows: Row[];
    // null: no container names a compose project (an agent before them), the flat list.
    groups: Group[] | null;
    total: number;
    crit: number;
    warn: number;
    running: number;
    stopped: number;
    allOk: boolean;
  }

  function note(c: Container): Note | null {
    const reason = c.reason;
    if (!reason) return null;
    const exit = /^exit:(-?\d+)$/.exec(reason);
    if (exit) return { key: 'monitoring.docker.reason.exit', vars: { code: exit[1] } };
    if (reason === 'restarted' && typeof c.restart_count === 'number') {
      return { key: 'monitoring.docker.reason.restarted', vars: { count: c.restart_count } };
    }
    // A code this UI does not know yet (a newer server) still says something.
    const key = REASON_KEY.get(reason) ?? 'monitoring.docker.reason.other';
    return { key, vars: { state: c.state } };
  }

  function groupsOf(rows: Row[]): Group[] | null {
    if (!rows.some((r) => r.c.compose_project)) return null;
    const projectOf = (r: Row) => r.c.compose_project || null;
    return [...new Set(rows.map(projectOf))]
      .map<Group>((project) => {
        const list = rows.filter((r) => projectOf(r) === project);
        return {
          project,
          rows: list,
          level: list.reduce<Level>(
            (w, r) => (SEVERITY[r.level] < SEVERITY[w] ? r.level : w),
            'none',
          ),
          running: list.filter((r) => r.c.state === 'running').length,
        };
      })
      .sort(
        (a, b) =>
          SEVERITY[a.level] - SEVERITY[b.level] ||
          Number(a.project === null) - Number(b.project === null) ||
          (a.project ?? '').localeCompare(b.project ?? ''),
      );
  }

  // Only for a running container: the start time of a stopped one says nothing about now.
  function uptime(c: Container): string | null {
    if (c.state !== 'running' || c.started_at === undefined) return null;
    return $t('monitoring.docker.upFor', { span: spanText($t, Date.now() / 1000 - c.started_at) });
  }

  function info(check: MonitorCheck): Info {
    const d = containerDetails(check.state?.details);
    // Rows are keyed by the container id (by name in details before R-0419), so
    // each container once, the first entry winning.
    const keyed = (d?.containers ?? []).map((c) => ({
      key: c.id ? `id:${c.id}` : `name:${c.name}`,
      c,
    }));
    const rows = keyed
      .filter((x, n) => keyed.findIndex((y) => y.key === x.key) === n)
      // A category this UI does not know yet stays neutral.
      .map<Row>(({ key, c }) => ({ key, c, level: LEVEL[c.category] ?? 'none', note: note(c) }))
      .sort((a, b) => ORDER[a.level] - ORDER[b.level]);
    const crit = rows.filter((r) => r.level === 'crit').length;
    const warn = rows.filter((r) => r.level === 'warn').length;
    return {
      unavailable:
        d?.available === false
          ? (ERROR_KEY.get(d.error ?? '') ?? 'monitoring.docker.error.unknown')
          : null,
      rows,
      groups: groupsOf(rows),
      total: rows.length,
      crit,
      warn,
      // The server rates exited/created containers as ok in details before
      // R-0419; the category alone does not say "running".
      running: rows.filter((r) => r.c.state === 'running').length,
      stopped: rows.filter((r) => r.c.category === 'stopped').length,
      allOk: crit === 0 && warn === 0,
    };
  }

  function countText(i: Info, all: 'monitoring.docker.allOk' | 'monitoring.docker.allOkHint') {
    if (i.stopped > 0) {
      return $t('monitoring.docker.runningStopped', { running: i.running, stopped: i.stopped });
    }
    if (i.running === i.total) return $t(all, { count: i.total });
    return $t('monitoring.docker.okRunning', { running: i.running, total: i.total });
  }

  // The colour comes from the effective status the line's dot shows, never above
  // the pill's own level: a first, damped failure and a single restart (details
  // only, Kevin 2026-10-17) leave the status ok, and then no pill turns yellow.
  function pill(check: MonitorCheck, level: 'ok' | 'warn' | 'crit'): string {
    const status = check.state?.status;
    if (level === 'ok') return status === 'ok' ? 'pill-ok' : '';
    if (status === 'critical') return level === 'crit' ? 'pill-crit' : 'pill-warn';
    if (status === 'warning') return 'pill-warn';
    return '';
  }
</script>

{#snippet containerRow(r: Row)}
  {@const up = uptime(r.c)}
  {@const ports = r.c.ports ?? []}
  <div class="mon-expand-row level-{r.level}">
    <span class="mon-dot {DOT[r.level]}"></span>
    {#if r.c.image}
      <span class="mon-expand-badge">{r.c.image.split(':')[0].split('/').pop()}</span>
    {/if}
    <span class="mon-expand-name">{r.c.name}</span>
    <span class="mon-expand-note">{r.note ? $t(r.note.key, r.note.vars) : r.c.state}</span>
  </div>
  {#if up !== null || ports.length > 0}
    <div class="mon-expand-names" data-container={r.key}>
      {#if up !== null}
        <span class="mon-expand-names-label" data-uptime>{up}</span>
      {/if}
      {#if ports.length > 0}
        <span class="mon-expand-names-label">{$t('monitoring.docker.ports')}</span>
        <!-- Keyed by position: a port text twice must not break the list. -->
        {#each ports as port, idx (idx)}
          <Tag tone="neutral" size="sm">{port}</Tag>
        {/each}
      {/if}
    </div>
  {/if}
{/snippet}

<section class="mon-section">
  <MonSectionHeader
    icon="docker"
    title={$t('monitoring.section.docker')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const i = info(check)}
      <MonCheckLine {check} showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          {#if i.unavailable}
            <span class="mon-line-pill {pill(check, 'crit')}" title={check.state?.message}
              >{$t(i.unavailable)}</span
            >
          {:else if i.total === 0}
            {#if check.state?.status === 'unknown'}
              <span class="mon-line-pill" title={check.state?.message}
                >{$t('monitoring.docker.noData')}</span
              >
            {:else}
              <span class="mon-line-pill">—</span>
            {/if}
          {:else if i.allOk}
            <span class="mon-line-pill {pill(check, 'ok')}"
              >{countText(i, 'monitoring.docker.allOk')}</span
            >
          {:else}
            {#if i.crit > 0}
              <span class="mon-line-pill {pill(check, 'crit')}">{i.crit} ✗</span>
            {/if}
            {#if i.warn > 0}
              <span class="mon-line-pill {pill(check, 'warn')}">{i.warn} ⚠</span>
            {/if}
            <span class="mon-line-pill">{countText(i, 'monitoring.docker.allOk')}</span>
          {/if}
        {/snippet}
        {#snippet extraBody()}
          {#if i.total > 0}
            <div class="mon-expand-list">
              {#if i.allOk}
                <div class="mon-expand-hint">{countText(i, 'monitoring.docker.allOkHint')}</div>
              {/if}
              {#if i.groups}
                {#each i.groups as g (g.project ?? '')}
                  <!-- A project with a problem starts open. -->
                  <details
                    class="mon-expand-group"
                    data-project={g.project ?? ''}
                    open={g.level === 'crit' || g.level === 'warn'}
                  >
                    <summary class="mon-expand-group-head level-{g.level}">
                      <span class="mon-dot {DOT[g.level]}"></span>
                      <span class="mon-expand-name"
                        >{g.project ?? $t('monitoring.docker.noProject')}</span
                      >
                      <span class="mon-expand-note"
                        >{$t('monitoring.docker.okRunning', {
                          running: g.running,
                          total: g.rows.length,
                        })}</span
                      >
                      <span class="mon-expand-group-chevron"><MonSectionIcon name="chevron" /></span
                      >
                    </summary>
                    <div class="mon-expand-group-body">
                      {#each g.rows as r (r.key)}
                        {@render containerRow(r)}
                      {/each}
                    </div>
                  </details>
                {/each}
              {:else}
                {#each i.rows as r (r.key)}
                  {@render containerRow(r)}
                {/each}
              {/if}
            </div>
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
