<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { worstStatus } from '$lib/models/monitoring';
  import MonSectionHeader from './MonSectionHeader.svelte';
  import MonCheckLine from './MonCheckLine.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    checks: MonitorCheck[];
  }
  let { checks }: Props = $props();

  let worst = $derived(worstStatus(checks));

  interface Svc {
    name: string;
    status: 'ok' | 'warn' | 'crit';
    note: string;
  }
  interface Info {
    total: number;
    problems: Svc[];
    running: number;
    allOk: boolean;
  }

  function info(check: MonitorCheck): Info {
    const d = (check.state?.details ?? null) as Record<string, unknown> | null;
    if (!d) return { total: 0, problems: [], running: 0, allOk: false };

    if (d.mode === 'auto') {
      const failed = (d.failed ?? []) as string[];
      const inactive = (d.enabled_inactive ?? []) as string[];
      const problems: Svc[] = [
        ...failed.map<Svc>((n) => ({ name: n, status: 'crit', note: 'failed' })),
        ...inactive.map<Svc>((n) => ({ name: n, status: 'warn', note: 'inactive' })),
      ];
      const countActive = Number(d.active_count ?? 0);
      return {
        total: countActive + problems.length,
        problems,
        running: countActive,
        allOk: problems.length === 0,
      };
    }

    const watched = (d.watched ?? []) as Array<{ name: string; running: boolean }>;
    const running = watched.filter((s) => s.running).length;
    const problems: Svc[] = watched
      .filter((s) => !s.running)
      .map<Svc>((s) => ({ name: s.name, status: 'crit', note: 'down' }));
    return { total: watched.length, problems, running, allOk: problems.length === 0 };
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
          {#if i.allOk}
            <span class="mon-line-pill pill-ok"
              >{$t('monitoring.services.allOk', { count: i.running })}</span
            >
          {:else}
            <span class="mon-line-pill pill-crit"
              >{i.problems.length} {$t('monitoring.services.problems')}</span
            >
            <span class="mon-line-pill"
              >{i.running}/{i.total} {$t('monitoring.services.running')}</span
            >
          {/if}
        {/snippet}
        {#snippet extraBody()}
          {#if i.allOk}
            <div class="mon-expand-list">
              <div class="mon-expand-hint">
                {$t('monitoring.services.allOkHint', { count: i.running })}
              </div>
            </div>
          {:else}
            <div class="mon-expand-list">
              {#each i.problems as s}
                <div class="mon-expand-row level-{s.status}">
                  <span class="mon-dot mon-{s.status === 'crit' ? 'critical' : 'warning'}"></span>
                  <span class="mon-expand-name">{s.name}</span>
                  <span class="mon-expand-note">{s.note}</span>
                </div>
              {/each}
            </div>
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
