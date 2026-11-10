// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T7 (R-1225, concept §5): the certificates of all servers in one
// table. Pins the rows (an HTTPS check's certificate, every probe check that reports
// not_after, a failing sensor kept, disabled checks and checks without a date left out),
// the rating relative to the lifetime for HTTP and by the check's status for a sensor,
// the issuer's CN from a distinguished name, the order by expiry with an unknown date
// last, the texts, the empty view and the click that opens a server page.

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import type { MonStatus, MonitorCheck, MonitorCheckConfig, Server } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import CertsView, { certRows, issuerName, levelRank } from './CertsView.svelte';

// Noon UTC, so the shown date is the same day in every time zone of the test host.
const NOW = Date.UTC(2027, 0, 15, 12) / 1000;
const DAY = 86400;

const SERVERS: Server[] = [
  { id: 'srv-web', name: 'web-1', hostname: 'web-1.example' },
  { id: 'srv-pve', name: 'pve-1', hostname: 'pve-1.example' },
];

function check(id: string, over: Partial<MonitorCheck>): MonitorCheck {
  return {
    id,
    name: id,
    serverId: 'srv-web',
    checkType: 'http',
    interval: '5m',
    severity: 'warning',
    enabled: true,
    ...over,
  };
}

// An HTTPS check whose certificate lives `life` days and ends `left` days from NOW.
function https(id: string, left: number, life = 90, over: Partial<MonitorCheck> = {}) {
  return check(id, {
    config: { url: `https://${id}.example/` },
    state: {
      status: 'ok',
      details: {
        cert: {
          not_before: NOW + (left - life) * DAY,
          not_after: NOW + left * DAY,
          issuer: 'R11',
          subject_cn: `${id}.example`,
        },
      },
    },
    ...over,
  });
}

function sensor(
  id: string,
  status: MonStatus,
  values: Record<string, unknown>,
  probeStatus: string | null = 'ok',
  config: Record<string, unknown> = {},
): MonitorCheck {
  // A probe's target is an object, the config type knows only the string of ping/tcp.
  const probeConfig: Record<string, unknown> = {
    sensor: 'tls',
    fields: ['not_after', 'days_left', 'issuer'],
    target: { kind: 'local', name: 'pve-1' },
    params: { server_name: `${id}.example` },
    ...config,
  };
  return check(id, {
    serverId: 'srv-pve',
    checkType: 'probe',
    config: probeConfig as MonitorCheckConfig,
    state: {
      status,
      details: { ts: NOW, status: probeStatus, error: null, measured_ts: NOW, values },
    },
  });
}

function rows(container: HTMLElement): string[][] {
  return [...container.querySelectorAll('tbody tr')].map((tr) =>
    [...tr.querySelectorAll('td')].map((td) => td.textContent?.replace(/\s+/g, ' ').trim() ?? ''),
  );
}

beforeAll(() => setLanguage('de'));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('certRows', () => {
  it('rates an HTTPS certificate relative to its lifetime', () => {
    const list = certRows(
      [
        https('ok', 30),
        https('warn', 20),
        https('crit', 8),
        https('gone', -1),
        // 6 days of life, 20 h left: under 25 % of L, not yet under 10 % (14.4 h).
        https('short', 20 / 24, 6),
        // Under 12 h is critical however long or short the lifetime.
        https('tiny', 11 / 24, 2),
      ],
      SERVERS,
      NOW,
    );
    expect(Object.fromEntries(list.map((r) => [r.key, r.level]))).toEqual({
      ok: 'ok',
      warn: 'warning',
      crit: 'critical',
      gone: 'expired',
      short: 'warning',
      tiny: 'critical',
    });
    expect(list.find((r) => r.key === 'ok')).toMatchObject({
      serverKey: 'srv-web',
      serverName: 'web-1',
      check: 'ok',
      target: 'https://ok.example/',
      issuer: 'R11',
      notAfter: NOW + 30 * DAY,
      probeStatus: null,
    });
  });

  it('leaves the rating open without a lifetime, whatever the HTTP status says', () => {
    const c = https('nolife', 30);
    c.state = { status: 'critical', details: { cert: { not_after: NOW + 30 * DAY } } };
    const [row] = certRows([c], SERVERS, NOW);
    expect(row.level).toBe('unknown');
    expect(row.checkStatus).toBe('critical');
    // An expired one is still certain.
    c.state = { status: 'ok', details: { cert: { not_after: NOW - DAY } } };
    expect(certRows([c], SERVERS, NOW)[0].level).toBe('expired');
  });

  it('rates a sensor by its check status and keeps a failing sensor', () => {
    const list = certRows(
      [
        sensor('tls-warn', 'warning', {
          not_after: NOW + 10 * DAY,
          issuer: "CN=R11,O=Let's Encrypt,C=US",
        }),
        sensor('tls-old', 'ok', { not_after: NOW - 2 * DAY }),
        sensor('denied', 'unknown', {}, 'denied', {
          sensor: 'certfile',
          fields: ['not_after'],
          params: { path: '/etc/ssl/certs/mail.pem' },
        }),
        sensor('noname', 'critical', { not_after: NOW + DAY }, 'ok', { params: {} }),
      ],
      SERVERS,
      NOW,
    );
    expect(
      list.map((r) => [r.key, r.level, r.target, r.issuer, r.notAfter, r.probeStatus]),
    ).toEqual([
      ['tls-warn', 'warning', 'tls-warn.example', 'R11', NOW + 10 * DAY, 'ok'],
      ['tls-old', 'expired', 'tls-old.example', null, NOW - 2 * DAY, 'ok'],
      ['denied', 'unknown', '/etc/ssl/certs/mail.pem', null, null, 'denied'],
      ['noname', 'critical', 'pve-1', null, NOW + DAY, 'ok'],
    ]);
  });

  it('leaves out disabled checks and checks without an expiry date', () => {
    const plain = check('plain', {
      config: { url: 'http://plain.example/' },
      state: { status: 'ok', details: { status_code: 200 } },
    });
    const load = sensor('load', 'ok', { load1: 0.2 }, 'ok', { sensor: 'load', fields: ['load1'] });
    const off = https('off', 30, 90, { enabled: false });
    const offSensor = { ...sensor('off-tls', 'ok', { not_after: NOW + DAY }), enabled: false };
    const ping = check('ping', { checkType: 'ping', config: { target: '192.0.2.1' } });
    expect(certRows([plain, load, off, offSensor, ping], SERVERS, NOW)).toEqual([]);
  });

  it('files a check without a server under its own key', () => {
    const [row] = certRows([https('lost', 30, 90, { serverId: null })], SERVERS, NOW);
    expect(row.serverKey).toBe('__none');
    expect(row.serverName).toBe('Ohne Server');
  });

  it('orders the levels from expired to ok', () => {
    const levels = ['ok', 'unknown', 'warning', 'expired', 'critical'] as const;
    expect([...levels].sort((a, b) => levelRank(a) - levelRank(b))).toEqual([
      'expired',
      'critical',
      'warning',
      'unknown',
      'ok',
    ]);
  });
});

describe('issuerName', () => {
  it('takes the CN, else the O of a distinguished name, else the text', () => {
    expect(issuerName("CN=R11,O=Let's Encrypt,C=US")).toBe('R11');
    expect(issuerName('OU=Unit,O=Acme\\, Inc.,C=DE')).toBe('Acme, Inc.');
    expect(issuerName('CN=,O=Fallback')).toBe('Fallback');
    expect(issuerName('C=US')).toBe('C=US');
    expect(issuerName('R11')).toBe('R11');
    expect(issuerName(null)).toBeNull();
  });
});

describe('CertsView', () => {
  it('says how to get rows while no check reports an expiry date', () => {
    const { container } = render(CertsView, { checks: [], servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('Kein Check meldet ein Ablaufdatum.');
  });

  it('lists the soonest expiry first, an unknown date last, with its rating', () => {
    vi.spyOn(Date, 'now').mockReturnValue(NOW * 1000);
    const checks = [
      https('later', 60),
      sensor('denied', 'unknown', {}, 'denied', {
        sensor: 'certfile',
        fields: ['not_after'],
        params: { path: '/etc/ssl/x.pem' },
      }),
      https('soon', 3),
      sensor('tls', 'ok', { not_after: NOW - 3 * DAY, issuer: 'CN=E5,O=Example CA' }),
    ];
    const { container } = render(CertsView, { checks, servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('table')?.getAttribute('aria-label')).toBe(
      'Zertifikate und Domains aller Server',
    );
    expect(rows(container)).toEqual([
      ['pve-1', 'tls tls.example', 'E5', '12.01.2027', 'Seit 3 Tagen abgelaufen'],
      ['web-1', 'soon https://soon.example/', 'R11', '18.01.2027', 'Läuft in 3 Tagen ab'],
      ['web-1', 'later https://later.example/', 'R11', '16.03.2027', 'Läuft in 60 Tagen ab'],
      [
        'pve-1',
        'denied /etc/ssl/x.pem',
        '—',
        '—',
        'Zugriff verweigert, der Agent wartet auf neue Zugangsdaten',
      ],
    ]);
    const levels = [...container.querySelectorAll('[data-level]')].map((el) => [
      el.getAttribute('data-level'),
      el.querySelector('.pill')?.className.match(/pill-(\w+)/)?.[1],
    ]);
    expect(levels).toEqual([
      ['expired', 'crit'],
      ['critical', 'crit'],
      ['ok', 'ok'],
      ['unknown', 'muted'],
    ]);
  });

  it('says the check status when a sensor sent neither a date nor an answer', () => {
    vi.spyOn(Date, 'now').mockReturnValue(NOW * 1000);
    const c = sensor('quiet', 'pending', {}, null);
    const { container } = render(CertsView, { checks: [c], servers: SERVERS, onOpen: () => {} });
    expect(rows(container)[0][4]).toBe('Pending');
  });

  it('opens the server page of a row', async () => {
    const onOpen = vi.fn();
    const { getByRole } = render(CertsView, {
      checks: [https('soon', 3)],
      servers: SERVERS,
      onOpen,
    });
    const link = getByRole('button', { name: 'web-1' });
    expect(link.getAttribute('title')).toBe('Server-Seite von web-1 öffnen');
    await fireEvent.click(link);
    expect(onOpen).toHaveBeenCalledWith('srv-web');
  });
});
