<script lang="ts">
  import { sessionStore } from '$lib/stores/session';
  import { monitoringApi } from '$lib/api/monitoring';
  import { formatCheckConfig } from '$lib/models/monitoring';
  import type { MonitorCheck, MonitoringMetricsResponse } from '$lib/api/types';
  import MonChart from './MonChart.svelte';
  import TypeContent from './detail/TypeContent.svelte';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();

  const PERIODS = ['1h', '6h', '24h', '7d'] as const;
  const NO_CHART_TYPES = ['service_process', 'docker_health', 'proxmox_backup'];

  let activePeriod = $state<(typeof PERIODS)[number]>('1h');
  let metrics = $state<MonitoringMetricsResponse | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  let configKV = $derived(formatCheckConfig(check));
  let skipChart = $derived(
    NO_CHART_TYPES.includes(check.checkType) ||
      (check.checkType === 'agent_resources' && check.state?.details != null),
  );

  async function load(): Promise<void> {
    const { session } = $sessionStore;
    if (!session) return;
    loading = true;
    error = null;
    try {
      metrics = await monitoringApi.fetchMetrics(session, check.id, activePeriod);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      metrics = null;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (skipChart) return;
    void load();
  });

  function setPeriod(p: (typeof PERIODS)[number]): void {
    activePeriod = p;
  }
</script>

<div class="mon-detail-panel" data-check-id={check.id}>
  <div class="mon-detail-info">
    <strong>{check.name}</strong> &mdash; {check.checkType.toUpperCase()}
    {#if check.description}
      <div class="mon-detail-desc">{check.description}</div>
    {/if}
    {#if configKV.length > 0}
      <div class="mon-detail-config">
        {#each configKV as [k, v], i}
          <span class="mon-cfg-key">{k}:</span>
          <span class="mon-cfg-val">{v}</span>
          {#if i < configKV.length - 1}
            <span> · </span>
          {/if}
        {/each}
      </div>
    {/if}
  </div>

  <div class="mon-type-content">
    <TypeContent {check} />
  </div>

  {#if !skipChart}
    <div class="mon-period-selector">
      {#each PERIODS as p}
        <button
          class="chip"
          class:active={p === activePeriod}
          onclick={() => setPeriod(p)}
        >
          {p}
        </button>
      {/each}
    </div>

    {#if loading}
      <div class="mon-chart-loading">Lade…</div>
    {:else if error}
      <div class="mon-chart-loading">Fehler beim Laden</div>
    {:else}
      <MonChart {metrics} checkType={check.checkType} />
    {/if}
  {/if}
</div>
