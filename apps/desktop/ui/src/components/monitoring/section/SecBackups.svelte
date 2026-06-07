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

  interface Vm {
    vmid: string | number;
    name: string;
    type?: string;
    backupStatus: 'ok' | 'missing' | 'outdated';
    ageHours?: number;
  }
  interface Info {
    vms: Vm[];
    total: number;
    ok: number;
    outdated: number;
    missing: number;
    allOk: boolean;
  }

  function info(check: MonitorCheck): Info {
    const d = (check.state?.details ?? null) as Record<string, unknown> | null;
    const list = (d?.vms ?? []) as Vm[];
    let ok = 0,
      outdated = 0,
      missing = 0;
    for (const v of list) {
      if (v.backupStatus === 'missing') missing++;
      else if (v.backupStatus === 'outdated') outdated++;
      else ok++;
    }
    return {
      vms: list,
      total: list.length,
      ok,
      outdated,
      missing,
      allOk: missing === 0 && outdated === 0,
    };
  }
</script>

<section class="mon-section">
  <MonSectionHeader
    icon="backups"
    title={$t('monitoring.section.backups')}
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
              >{$t('monitoring.proxmox.allOk', { count: i.total })}</span
            >
          {:else}
            {#if i.missing > 0}
              <span class="mon-line-pill pill-crit"
                >{i.missing} {$t('monitoring.proxmox.missing')}</span
              >
            {/if}
            {#if i.outdated > 0}
              <span class="mon-line-pill pill-warn">{i.outdated} outdated</span>
            {/if}
            <span class="mon-line-pill">{i.ok}/{i.total}</span>
          {/if}
        {/snippet}
        {#snippet extraBody()}
          <div class="mon-expand-list">
            {#each [...i.vms].sort( (a) => (a.backupStatus === 'missing' ? -1 : a.backupStatus === 'outdated' ? 0 : 1), ) as v (v.vmid)}
              <div
                class="mon-expand-row level-{v.backupStatus === 'missing'
                  ? 'crit'
                  : v.backupStatus === 'outdated'
                    ? 'warn'
                    : 'ok'}"
              >
                <span
                  class="mon-dot mon-{v.backupStatus === 'missing'
                    ? 'critical'
                    : v.backupStatus === 'outdated'
                      ? 'warning'
                      : 'ok'}"
                ></span>
                <span class="mon-expand-badge">{(v.type || 'vm').toUpperCase()}</span>
                <span class="mon-expand-name"
                  >{v.name} <span class="mon-expand-muted">({v.vmid})</span></span
                >
                <span class="mon-expand-note">
                  {#if v.backupStatus === 'ok'}
                    {$t('monitoring.status.ok')}
                  {:else if v.backupStatus === 'missing'}
                    {$t('monitoring.proxmox.missing')}
                  {:else}
                    {$t('monitoring.proxmox.outdated', { hours: v.ageHours })}
                  {/if}
                </span>
              </div>
            {/each}
          </div>
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</section>
