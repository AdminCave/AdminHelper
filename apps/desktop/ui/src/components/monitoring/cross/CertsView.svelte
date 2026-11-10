<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorCheck, Server } from '$lib/api/types';
  import { probeDetails } from '$lib/models/checkDetails';
  import { groupChecksByServer } from '$lib/models/monitoring';
  import { expiryLevel, type ExpiryLevel } from '$lib/models/monitoringText';

  /** Display only (concept §5): relative to the lifetime when known, else the check's status. */
  export type CertLevel = ExpiryLevel | 'unknown';

  export interface CertRow {
    key: string;
    serverKey: string;
    serverName: string;
    check: string;
    /** URL, file or server name the date belongs to; null when the check names none. */
    target: string | null;
    issuer: string | null;
    /** Unix seconds; null while a sensor delivered no date. */
    notAfter: number | null;
    level: CertLevel;
    /** The sensor's answer, said when the row has no date. */
    probeStatus: string | null;
    checkStatus: string;
  }

  const LEVEL_OF_STATUS = new Map<string, CertLevel>([
    ['ok', 'ok'],
    ['warning', 'warning'],
    ['critical', 'critical'],
  ]);

  const SEVERITY: Record<CertLevel, number> = {
    expired: 0,
    critical: 1,
    warning: 2,
    unknown: 3,
    ok: 4,
  };

  export function levelRank(level: CertLevel): number {
    return SEVERITY[level];
  }

  function isObject(v: unknown): v is Record<string, unknown> {
    return typeof v === 'object' && v !== null && !Array.isArray(v);
  }

  function seconds(v: unknown): number | null {
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  }

  function text(v: unknown): string | null {
    return typeof v === 'string' && v.trim() ? v.trim() : null;
  }

  /**
   * The CN of a distinguished name as the agent sends it (Go `pkix.Name.String()`,
   * "CN=R11,O=Let's Encrypt,C=US"), else its O, else the text as it came. The HTTP
   * check already sends CN or O alone.
   */
  export function issuerName(issuer: string | null): string | null {
    if (!issuer) return null;
    for (const attr of ['CN', 'O']) {
      const m = new RegExp(`(?:^|,)${attr}=((?:[^,\\\\]|\\\\.)*)`).exec(issuer);
      if (m && m[1]) return m[1].replace(/\\(.)/g, '$1');
    }
    return issuer;
  }

  function statusLevel(status: string): CertLevel {
    return LEVEL_OF_STATUS.get(status) ?? 'unknown';
  }

  function httpRow(
    check: MonitorCheck,
    now: number,
  ): Omit<CertRow, 'serverKey' | 'serverName'> | null {
    const details = check.state?.details;
    const cert = isObject(details) && isObject(details.cert) ? details.cert : null;
    const notAfter = cert ? seconds(cert.not_after) : null;
    if (!cert || notAfter === null) return null;
    const status = check.state?.status ?? 'unknown';
    return {
      key: check.id,
      check: check.name,
      target: text(check.config?.url),
      issuer: issuerName(text(cert.issuer)),
      notAfter,
      // The HTTP check's status says nothing about its certificate: without a lifetime
      // that makes sense the rating stays open.
      level: expiryLevel(notAfter, seconds(cert.not_before), now) ?? 'unknown',
      probeStatus: null,
      checkStatus: status,
    };
  }

  function probeTarget(config: MonitorCheck['config']): string | null {
    // A probe's target is an object ({kind, name, …}), unlike the string of ping/tcp.
    const rawParams: unknown = config?.params;
    const rawTarget: unknown = config?.target;
    const params = isObject(rawParams) ? rawParams : {};
    const target = isObject(rawTarget) ? rawTarget : {};
    return text(params.path) ?? text(params.server_name) ?? text(target.name);
  }

  function probeRow(
    check: MonitorCheck,
    now: number,
  ): Omit<CertRow, 'serverKey' | 'serverName'> | null {
    const fields = check.config?.fields;
    if (!Array.isArray(fields) || !fields.includes('not_after')) return null;
    const details = probeDetails(check.state?.details);
    const values = details?.values ?? {};
    const notAfter = seconds(values.not_after);
    const status = check.state?.status ?? 'unknown';
    // A sensor sends no not_before: only "expired" is certain, else its check's thresholds
    // (days_left) have rated it already.
    const expired = notAfter !== null && expiryLevel(notAfter, null, now) === 'expired';
    return {
      key: check.id,
      check: check.name,
      target: probeTarget(check.config),
      issuer: issuerName(text(values.issuer)),
      notAfter,
      level: expired ? 'expired' : statusLevel(status),
      probeStatus: details?.status ?? null,
      checkStatus: status,
    };
  }

  /**
   * One row per enabled check with an expiry date: the certificate of an HTTPS check
   * (`details.cert`) and every probe check whose fields carry `not_after` (sensors `tls`,
   * `certfile`). A sensor row stays while its sensor fails, so a broken check is seen.
   * `now` in Unix seconds.
   */
  export function certRows(checks: MonitorCheck[], servers: Server[], now: number): CertRow[] {
    const rows: CertRow[] = [];
    for (const group of groupChecksByServer(checks, servers)) {
      const server = { serverKey: group.serverId ?? '__none', serverName: group.serverName };
      for (const check of group.checks) {
        if (check.enabled === false) continue;
        const row =
          check.checkType === 'http'
            ? httpRow(check, now)
            : check.checkType === 'probe'
              ? probeRow(check, now)
              : null;
        if (row) rows.push({ ...row, ...server });
      }
    }
    return rows;
  }
</script>

<script lang="ts">
  import { t } from '$lib/i18n';
  import { expiryText, probeStatusText, valueText } from '$lib/models/monitoringText';
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

  // Recomputed with every refresh of the checks; the rating moves with the clock.
  const rows = $derived(certRows(checks, servers, Date.now() / 1000));

  const TONE: Record<CertLevel, 'ok' | 'warn' | 'crit' | 'muted'> = {
    expired: 'crit',
    critical: 'crit',
    warning: 'warn',
    unknown: 'muted',
    ok: 'ok',
  };

  function statusText(status: string): string {
    const map: Record<string, string> = {
      ok: $t('monitoring.status.ok'),
      warning: $t('monitoring.status.warning'),
      critical: $t('monitoring.status.critical'),
      pending: $t('monitoring.status.pending'),
    };
    return map[status] ?? $t('monitoring.status.unknown');
  }

  function levelText(row: CertRow): string {
    if (row.notAfter !== null) return expiryText($t, row.notAfter, Date.now() / 1000);
    return probeStatusText($t, row.probeStatus) ?? statusText(row.checkStatus);
  }

  function targetText(row: CertRow): string {
    return row.target ? `${row.check} · ${row.target}` : row.check;
  }

  const columns: CrossColumn<CertRow>[] = $derived([
    {
      key: 'server',
      label: $t('monitoring.cross.server'),
      text: (r) => r.serverName,
      cell: serverCell,
    },
    { key: 'target', label: $t('monitoring.certs.col.target'), text: targetText, cell: targetCell },
    { key: 'issuer', label: $t('monitoring.certs.col.issuer'), text: (r) => r.issuer ?? '—' },
    {
      key: 'expires',
      label: $t('monitoring.certs.col.expires'),
      text: (r) => (r.notAfter === null ? '—' : valueText($t, 'not_after', r.notAfter)),
      sort: (r) => r.notAfter,
      numeric: true,
    },
    {
      key: 'level',
      label: $t('monitoring.certs.col.level'),
      text: levelText,
      sort: (r) => levelRank(r.level),
      cell: levelCell,
    },
  ]);
</script>

{#snippet serverCell(row: CertRow)}
  <ServerLink name={row.serverName} serverKey={row.serverKey} {onOpen} />
{/snippet}

{#snippet targetCell(row: CertRow)}
  <span class="cert-check">{row.check}</span>
  {#if row.target}<span class="cert-target">{row.target}</span>{/if}
{/snippet}

{#snippet levelCell(row: CertRow)}
  <span data-level={row.level}><Pill tone={TONE[row.level]}>{levelText(row)}</Pill></span>
{/snippet}

<CrossTable
  {rows}
  {columns}
  rowKey={(r) => r.key}
  label={$t('monitoring.certs.label')}
  emptyText={$t('monitoring.certs.empty')}
  sortKey="expires"
/>

<style>
  .cert-check {
    display: block;
  }
  .cert-target {
    display: block;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }
</style>
