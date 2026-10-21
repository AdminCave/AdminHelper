<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { untrack } from 'svelte';
  import type { MonitorCheckConfig } from '$lib/api/types';
  import { t } from '$lib/i18n';

  // config.disk_overrides of an agent_resources check: per exact mount path its
  // own warn, crit and min_free_gb (app/check_configs.py _DiskOverride).
  interface Props {
    // The parent's reactive $state config; this field owns config.disk_overrides.
    config: MonitorCheckConfig;
  }
  let { config }: Props = $props();

  type Override = NonNullable<MonitorCheckConfig['disk_overrides']>[string];
  type NumKey = keyof Override;
  type Row = { id: number; mount: string } & Record<NumKey, string>;

  // min/max mirror _DiskOverride; the hard rejection lives server-side.
  const NUM_COLS: { key: NumKey; labelKey: string; max: number }[] = [
    { key: 'warn', labelKey: 'monitoring.checkCfg.diskOverridesWarn', max: 100 },
    { key: 'crit', labelKey: 'monitoring.checkCfg.diskOverridesCrit', max: 100 },
    { key: 'min_free_gb', labelKey: 'monitoring.checkCfg.diskOverridesMinFreeGb', max: 1e6 },
  ];

  let nextId = 0;
  function newRow(mount = '', o: Override = {}): Row {
    const num = (v: unknown): string => (typeof v === 'number' ? String(v) : '');
    return {
      id: nextId++,
      mount,
      warn: num(o.warn),
      crit: num(o.crit),
      min_free_gb: num(o.min_free_gb),
    };
  }

  // The rows live here, not in config: a row without a mount or with a repeated
  // mount stays on screen but is not stored.
  let rows = $state<Row[]>([]);
  // The template editor keys its check cards by index: removing a card hands
  // this field the next card's config, and the rows have to follow it.
  let seededFrom: MonitorCheckConfig | undefined;
  $effect.pre(() => {
    const c = config;
    if (c === seededFrom) return;
    seededFrom = c;
    rows = untrack(() => Object.entries(c.disk_overrides ?? {}).map(([m, o]) => newRow(m, o)));
  });

  let duplicates = $derived.by(() => {
    const mounts = rows.map((r) => r.mount.trim()).filter(Boolean);
    return [...new Set(mounts.filter((m, i) => mounts.indexOf(m) !== i))];
  });

  // Without an entry the key goes, as in setBoolDefault (CheckConfigFields): a
  // template's check whose config gained {} would count as changed by the user.
  function store(): void {
    const entries: [string, Override][] = [];
    for (const r of rows) {
      const mount = r.mount.trim();
      // A repeated mount: the first row counts, the hint names the others.
      if (mount === '' || entries.some(([m]) => m === mount)) continue;
      const o: Override = {};
      for (const { key } of NUM_COLS) if (r[key].trim() !== '') o[key] = Number(r[key]);
      entries.push([mount, o]);
    }
    if (entries.length === 0) delete config.disk_overrides;
    else config.disk_overrides = Object.fromEntries(entries);
  }

  function setCell(row: Row, key: 'mount' | NumKey, raw: string): void {
    row[key] = raw;
    store();
  }
  function addRow(): void {
    rows.push(newRow());
  }
  function removeRow(id: number): void {
    rows = rows.filter((r) => r.id !== id);
    store();
  }
</script>

<div class="overrides">
  <span class="ovr-label">{$t('monitoring.checkCfg.diskOverrides')}</span>
  {#if rows.length > 0}
    <table>
      <thead>
        <tr>
          <th scope="col" class="ovr-mount">{$t('monitoring.checkCfg.diskOverridesMount')}</th>
          {#each NUM_COLS as col (col.key)}
            <th scope="col">{$t(col.labelKey)}</th>
          {/each}
          <td></td>
        </tr>
      </thead>
      <tbody>
        {#each rows as row (row.id)}
          <tr>
            <td>
              <input
                type="text"
                placeholder="/data"
                aria-label={$t('monitoring.checkCfg.diskOverridesMount')}
                value={row.mount}
                oninput={(e) => setCell(row, 'mount', e.currentTarget.value)}
              />
            </td>
            {#each NUM_COLS as col (col.key)}
              <td>
                <input
                  type="number"
                  min="0"
                  max={col.max}
                  aria-label={$t(col.labelKey)}
                  value={row[col.key]}
                  oninput={(e) => setCell(row, col.key, e.currentTarget.value)}
                />
              </td>
            {/each}
            <td>
              <button
                type="button"
                class="btn ghost small"
                title={$t('monitoring.checkCfg.diskOverridesRemove')}
                aria-label={$t('monitoring.checkCfg.diskOverridesRemove')}
                onclick={() => removeRow(row.id)}>×</button
              >
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {#if duplicates.length > 0}
    <div class="ovr-warn" role="note">
      {$t('monitoring.checkCfg.diskOverridesDuplicate', { mounts: duplicates.join(', ') })}
    </div>
  {/if}
  <span class="ovr-hint">{$t('monitoring.checkCfg.diskOverridesHint')}</span>
  <div>
    <button type="button" class="btn small" onclick={addRow}
      >{$t('monitoring.checkCfg.diskOverridesAdd')}</button
    >
  </div>
</div>

<style>
  .overrides {
    grid-column: span 2;
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .ovr-label,
  th {
    font-size: 12px;
    color: var(--text-muted);
  }
  .ovr-hint {
    font-size: 11px;
    color: var(--text-muted);
  }
  .ovr-warn {
    font-size: 12px;
    color: var(--warning, #ffc859);
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th {
    text-align: left;
    font-weight: 400;
    padding: 0 var(--sp-2) var(--sp-1) 0;
  }
  th.ovr-mount {
    width: 34%;
  }
  td {
    padding: 0 var(--sp-2) var(--sp-2) 0;
  }
  input {
    width: 100%;
    box-sizing: border-box;
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  input:focus {
    outline: 1px solid var(--accent);
  }
</style>
