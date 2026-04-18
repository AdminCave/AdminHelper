<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  let details = $derived((check.state?.details ?? null) as Record<string, unknown> | null);
  let config = $derived((check.config ?? {}) as Record<string, unknown>);

  function gaugeClass(pct: number, warn: number, crit: number): string {
    if (pct >= crit) return 'gauge-crit';
    if (pct >= warn) return 'gauge-warn';
    return 'gauge-ok';
  }

  function num(v: unknown, fallback = 0): number {
    const n = Number(v);
    return Number.isNaN(n) ? fallback : n;
  }

  // agent_resources — Gauges für CPU/RAM/Disk
  let resourceGauges = $derived.by(() => {
    if (check.checkType !== 'agent_resources' || !details) return [];
    const cpuWarn = num(config.cpu_warn, 80);
    const cpuCrit = num(config.cpu_crit, 95);
    const memWarn = num(config.memory_warn, 80);
    const memCrit = num(config.memory_crit, 95);
    const diskWarn = num(config.disk_warn, 85);
    const diskCrit = num(config.disk_crit, 95);
    const items: Array<{ label: string; pct: number; detail: string | null; cls: string }> = [];

    if (details.cpu != null) {
      const pct = num(details.cpu);
      items.push({ label: 'CPU', pct, detail: null, cls: gaugeClass(pct, cpuWarn, cpuCrit) });
    }
    if (details.memory != null) {
      const pct = num(details.memory);
      const detail = details.memory_total_mb
        ? `${num(details.memory_used_mb)} / ${num(details.memory_total_mb)} MB`
        : null;
      items.push({ label: 'RAM', pct, detail, cls: gaugeClass(pct, memWarn, memCrit) });
    }
    const disks = (details.disks ?? []) as Array<Record<string, unknown>>;
    for (const d of disks) {
      const pct = num(d.percent);
      const detail = d.total_gb != null
        ? `${num(d.used_gb).toFixed(1)} / ${num(d.total_gb).toFixed(1)} GB`
        : null;
      items.push({ label: String(d.mount ?? '?'), pct, detail, cls: gaugeClass(pct, diskWarn, diskCrit) });
    }
    return items;
  });

  // service_process
  let serviceAuto = $derived.by(() => {
    if (check.checkType !== 'service_process' || !details || details.mode !== 'auto') return null;
    return {
      failed: (details.failed ?? []) as string[],
      inactive: (details.enabled_inactive ?? []) as string[],
    };
  });
  let serviceList = $derived.by(() => {
    if (check.checkType !== 'service_process' || !details || details.mode === 'auto') return null;
    return (details.watched ?? []) as Array<{ name: string; running: boolean }>;
  });

  // docker_health
  let containers = $derived.by(() => {
    if (check.checkType !== 'docker_health') return null;
    const list = (details?.containers ?? []) as Array<{
      name: string;
      image?: string;
      state: string;
      category: 'ok' | 'warning' | 'critical';
    }>;
    if (list.length === 0) return null;
    const order = { critical: 0, warning: 1, ok: 2 } as Record<string, number>;
    const sorted = [...list].sort((a, b) => (order[a.category] ?? 2) - (order[b.category] ?? 2));
    const allOk = sorted.every((c) => c.category === 'ok');
    return { sorted, allOk, total: sorted.length };
  });

  // proxmox_backup
  let vms = $derived.by(() => {
    if (check.checkType !== 'proxmox_backup') return null;
    const list = (details?.vms ?? []) as Array<{
      vmid: string | number;
      name: string;
      type?: string;
      backupStatus: 'ok' | 'missing' | 'outdated';
      ageHours?: number;
    }>;
    if (list.length === 0) return null;
    const order = { missing: 0, outdated: 1, ok: 2 } as Record<string, number>;
    const sorted = [...list].sort((a, b) => (order[a.backupStatus] ?? 2) - (order[b.backupStatus] ?? 2));
    const allOk = sorted.every((v) => v.backupStatus === 'ok');
    return { sorted, allOk, total: sorted.length };
  });

  // zfs_health
  let zfsPools = $derived.by(() => {
    if (check.checkType !== 'zfs_health') return null;
    return (details?.pools ?? []) as Array<{ name: string; health: string; capacityPercent: number }>;
  });

  // smart_health
  let smartDisks = $derived.by(() => {
    if (check.checkType !== 'smart_health') return null;
    return (details?.disks ?? []) as Array<Record<string, unknown>>;
  });

  function smartSecondary(d: Record<string, unknown>): string {
    const hours = num(d.power_on_hours);
    const hoursStr = hours > 0 ? `${hours.toLocaleString('de-DE')} h` : null;
    if (d.kind === 'NVMe') {
      const parts: string[] = [];
      if (d.available_spare_pct != null) parts.push(`Spare ${d.available_spare_pct}%`);
      if (d.percentage_used != null) parts.push(`Wear ${d.percentage_used}%`);
      if (hoursStr) parts.push(hoursStr);
      return parts.join(' | ');
    }
    const parts: string[] = [];
    const realloc = num(d.reallocated_sectors);
    const pending = num(d.pending_sectors);
    if (realloc > 0) parts.push(`Realloc ${realloc}`);
    if (pending > 0) parts.push(`Pending ${pending}`);
    if (hoursStr) parts.push(hoursStr);
    return parts.join(' | ');
  }

  function smartBadge(cat: string): { cls: string; text: string } {
    if (cat === 'critical') return { cls: 'health-faulted', text: 'CRIT' };
    if (cat === 'warning') return { cls: 'health-degraded', text: 'WARN' };
    return { cls: 'health-online', text: 'OK' };
  }

  // agent_ping
  let agentPingSeconds = $derived.by(() => {
    if (check.checkType !== 'agent_ping') return null;
    const msg = check.state?.message || '';
    const match = msg.match(/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  });
  let agentPingDisplay = $derived(
    agentPingSeconds == null
      ? null
      : agentPingSeconds < 120
        ? `${agentPingSeconds}s`
        : `${Math.round(agentPingSeconds / 60)}m`,
  );
</script>

{#if check.checkType === 'agent_resources' && resourceGauges.length > 0}
  <div class="mon-gauge-grid">
    {#each resourceGauges as g}
      <div class="mon-gauge-item">
        <span class="mon-gauge-label">{g.label}</span>
        <div class="mon-gauge-bar">
          <div class="mon-gauge-fill {g.cls}" style="width:{Math.min(g.pct, 100)}%"></div>
          <span class="mon-gauge-text">{g.pct.toFixed(1)}%</span>
        </div>
        {#if g.detail}<span class="mon-gauge-detail">{g.detail}</span>{/if}
      </div>
    {/each}
  </div>
{/if}

{#if serviceAuto}
  {#if serviceAuto.failed.length === 0 && serviceAuto.inactive.length === 0}
    <div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle Units OK</div>
  {:else}
    <div class="mon-item-list">
      {#if serviceAuto.failed.length > 0}
        <div class="mon-section-title">Failed</div>
        {#each serviceAuto.failed as svc}
          <div class="mon-item-row">
            <span class="mon-item-dot item-crit"></span>
            <span class="mon-item-name">{svc}</span>
            <span class="mon-item-status">failed</span>
          </div>
        {/each}
      {/if}
      {#if serviceAuto.inactive.length > 0}
        <div class="mon-section-title">Inaktiv (Autostart)</div>
        {#each serviceAuto.inactive as svc}
          <div class="mon-item-row">
            <span class="mon-item-dot item-warn"></span>
            <span class="mon-item-name">{svc}</span>
            <span class="mon-item-status">inactive</span>
          </div>
        {/each}
      {/if}
    </div>
  {/if}
{/if}

{#if serviceList && serviceList.length > 0}
  <div class="mon-item-list">
    {#each serviceList as svc}
      <div class="mon-item-row">
        <span class="mon-item-dot {svc.running ? 'item-ok' : 'item-crit'}"></span>
        <span class="mon-item-name">{svc.name}</span>
        <span class="mon-item-status">{svc.running ? 'running' : 'down'}</span>
      </div>
    {/each}
  </div>
{/if}

{#if containers}
  {#if containers.allOk}
    <div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle {containers.total} Container laufen</div>
  {:else}
    <div class="mon-item-list">
      {#each containers.sorted as c}
        <div class="mon-item-row">
          <span class="mon-item-dot {c.category === 'critical' ? 'item-crit' : c.category === 'warning' ? 'item-warn' : 'item-ok'}"></span>
          {#if c.image}
            <span class="mon-item-badge">{c.image.split(':')[0].split('/').pop()}</span>
          {/if}
          <span class="mon-item-name">{c.name}</span>
          <span class="mon-item-status">{c.state}</span>
        </div>
      {/each}
    </div>
  {/if}
{/if}

{#if vms}
  {#if vms.allOk}
    <div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle {vms.total} VMs/CTs haben aktuelle Backups</div>
  {:else}
    <div class="mon-item-list">
      {#each vms.sorted as v}
        <div class="mon-item-row">
          <span class="mon-item-dot {v.backupStatus === 'missing' ? 'item-crit' : v.backupStatus === 'outdated' ? 'item-warn' : 'item-ok'}"></span>
          <span class="mon-item-badge">{(v.type || 'vm').toUpperCase()}</span>
          <span class="mon-item-name">{v.name} ({v.vmid})</span>
          <span class="mon-item-status">
            {v.backupStatus === 'ok'
              ? 'OK'
              : v.backupStatus === 'missing'
                ? 'Kein Backup'
                : `Veraltet (${v.ageHours}h)`}
          </span>
        </div>
      {/each}
    </div>
  {/if}
{/if}

{#if zfsPools && zfsPools.length > 0}
  <div class="mon-gauge-grid">
    {#each zfsPools as pool}
      <div class="mon-gauge-item">
        <span class="mon-gauge-label">{pool.name}</span>
        <div class="mon-gauge-bar">
          <div
            class="mon-gauge-fill {gaugeClass(pool.capacityPercent, 80, 90)}"
            style="width:{Math.min(pool.capacityPercent, 100)}%"
          ></div>
          <span class="mon-gauge-text">{pool.capacityPercent}%</span>
        </div>
        <span
          class="mon-health-badge {pool.health === 'ONLINE'
            ? 'health-online'
            : pool.health === 'DEGRADED'
              ? 'health-degraded'
              : 'health-faulted'}"
        >{pool.health}</span>
      </div>
    {/each}
  </div>
{/if}

{#if smartDisks && smartDisks.length > 0}
  <div class="mon-gauge-grid">
    {#each smartDisks as d}
      {@const temp = num(d.temp_c)}
      {@const tempWarn = num(d.temp_warn) || 60}
      {@const tempCrit = num(d.temp_crit) || 70}
      {@const tempPct = Math.min((temp / tempCrit) * 100, 100)}
      {@const badge = smartBadge(String(d.category ?? 'ok'))}
      {@const cwBits = Array.isArray(d.critical_warning_bits) ? (d.critical_warning_bits as string[]) : []}
      {@const secondary = smartSecondary(d)}
      <div class="mon-gauge-item">
        <span class="mon-gauge-label">{d.device} [{d.kind || d.protocol || 'Disk'}]</span>
        <div class="mon-gauge-bar">
          <div class="mon-gauge-fill {gaugeClass(temp, tempWarn, tempCrit)}" style="width:{tempPct}%"></div>
          <span class="mon-gauge-text">{temp}°C</span>
        </div>
        <span class="mon-gauge-detail">{d.model || ''}</span>
        {#if secondary}<span class="mon-gauge-detail">{secondary}</span>{/if}
        {#if cwBits.length > 0}
          <span class="mon-gauge-detail" style="color: var(--status-crit);">{cwBits.join(', ')}</span>
        {/if}
        <span class="mon-health-badge {badge.cls}">{badge.text}</span>
      </div>
    {/each}
  </div>
{/if}

{#if agentPingDisplay}
  <div class="mon-last-seen">
    <span class="mon-last-seen-value">{agentPingDisplay}</span>
    <span class="mon-last-seen-unit">zuletzt gesehen</span>
  </div>
{/if}
