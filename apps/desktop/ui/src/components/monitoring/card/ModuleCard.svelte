<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCatalogModule, MonitorCheck } from '$lib/api/types';
  import { t } from '$lib/i18n';
  import { probeDetails } from '$lib/models/checkDetails';
  import { worstStatus } from '$lib/models/monitoring';
  import { cardNote, cardSummary, probeStatusText, valueText } from '$lib/models/monitoringText';
  import Badge from '../../ui/Badge.svelte';
  import MonCheckLine from '../section/MonCheckLine.svelte';
  import MonCard, { opensByDefault } from './MonCard.svelte';

  interface Props {
    /** The catalog's module; null while the catalog is not loaded or once it dropped the module. */
    module: MonitorCatalogModule | null;
    moduleId: string;
    instance: string;
    /** The instance's checks, all on one server. */
    checks: MonitorCheck[];
  }

  let { module, moduleId, instance, checks }: Props = $props();

  const name = $derived(module?.name ?? moduleId);
  // A single-instance module's instance key repeats the module id: not shown twice.
  const title = $derived(instance && instance !== moduleId ? `${name} · ${instance}` : name);
  const status = $derived(worstStatus(checks));

  // What a check says beyond its dot: why its sensor delivered nothing, else the first
  // rule it broke. The checker's raw message stays in the expanded row.
  function problemText(check: MonitorCheck): string | null {
    const details = probeDetails(check.state?.details);
    if (details?.status && details.status !== 'ok') return probeStatusText($t, details.status);
    return details?.problems?.[0] ?? null;
  }

  // The catalog's figures (`card`), each read from the instance's check it names; a
  // figure of a check the instance does not have (not adopted, deleted) is left out.
  const figures = $derived(
    (module?.card ?? []).flatMap((entry) => {
      const check = checks.find((c) => c.moduleCheckKey === entry.checkKey);
      if (!check) return [];
      const value = probeDetails(check.state?.details)?.values?.[entry.field];
      return [
        {
          key: `${entry.checkKey}/${entry.field}`,
          label: entry.label,
          text: valueText($t, entry.field, value),
          known: value !== null && value !== undefined && value !== '',
        },
      ];
    }),
  );

  const summary = $derived.by(() => {
    if (opensByDefault(status)) {
      const worst = checks.find((c) => (c.state?.status ?? 'pending') === status);
      const text = worst && (problemText(worst) ?? worst.state?.message);
      if (worst && text) return checks.length > 1 ? `${worst.name}: ${text}` : text;
      return cardSummary($t, checks);
    }
    const known = figures.filter((f) => f.known).slice(0, 3);
    if (known.length) return known.map((f) => `${f.label} ${f.text}`).join(' · ');
    return cardSummary($t, checks);
  });
</script>

<MonCard {title} {status} {summary} note={cardNote($t, checks)}>
  {#if figures.length > 0}
    <dl class="module-figures">
      {#each figures as figure (figure.key)}
        <div class="module-figure">
          <dt>{figure.label}</dt>
          <dd>{figure.text}</dd>
        </div>
      {/each}
    </dl>
  {/if}
  <div class="module-checks">
    {#each checks as check (check.id)}
      {@const text = problemText(check)}
      <MonCheckLine {check} dense showChart={false}>
        {#snippet label()}
          <span class="mon-line-name">{check.name}</span>
          {#if check.silent}
            <Badge>{$t('monitoring.card.silent')}</Badge>
          {/if}
        {/snippet}
        {#snippet value()}
          {#if text}
            <span class="module-status">{text}</span>
          {/if}
        {/snippet}
      </MonCheckLine>
    {/each}
  </div>
</MonCard>

<style>
  .module-figures {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
    gap: var(--space-3) var(--space-4);
    margin: 0;
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border-faint);
  }
  .module-figure {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .module-figure dt {
    color: var(--text-subtle);
    font-size: var(--text-xs);
  }
  .module-figure dd {
    overflow: hidden;
    margin: 0;
    color: var(--text-strong);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .module-checks {
    display: flex;
    flex-direction: column;
  }
  .module-status {
    overflow: hidden;
    max-width: 24rem;
    color: var(--text-muted);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
