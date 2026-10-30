<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { serviceDetails } from '$lib/models/checkDetails';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  // Spelled out: the i18n "no unused keys" guard only sees quoted keys.
  const NOTE_KEY = {
    failed: 'monitoring.services.note.failed',
    inactive: 'monitoring.services.note.inactive',
    down: 'monitoring.services.note.down',
    nodata: 'monitoring.services.note.nodata',
  } as const;
  const DOT = { crit: 'mon-critical', warn: 'mon-warning', none: 'mon-unknown' } as const;

  interface Svc {
    name: string;
    // none: a watched name without data, neither down nor running.
    level: keyof typeof DOT;
    note: keyof typeof NOTE_KEY;
  }
  type Neutral = 'monitoring.services.noData' | 'monitoring.services.unknown';
  interface Info {
    // The text of a neutral pill instead of the counts: noData without details,
    // unknown without a problem in a status other than ok (systemctl failed, no
    // watched name has data). Nothing honest to count in either case.
    neutral: Neutral | null;
    rows: Svc[];
    problems: number;
    count: { n: number; of: number; key: string } | null;
  }

  // Rows are keyed by name, so each name once, the first entry winning. Older
  // configurations may list a name twice, and the agent's failed and
  // enabled_inactive come from two systemctl calls a unit can fail between.
  function uniqueByName<T extends { name: string }>(list: T[]): T[] {
    return list.filter((x, i) => list.findIndex((y) => y.name === x.name) === i);
  }

  // The unit type suffixes of _UNIT_TYPES in the checker (checkers/agent.py,
  // systemd.unit(5)). As there, only a failed .service or a name without one of
  // them (a Windows service) is critical, any other failed unit warning.
  const UNIT_TYPES = [
    '.service',
    '.socket',
    '.device',
    '.mount',
    '.automount',
    '.swap',
    '.target',
    '.path',
    '.timer',
    '.slice',
    '.scope',
  ];

  function failedLevel(name: string): Svc['level'] {
    const service = name.endsWith('.service') || !UNIT_TYPES.some((s) => name.endsWith(s));
    return service ? 'crit' : 'warn';
  }

  function info(check: MonitorCheck): Info {
    const d = serviceDetails(check.state?.details);
    if (!d) return { neutral: 'monitoring.services.noData', rows: [], problems: 0, count: null };
    const status = check.state?.status;
    const neutral = (problems: number): Neutral | null =>
      problems === 0 && status !== 'ok' ? 'monitoring.services.unknown' : null;

    if (d.mode === 'auto') {
      const rows = uniqueByName<Svc>([
        ...(d.failed ?? []).map<Svc>((n) => ({ name: n, level: failedLevel(n), note: 'failed' })),
        ...(d.enabled_inactive ?? []).map<Svc>((n) => ({
          name: n,
          level: 'warn',
          note: 'inactive',
        })),
      ]);
      // Agents before R-0418 send no counts: then the problem count alone, no "x/y".
      const { active_count: n, total: of } = d;
      return {
        neutral: neutral(rows.length),
        rows,
        problems: rows.length,
        count:
          typeof n === 'number' && typeof of === 'number'
            ? { n, of, key: 'monitoring.services.active' }
            : null,
      };
    }

    // Details written before R-0418 carry running alone; false meant down then.
    const watched = uniqueByName(
      (d.watched ?? []).map((s) => ({
        name: s.name,
        state: s.state ?? (s.running ? 'running' : 'down'),
      })),
    );
    const down = watched
      .filter((s) => s.state === 'down')
      .map<Svc>((s) => ({ name: s.name, level: 'crit', note: 'down' }));
    const nodata = watched
      .filter((s) => s.state === 'nodata')
      .map<Svc>((s) => ({ name: s.name, level: 'none', note: 'nodata' }));
    return {
      neutral: neutral(down.length),
      rows: [...down, ...nodata],
      problems: down.length,
      count: {
        n: watched.filter((s) => s.state === 'running').length,
        of: watched.length,
        key: 'monitoring.services.running',
      },
    };
  }

  // The dot's source, the effective status: the raw problems of a first, still
  // damped failure leave it ok, and then the pill must not turn red either.
  function problemPill(check: MonitorCheck): string {
    const status = check.state?.status;
    if (status === 'critical') return 'pill-crit';
    if (status === 'warning') return 'pill-warn';
    return '';
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="services"
    title={$t('monitoring.section.services')}
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
          {#if i.neutral}
            <span class="mon-line-pill" title={check.state?.message}>{$t(i.neutral)}</span>
          {:else}
            {#if i.problems > 0}
              <span class="mon-line-pill {problemPill(check)}"
                >{i.problems} {$t('monitoring.services.problems')}</span
              >
            {:else}
              <span class="mon-line-pill pill-ok">{$t('monitoring.services.allOk')}</span>
            {/if}
            {#if i.count}
              <span class="mon-line-pill">{i.count.n}/{i.count.of} {$t(i.count.key)}</span>
            {/if}
          {/if}
        {/snippet}
        {#snippet extraBody()}
          {#if i.rows.length > 0}
            <div class="mon-expand-list">
              {#each i.rows as s (s.name)}
                <div class="mon-expand-row level-{s.level}">
                  <span class="mon-dot {DOT[s.level]}"></span>
                  <span class="mon-expand-name">{s.name}</span>
                  <span class="mon-expand-note">{$t(NOTE_KEY[s.note])}</span>
                </div>
              {/each}
            </div>
          {:else if !i.neutral}
            <div class="mon-expand-list">
              <div class="mon-expand-hint">{$t('monitoring.services.allOkHint')}</div>
            </div>
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
