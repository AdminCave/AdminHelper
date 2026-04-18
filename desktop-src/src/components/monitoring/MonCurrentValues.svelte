<script lang="ts">
  import type { MonitoringMetricsResponse } from '$lib/api/types';
  import { checkTypeUnit } from '$lib/models/monitoring';

  interface Props {
    metrics: MonitoringMetricsResponse | null;
    checkType: string;
  }
  let { metrics, checkType }: Props = $props();

  interface Entry { label: string; value: string; }

  let entries = $derived.by<Entry[]>(() => {
    const results = metrics?.data ?? [];
    if (results.length === 0) return [];
    const unit = checkTypeUnit(checkType);
    const out: Entry[] = [];
    for (const series of results) {
      const name = series.metric?.__name__ || '';
      if (name.includes('status')) continue;
      const values = series.values || [];
      if (values.length === 0) continue;
      const last = parseFloat(values[values.length - 1][1]);
      if (Number.isNaN(last)) continue;
      const label = name
        .replace('monitor_check_', '')
        .replace('monitor_agent_', '')
        .replace('monitor_', '')
        .replace(/_value$/, '')
        .replace(/_/g, ' ');
      const formatted = Number.isInteger(last) ? String(last) : last.toFixed(1);
      out.push({ label, value: `${formatted}${unit}` });
    }
    return out;
  });
</script>

{#if entries.length > 0}
  <div class="mon-detail-current">
    {#each entries as e}
      <span class="mon-current-item"><strong>{e.label}</strong> {e.value}</span>
    {/each}
  </div>
{/if}
