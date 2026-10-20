<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck, MonitorSystemStateDetails } from '$lib/api/types';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  type Key = 'reboot' | 'time_sync' | 'security_updates' | 'oom';
  type Level = 'ok' | 'warn' | 'none';

  // Spelled out: the i18n "no unused keys" guard only sees quoted keys.
  const PROBLEM_KEY = new Map<string, string>([
    ['reboot', 'monitoring.system.problem.reboot'],
    ['time_sync', 'monitoring.system.problem.time_sync'],
    ['security_updates', 'monitoring.system.problem.security_updates'],
    ['oom', 'monitoring.system.problem.oom'],
  ]);
  const POINT_KEY: Record<Key, string> = {
    reboot: 'monitoring.system.point.reboot',
    time_sync: 'monitoring.system.point.time_sync',
    security_updates: 'monitoring.system.point.security_updates',
    oom: 'monitoring.system.point.oom',
  };
  // The colour comes from the status the line's dot shows: a first, still
  // damped problem leaves it ok, and then the pill stays grey.
  const PROBLEM_PILL = new Map<string, string>([
    ['critical', 'pill-crit'],
    ['warning', 'pill-warn'],
  ]);
  const DOT: Record<Level, string> = { ok: 'mon-ok', warn: 'mon-warning', none: 'mon-unknown' };

  interface Point {
    key: Key;
    // null: the agent could not determine the point.
    value: string | null;
    level: Level;
  }
  interface Pill {
    key: string;
    text: string;
  }
  interface Info {
    // false: no details yet.
    reported: boolean;
    pills: Pill[];
    points: Point[];
    // false: details without a single value (agent before report version 3, Windows).
    evaluated: boolean;
  }

  // Read loosely: only the types the checker writes count, anything else is not
  // determined. A check switched to this type keeps the details of its old type
  // until the next push (agent_resources: problems is a map there).
  type LooseDetails = { [K in keyof MonitorSystemStateDetails]?: unknown };

  function asFlag(v: unknown): boolean | null {
    return typeof v === 'boolean' ? v : null;
  }
  function asCount(v: unknown): number | null {
    return typeof v === 'number' && Number.isInteger(v) ? v : null;
  }

  function yesNo(v: boolean): string {
    return $t(v ? 'monitoring.system.yes' : 'monitoring.system.no');
  }

  function problemText(key: string, updates: number | null, ooms: number | null): string {
    const textKey = PROBLEM_KEY.get(key);
    // A point this UI does not know yet (a newer server) shows by its raw name.
    if (!textKey) return key;
    const count = key === 'security_updates' ? updates : key === 'oom' ? ooms : null;
    return $t(textKey, { count });
  }

  function info(check: MonitorCheck): Info {
    const d = (check.state?.details ?? null) as LooseDetails | null;
    if (!d) return { reported: false, pills: [], points: [], evaluated: false };
    const reboot = asFlag(d.reboot_required);
    const synced = asFlag(d.time_synchronized);
    const updates = asCount(d.security_updates);
    const ooms = asCount(d.oom_kills);
    const named: unknown[] = Array.isArray(d.problems) ? d.problems : [];
    // Each once: a name twice would break the keyed pill list.
    const problems = [...new Set(named.filter((p): p is string => typeof p === 'string'))];
    // The checker's rating decides the colour. A bad value it does not name
    // (point switched off, clock in the first 15 minutes of uptime) is no
    // problem, but no green either.
    const point = (key: Key, value: string | null, good: boolean): Point => ({
      key,
      value,
      level: problems.includes(key) ? 'warn' : value !== null && good ? 'ok' : 'none',
    });
    const points = [
      point('reboot', reboot === null ? null : yesNo(reboot), reboot === false),
      point('time_sync', synced === null ? null : yesNo(synced), synced === true),
      point('security_updates', updates === null ? null : String(updates), updates === 0),
      point('oom', ooms === null ? null : String(ooms), ooms === 0),
    ];
    return {
      reported: true,
      pills: problems.map((key) => ({ key, text: problemText(key, updates, ooms) })),
      points,
      evaluated: points.some((p) => p.value !== null),
    };
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="power"
    title={$t('monitoring.section.system')}
    {worst}
    count={checks.length}
  />

  <div class="mon-section-body">
    {#each checks as check (check.id)}
      {@const i = info(check)}
      {@const status = check.state?.status ?? ''}
      <MonCheckLine {check} showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
        {/snippet}
        {#snippet value()}
          {#if !i.reported}
            <span class="mon-line-pill">—</span>
          {:else if !i.evaluated}
            <span class="mon-line-pill" title={check.state?.message}
              >{$t('monitoring.system.notEvaluated')}</span
            >
          {:else if i.pills.length === 0}
            <span class="mon-line-pill {status === 'ok' ? 'pill-ok' : ''}"
              >{$t('monitoring.system.allOk')}</span
            >
          {:else}
            {#each i.pills as p (p.key)}
              <span class="mon-line-pill {PROBLEM_PILL.get(status) ?? ''}">{p.text}</span>
            {/each}
          {/if}
        {/snippet}
        {#snippet extraBody()}
          {#if i.evaluated}
            <div class="mon-expand-list">
              {#each i.points as p (p.key)}
                <div class="mon-expand-row level-{p.level}">
                  <span class="mon-dot {DOT[p.level]}"></span>
                  <span class="mon-expand-name">{$t(POINT_KEY[p.key])}</span>
                  <span class="mon-expand-note"
                    >{p.value ?? $t('monitoring.system.notDetermined')}</span
                  >
                </div>
              {/each}
            </div>
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
