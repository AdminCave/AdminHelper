<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorCheck, Server } from '$lib/api/types';
  import { groupChecksByServer } from '$lib/models/monitoring';

  /**
   * The checker's rating of the two points: `action` when it names a reboot or security
   * updates, `ok` when both are known and clean, `open` for anything else it reported (a
   * point not determined, or switched off with a bad value), `nodata` before a report.
   */
  export type UpdateState = 'action' | 'open' | 'nodata' | 'ok';

  export interface UpdateRow {
    key: string;
    serverKey: string;
    serverName: string;
    /** null: not determined. */
    reboot: boolean | null;
    securityUpdates: number | null;
    /** The checker's problems among reboot and security_updates, in its order. */
    problems: ('reboot' | 'security_updates')[];
    state: UpdateState;
    checkStatus: string;
  }

  const SEVERITY: Record<UpdateState, number> = { action: 0, open: 1, nodata: 2, ok: 3 };

  export function stateRank(state: UpdateState): number {
    return SEVERITY[state];
  }

  function isObject(v: unknown): v is Record<string, unknown> {
    return typeof v === 'object' && v !== null && !Array.isArray(v);
  }

  function updateRow(check: MonitorCheck): Omit<UpdateRow, 'serverKey' | 'serverName'> {
    const status = check.state?.status ?? 'unknown';
    const d: unknown = check.state?.details;
    // Read loosely like the server page's section: a check switched to this type keeps
    // the details of its old type until the next push.
    const details = isObject(d) ? d : null;
    const reboot =
      details && typeof details.reboot_required === 'boolean' ? details.reboot_required : null;
    const raw = details?.security_updates;
    const updates = typeof raw === 'number' && Number.isInteger(raw) ? raw : null;
    const named: unknown[] = Array.isArray(details?.problems) ? details.problems : [];
    const problems = (['reboot', 'security_updates'] as const).filter((p) => named.includes(p));
    let state: UpdateState;
    if (!details) state = 'nodata';
    else if (problems.length > 0) state = 'action';
    else if (reboot === false && updates === 0) state = 'ok';
    else state = 'open';
    return {
      key: check.id,
      reboot,
      securityUpdates: updates,
      problems,
      state,
      checkStatus: status,
    };
  }

  /** One row per enabled `system_state` check, i.e. per Linux server that reports it. */
  export function updateRows(checks: MonitorCheck[], servers: Server[]): UpdateRow[] {
    const rows: UpdateRow[] = [];
    for (const group of groupChecksByServer(checks, servers)) {
      const server = { serverKey: group.serverId ?? '__none', serverName: group.serverName };
      for (const check of group.checks) {
        if (check.checkType !== 'system_state' || check.enabled === false) continue;
        rows.push({ ...updateRow(check), ...server });
      }
    }
    return rows;
  }
</script>

<script lang="ts">
  import { t } from '$lib/i18n';
  import Pill from '../../ui/Pill.svelte';
  import CrossTable, { type CrossColumn } from './CrossTable.svelte';
  import ServerLink from './ServerLink.svelte';

  interface Props {
    checks: MonitorCheck[];
    servers: Server[];
    /** Opens the server page of a row's server. */
    onOpen: (serverKey: string) => void;
  }

  let { checks, servers, onOpen }: Props = $props();

  const rows = $derived(updateRows(checks, servers));

  // A problem takes the colour of the check's status, as on the server page: a first,
  // still damped one leaves the check ok, and then the pill stays grey.
  function tone(row: UpdateRow): 'ok' | 'warn' | 'crit' | 'muted' {
    if (row.state === 'ok') return 'ok';
    if (row.state !== 'action') return 'muted';
    if (row.checkStatus === 'critical') return 'crit';
    if (row.checkStatus === 'warning') return 'warn';
    return 'muted';
  }

  function stateText(row: UpdateRow): string {
    switch (row.state) {
      case 'action':
        return row.problems
          .map((p) =>
            p === 'reboot'
              ? $t('monitoring.system.problem.reboot')
              : $t('monitoring.system.problem.security_updates', { count: row.securityUpdates }),
          )
          .join(' · ');
      case 'ok':
        return $t('monitoring.updates.state.ok');
      case 'open':
        return $t('monitoring.system.notEvaluated');
      case 'nodata':
        return $t('monitoring.updates.state.noData');
    }
  }

  function rebootText(row: UpdateRow): string {
    if (row.reboot === null) return '—';
    return $t(row.reboot ? 'monitoring.system.yes' : 'monitoring.system.no');
  }

  const columns: CrossColumn<UpdateRow>[] = $derived([
    {
      key: 'server',
      label: $t('monitoring.cross.server'),
      text: (r) => r.serverName,
      cell: serverCell,
    },
    {
      key: 'reboot',
      label: $t('monitoring.system.point.reboot'),
      text: rebootText,
      // Needed first, then not needed, an unknown one last.
      sort: (r) => (r.reboot === null ? null : r.reboot ? 0 : 1),
    },
    {
      key: 'updates',
      label: $t('monitoring.system.point.security_updates'),
      text: (r) => (r.securityUpdates === null ? '—' : String(r.securityUpdates)),
      sort: (r) => r.securityUpdates,
      numeric: true,
    },
    {
      key: 'state',
      label: $t('monitoring.updates.col.state'),
      text: stateText,
      sort: (r) => stateRank(r.state),
      cell: stateCell,
    },
  ]);
</script>

{#snippet serverCell(row: UpdateRow)}
  <ServerLink name={row.serverName} serverKey={row.serverKey} {onOpen} />
{/snippet}

{#snippet stateCell(row: UpdateRow)}
  <span data-state={row.state}><Pill tone={tone(row)}>{stateText(row)}</Pill></span>
{/snippet}

<CrossTable
  {rows}
  {columns}
  rowKey={(r) => r.key}
  label={$t('monitoring.updates.label')}
  emptyText={$t('monitoring.updates.empty')}
  sortKey="state"
/>
