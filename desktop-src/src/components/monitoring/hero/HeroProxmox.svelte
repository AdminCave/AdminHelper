<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import { t } from '$lib/i18n';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let details = $derived((check.state?.details ?? null) as Record<string, unknown> | null);

  let vms = $derived.by(() => {
    return (details?.vms ?? []) as Array<{
      vmid: string | number;
      name: string;
      type?: string;
      backupStatus: 'ok' | 'missing' | 'outdated';
      ageHours?: number;
    }>;
  });

  let stats = $derived.by(() => {
    const s = { total: vms.length, ok: 0, outdated: 0, missing: 0 };
    for (const v of vms) {
      if (v.backupStatus === 'missing') s.missing += 1;
      else if (v.backupStatus === 'outdated') s.outdated += 1;
      else s.ok += 1;
    }
    return s;
  });

  let problems = $derived(
    [...vms]
      .filter((v) => v.backupStatus !== 'ok')
      .sort((a) => (a.backupStatus === 'missing' ? -1 : 1)),
  );
</script>

<div class="mon-hero mon-hero-count">
  {#if stats.total === 0}
    <span class="mon-hero-empty">—</span>
  {:else if stats.missing === 0 && stats.outdated === 0}
    <div class="mon-hero-main">
      <span class="mon-hero-value mon-hero-ok">✓</span>
      <span class="mon-hero-fraction">{stats.total}</span>
    </div>
    <span class="mon-hero-sub">{$t('monitoring.proxmox.allOk', { count: stats.total })}</span>
  {:else}
    <div class="mon-hero-main">
      <span class="mon-hero-value">{stats.ok}</span>
      <span class="mon-hero-fraction">/ {stats.total}</span>
    </div>
    <div class="mon-hero-badge-row">
      {#if stats.missing > 0}
        <span class="mon-chip chip-crit">{stats.missing} {$t('monitoring.proxmox.missing')}</span>
      {/if}
      {#if stats.outdated > 0}
        <span class="mon-chip chip-warn">{stats.outdated} outdated</span>
      {/if}
    </div>
    <div class="mon-chip-row">
      {#each problems.slice(0, 6) as v}
        <span class="mon-chip chip-{v.backupStatus === 'missing' ? 'crit' : 'warn'}">
          {(v.type || 'vm').toUpperCase()} {v.name}
        </span>
      {/each}
      {#if problems.length > 6}
        <span class="mon-chip chip-muted">+{problems.length - 6}</span>
      {/if}
    </div>
  {/if}
</div>
