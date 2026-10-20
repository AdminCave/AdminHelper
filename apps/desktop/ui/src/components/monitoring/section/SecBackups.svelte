<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheck, MonitorBackupDetails } from '$lib/api/types';
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
  const ERROR_KEY = new Map<string, string>([
    ['timeout', 'monitoring.proxmox.error.timeout'],
    ['cli_failed', 'monitoring.proxmox.error.cli_failed'],
    ['parse_failed', 'monitoring.proxmox.error.parse_failed'],
    ['backup_index_incomplete', 'monitoring.proxmox.error.backup_index_incomplete'],
  ]);
  // The colour comes from the status the line's dot shows: an outage is a
  // warning, and with the outage alert off (unknown) the pill stays grey.
  const OUTAGE_PILL = new Map<string, string>([
    ['critical', 'pill-crit'],
    ['warning', 'pill-warn'],
  ]);

  type Vm = NonNullable<MonitorBackupDetails['vms']>[number];
  interface Info {
    // The error's text key when the agent could not read Proxmox; no VMs then.
    unavailable: string | null;
    vms: Vm[];
    total: number;
    ok: number;
    outdated: number;
    missing: number;
    allOk: boolean;
  }

  // Read loosely: only the types the checker writes count. A check switched to
  // this type keeps the details of its old type until the next push.
  type LooseDetails = { [K in keyof MonitorBackupDetails]?: unknown };

  function unavailableOf(d: LooseDetails): string | null {
    // Only a JSON false is an outage, as for the checker.
    if (d.available !== false) return null;
    // A code this UI does not know yet (a newer agent) still says something.
    const key = typeof d.error === 'string' ? ERROR_KEY.get(d.error) : undefined;
    return key ?? 'monitoring.proxmox.error.unknown';
  }

  function vmsOf(d: LooseDetails): Vm[] {
    const raw: unknown[] = Array.isArray(d.vms) ? d.vms : [];
    const vms = raw.filter((v): v is Vm => typeof v === 'object' && v !== null);
    // The VM rows are keyed by the VMID: each VM once, the first entry winning.
    return vms.filter((v, n) => vms.findIndex((w) => w.vmid === v.vmid) === n);
  }

  function info(check: MonitorCheck): Info {
    const d = (check.state?.details ?? {}) as LooseDetails;
    const unavailable = unavailableOf(d);
    const list = unavailable ? [] : vmsOf(d);
    let ok = 0,
      outdated = 0,
      missing = 0;
    for (const v of list) {
      if (v.backupStatus === 'missing') missing++;
      else if (v.backupStatus === 'outdated') outdated++;
      else ok++;
    }
    return {
      unavailable,
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
          {#if i.unavailable}
            <span
              class="mon-line-pill {OUTAGE_PILL.get(check.state?.status ?? '') ?? ''}"
              title={check.state?.message}>{$t(i.unavailable)}</span
            >
          {:else if i.total === 0}
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
