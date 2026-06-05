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

  interface Container {
    name: string;
    image?: string;
    state: string;
    category: 'ok' | 'warning' | 'critical';
  }
  interface Info {
    containers: Container[];
    total: number;
    ok: number;
    warn: number;
    crit: number;
    allOk: boolean;
  }

  function info(check: MonitorCheck): Info {
    const d = (check.state?.details ?? null) as Record<string, unknown> | null;
    const list = (d?.containers ?? []) as Container[];
    let ok = 0,
      warn = 0,
      crit = 0;
    for (const c of list) {
      if (c.category === 'critical') crit++;
      else if (c.category === 'warning') warn++;
      else ok++;
    }
    return {
      containers: list,
      total: list.length,
      ok,
      warn,
      crit,
      allOk: crit === 0 && warn === 0,
    };
  }
</script>

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
          {#if i.total === 0}
            <span class="mon-line-pill">—</span>
          {:else if i.allOk}
            <span class="mon-line-pill pill-ok"
              >{$t('monitoring.docker.allOk', { count: i.total })}</span
            >
          {:else}
            {#if i.crit > 0}
              <span class="mon-line-pill pill-crit">{i.crit} ✗</span>
            {/if}
            {#if i.warn > 0}
              <span class="mon-line-pill pill-warn">{i.warn} ⚠</span>
            {/if}
            <span class="mon-line-pill">{i.ok}/{i.total}</span>
          {/if}
        {/snippet}
        {#snippet extraBody()}
          {#if i.allOk && i.total > 0}
            <div class="mon-expand-list">
              <div class="mon-expand-hint">
                {$t('monitoring.docker.allOkHint', { count: i.total })}
              </div>
              {#each i.containers as c}
                <div class="mon-expand-row level-ok">
                  <span class="mon-dot mon-ok"></span>
                  {#if c.image}
                    <span class="mon-expand-badge">{c.image.split(':')[0].split('/').pop()}</span>
                  {/if}
                  <span class="mon-expand-name">{c.name}</span>
                  <span class="mon-expand-note">{c.state}</span>
                </div>
              {/each}
            </div>
          {:else}
            <div class="mon-expand-list">
              {#each i.containers.filter((c) => c.category !== 'ok') as c}
                <div class="mon-expand-row level-{c.category === 'critical' ? 'crit' : 'warn'}">
                  <span class="mon-dot mon-{c.category}"></span>
                  {#if c.image}
                    <span class="mon-expand-badge">{c.image.split(':')[0].split('/').pop()}</span>
                  {/if}
                  <span class="mon-expand-name">{c.name}</span>
                  <span class="mon-expand-note">{c.state}</span>
                </div>
              {/each}
              {#each i.containers.filter((c) => c.category === 'ok') as c}
                <div class="mon-expand-row level-ok">
                  <span class="mon-dot mon-ok"></span>
                  {#if c.image}
                    <span class="mon-expand-badge">{c.image.split(':')[0].split('/').pop()}</span>
                  {/if}
                  <span class="mon-expand-name">{c.name}</span>
                  <span class="mon-expand-note">{c.state}</span>
                </div>
              {/each}
            </div>
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
