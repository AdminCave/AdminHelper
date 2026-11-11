<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorCheck, Server } from '$lib/api/types';
  import { groupChecksByServer } from '$lib/models/monitoring';

  /** ok/outdated/missing per VM; a check without VM rows says why in one row. */
  export type BackupState = 'ok' | 'outdated' | 'missing' | 'unavailable' | 'empty';

  export interface BackupRow {
    key: string;
    serverKey: string;
    serverName: string;
    vmid: number | null;
    /** "VM 101 (web)"; the check's name for a row of the whole check. */
    what: string;
    state: BackupState;
    /** Hours since the last backup, known only for an outdated one. */
    ageHours: number | null;
    maxAgeHours: number;
    /** Text key of the outage when the agent could not read Proxmox. */
    errorKey: string | null;
    checkStatus: string;
  }

  // The checker's default (checkers/plugins.py) when the check sets none.
  const DEFAULT_MAX_AGE_HOURS = 26;

  // Spelled out: the i18n "no unused keys" guard only sees quoted keys.
  const ERROR_KEY = new Map<string, string>([
    ['timeout', 'monitoring.proxmox.error.timeout'],
    ['cli_failed', 'monitoring.proxmox.error.cli_failed'],
    ['parse_failed', 'monitoring.proxmox.error.parse_failed'],
    ['backup_index_incomplete', 'monitoring.proxmox.error.backup_index_incomplete'],
  ]);

  const SEVERITY: Record<BackupState, number> = {
    missing: 0,
    outdated: 1,
    unavailable: 2,
    empty: 3,
    ok: 4,
  };

  export function stateRank(state: BackupState): number {
    return SEVERITY[state];
  }

  function isObject(v: unknown): v is Record<string, unknown> {
    return typeof v === 'object' && v !== null && !Array.isArray(v);
  }

  type VmRow = Pick<BackupRow, 'what' | 'state' | 'ageHours'> & { vmid: number };

  function vmRow(v: Record<string, unknown>): VmRow | null {
    const vmid = v.vmid;
    if (typeof vmid !== 'number') return null;
    const type = typeof v.type === 'string' && v.type ? v.type : 'vm';
    const name = typeof v.name === 'string' && v.name ? v.name : '?';
    const state =
      v.backupStatus === 'missing' || v.backupStatus === 'outdated' ? v.backupStatus : 'ok';
    const age = typeof v.ageHours === 'number' && Number.isFinite(v.ageHours) ? v.ageHours : null;
    return {
      vmid,
      what: `${type.toUpperCase()} ${vmid} (${name})`,
      state,
      ageHours: state === 'outdated' ? age : null,
    };
  }

  /**
   * One row per VM/CT of every enabled `proxmox_backup` check, read loosely like the
   * server page's section: a check switched to this type keeps its old details until the
   * next push. A check that names no VM (Proxmox not readable, no data yet, no VM) keeps
   * one row, so the server does not drop out of the view.
   */
  export function backupRows(checks: MonitorCheck[], servers: Server[]): BackupRow[] {
    const rows: BackupRow[] = [];
    for (const group of groupChecksByServer(checks, servers)) {
      const server = { serverKey: group.serverId ?? '__none', serverName: group.serverName };
      for (const check of group.checks) {
        if (check.checkType !== 'proxmox_backup' || check.enabled === false) continue;
        const status = check.state?.status ?? 'unknown';
        const maxAge = check.config?.max_backup_age_hours;
        const base = {
          ...server,
          maxAgeHours: typeof maxAge === 'number' ? maxAge : DEFAULT_MAX_AGE_HOURS,
          checkStatus: status,
        };
        const d: unknown = check.state?.details;
        const details = isObject(d) ? d : {};
        // Only a JSON false is an outage, as for the checker.
        if (details.available === false) {
          const code = typeof details.error === 'string' ? details.error : '';
          rows.push({
            ...base,
            key: check.id,
            vmid: null,
            what: check.name,
            state: 'unavailable',
            ageHours: null,
            errorKey: ERROR_KEY.get(code) ?? 'monitoring.proxmox.error.unknown',
          });
          continue;
        }
        const raw: unknown[] = Array.isArray(details.vms) ? details.vms : [];
        const vms = raw
          .map((v) => (isObject(v) ? vmRow(v) : null))
          .filter((v): v is VmRow => v !== null);
        // Each VM once, the first entry winning, as on the server page.
        const unique = vms.filter((v, n) => vms.findIndex((w) => w.vmid === v.vmid) === n);
        for (const vm of unique) {
          rows.push({ ...base, ...vm, key: `${check.id}:${vm.vmid}`, errorKey: null });
        }
        if (unique.length === 0) {
          rows.push({
            ...base,
            key: check.id,
            vmid: null,
            what: check.name,
            state: 'empty',
            ageHours: null,
            errorKey: null,
          });
        }
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

  const rows = $derived(backupRows(checks, servers));

  // The outage takes the colour of the check's status, as on the server page: a warning,
  // and with the outage alert off (unknown) grey.
  function tone(row: BackupRow): 'ok' | 'warn' | 'crit' | 'muted' {
    if (row.state === 'ok') return 'ok';
    if (row.state === 'missing') return 'crit';
    if (row.state === 'outdated') return 'warn';
    if (row.state === 'unavailable' && row.checkStatus === 'critical') return 'crit';
    if (row.state === 'unavailable' && row.checkStatus === 'warning') return 'warn';
    return 'muted';
  }

  function stateText(row: BackupRow): string {
    switch (row.state) {
      case 'ok':
        return $t('monitoring.backups.state.ok');
      case 'outdated':
        return $t('monitoring.backups.state.outdated');
      case 'missing':
        return $t('monitoring.proxmox.missing');
      case 'unavailable':
        return $t(row.errorKey ?? 'monitoring.proxmox.error.unknown');
      case 'empty':
        return row.checkStatus === 'ok'
          ? $t('monitoring.backups.state.noVms')
          : $t('monitoring.backups.state.noData');
    }
  }

  // The details carry no backup time: an ok backup is younger than the check's limit,
  // only an outdated one knows its age (whole hours, as of the check's last run).
  function lastText(row: BackupRow): string {
    if (row.state === 'ok') return $t('monitoring.backups.within', { hours: row.maxAgeHours });
    if (row.state === 'missing') return $t('monitoring.backups.never');
    if (row.state !== 'outdated' || row.ageHours === null) return '—';
    if (row.ageHours < 48) return $t('monitoring.backups.agoHours', { count: row.ageHours });
    return $t('monitoring.backups.agoDays', { count: Math.floor(row.ageHours / 24) });
  }

  function lastSort(row: BackupRow): number | null {
    if (row.state === 'ok') return 0;
    if (row.state === 'outdated') return row.ageHours ?? row.maxAgeHours;
    if (row.state === 'missing') return Number.MAX_SAFE_INTEGER;
    return null;
  }

  const columns: CrossColumn<BackupRow>[] = $derived([
    {
      key: 'server',
      label: $t('monitoring.cross.server'),
      text: (r) => r.serverName,
      cell: serverCell,
    },
    { key: 'what', label: $t('monitoring.backups.col.what'), text: (r) => r.what },
    {
      key: 'last',
      label: $t('monitoring.backups.col.last'),
      text: lastText,
      sort: lastSort,
    },
    {
      key: 'state',
      label: $t('monitoring.backups.col.state'),
      text: stateText,
      sort: (r) => stateRank(r.state),
      cell: stateCell,
    },
  ]);
</script>

{#snippet serverCell(row: BackupRow)}
  <ServerLink name={row.serverName} serverKey={row.serverKey} {onOpen} />
{/snippet}

{#snippet stateCell(row: BackupRow)}
  <span data-state={row.state}><Pill tone={tone(row)}>{stateText(row)}</Pill></span>
{/snippet}

<CrossTable
  {rows}
  {columns}
  rowKey={(r) => r.key}
  label={$t('monitoring.backups.label')}
  emptyText={$t('monitoring.backups.empty')}
  sortKey="state"
/>
