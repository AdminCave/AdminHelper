// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T4 (R-1225): the plain-text sentences of the monitoring cards.
// Pins the certificate thresholds of concept §5 at their boundaries (90 days: 22.5/9 d,
// 6 days: 36/14.4 h, a short-lived certificate: never under 12 h), the expiry sentences,
// the UTC reading of zone-less timestamps, units by field name, the finding detail and a
// card's closed line and muted note. T8: a finding's name and the lines of what adopting
// left out, shared by the server page and the findings of all servers.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/utils/timeAgo', () => ({ timeAgo: vi.fn(() => 'AGO') }));

import { get } from 'svelte/store';
import { setLanguage, t } from '$lib/i18n';
import { timeAgo } from '$lib/utils/timeAgo';
import type {
  MonitorCatalog,
  MonitorCheck,
  MonitorFinding,
  MonitorMutedReason,
  MonStatus,
} from '$lib/api/types';
import {
  adoptNoteLines,
  ageText,
  bytesText,
  cardNote,
  cardSummary,
  expiryLevel,
  expiryText,
  findingDetail,
  findingLabel,
  mutedReasonText,
  probeStatusText,
  spanText,
  valueText,
} from './monitoringText';

const H = 3600;
const D = 24 * H;
const NOW = 1_800_000_000;

beforeEach(() => setLanguage('de'));
afterEach(() => setLanguage('de'));

describe('probeStatusText', () => {
  it('names every known sensor status in words', () => {
    const tr = get(t);
    expect(probeStatusText(tr, 'no_credential')).toBe('Zugangsdaten fehlen');
    for (const code of [
      'ok',
      'error',
      'denied',
      'no_credential',
      'not_allowed',
      'unsupported',
      'ambiguous_target',
      'invalid',
    ]) {
      const text = probeStatusText(tr, code);
      expect(text, code).toBeTruthy();
      expect(text, code).not.toMatch(/^monitoring\./);
    }
  });

  it('says the agent refused a target without claiming why', () => {
    // The agent refuses for several reasons (blocklist, forwarder, socket checks); its own
    // error names the one that applied, so the label must not assert a foreign address.
    expect(probeStatusText(get(t), 'not_allowed')).toBe('Der Agent hat das Ziel abgewiesen');
    setLanguage('en');
    expect(probeStatusText(get(t), 'not_allowed')).toBe('The agent refused the target');
  });

  it('quotes the code of a newer agent and is null before the first answer', () => {
    const tr = get(t);
    expect(probeStatusText(tr, 'rate_limited')).toBe('Fühler meldet „rate_limited“');
    expect(probeStatusText(tr, null)).toBeNull();
    expect(probeStatusText(tr, '')).toBeNull();
  });
});

describe('mutedReasonText', () => {
  it('says why notifications are held back, null when they are not', () => {
    const tr = get(t);
    expect(mutedReasonText(tr, 'host down')).toBe('Host down — Meldungen unterdrückt');
    expect(mutedReasonText(tr, 'maintenance window')).toBe(
      'Wartungsfenster — Meldungen unterdrückt',
    );
    expect(mutedReasonText(tr, 'silent check')).toBe(
      'Stiller Check — meldet erst nach dem Übernehmen',
    );
    expect(mutedReasonText(tr, null)).toBeNull();
    expect(mutedReasonText(tr, undefined)).toBeNull();
  });
});

function check(status: MonStatus, mutedReason: MonitorMutedReason | null = null): MonitorCheck {
  return {
    id: `${status}-${mutedReason}`,
    name: 'c',
    checkType: 'probe',
    interval: '5m',
    severity: 'warning',
    enabled: true,
    state: { status },
    mutedReason,
  };
}

describe('cardNote', () => {
  it('names host down before a maintenance window, as soon as one check has it', () => {
    const tr = get(t);
    expect(
      cardNote(tr, [check('ok', 'maintenance window'), check('ok', 'host down'), check('ok')]),
    ).toBe('Host down — Meldungen unterdrückt');
    expect(cardNote(tr, [check('ok'), check('ok', 'maintenance window')])).toBe(
      'Wartungsfenster — Meldungen unterdrückt',
    );
  });

  it('calls a card silent only when every check is silent', () => {
    const tr = get(t);
    expect(cardNote(tr, [check('ok', 'silent check'), check('pending', 'silent check')])).toBe(
      'Stiller Check — meldet erst nach dem Übernehmen',
    );
    expect(cardNote(tr, [check('ok', 'silent check'), check('ok')])).toBeNull();
    expect(cardNote(tr, [])).toBeNull();
  });
});

describe('cardSummary', () => {
  it('counts the problems by status, worst first', () => {
    const tr = get(t);
    expect(
      cardSummary(tr, [check('unknown'), check('warning'), check('critical'), check('warning')]),
    ).toBe('1 Kritisch · 2 Warnung · 1 Unknown');
  });

  it('counts the checks when nothing is wrong', () => {
    expect(cardSummary(get(t), [check('ok'), check('pending')])).toBe('2 Checks');
  });
});

describe('expiryLevel (concept §5)', () => {
  // A certificate issued at `notBefore`, `lifetime` long, seen with `left` to go.
  const level = (lifetime: number, left: number) =>
    expiryLevel(NOW + left, NOW + left - lifetime, NOW);

  it('90 days: warning under 22.5 days, critical under 9 days', () => {
    expect(level(90 * D, 22.5 * D)).toBe('ok');
    expect(level(90 * D, 22.5 * D - 1)).toBe('warning');
    expect(level(90 * D, 9 * D)).toBe('warning');
    expect(level(90 * D, 9 * D - 1)).toBe('critical');
  });

  it('6 days: warning under 36 hours, critical under 14.4 hours', () => {
    expect(level(6 * D, 36 * H)).toBe('ok');
    expect(level(6 * D, 36 * H - 1)).toBe('warning');
    expect(level(6 * D, 14.4 * H)).toBe('warning');
    expect(level(6 * D, 14.4 * H - 1)).toBe('critical');
  });

  it('a short lifetime is critical under 12 hours, however small 10 % is', () => {
    expect(level(2 * D, 13 * H)).toBe('ok');
    expect(level(2 * D, 12 * H)).toBe('ok');
    expect(level(2 * D, 11 * H)).toBe('critical');
  });

  it('is expired from the second it runs out, with or without notBefore', () => {
    expect(level(90 * D, 0)).toBe('expired');
    expect(expiryLevel(NOW - 10, null, NOW)).toBe('expired');
  });

  it('is null without a lifetime: the check status counts', () => {
    expect(expiryLevel(NOW + D, null, NOW)).toBeNull();
    expect(expiryLevel(NOW + D, undefined, NOW)).toBeNull();
    expect(expiryLevel(NOW + D, NOW + D, NOW)).toBeNull();
    expect(expiryLevel(NOW + D, NOW + 2 * D, NOW)).toBeNull();
  });
});

describe('expiryText', () => {
  const text = (left: number) => expiryText(get(t), NOW + left, NOW);

  it('counts whole days from two days on, else hours', () => {
    expect(text(9.9 * D)).toBe('Läuft in 9 Tagen ab');
    expect(text(2 * D)).toBe('Läuft in 2 Tagen ab');
    expect(text(2 * D - 1)).toBe('Läuft in 47 Stunden ab');
    expect(text(2 * H)).toBe('Läuft in 2 Stunden ab');
    expect(text(H + 30 * 60)).toBe('Läuft in einer Stunde ab');
    expect(text(59 * 60)).toBe('Läuft in weniger als einer Stunde ab');
  });

  it('says how long ago an expired certificate ran out', () => {
    expect(text(-3 * D - H)).toBe('Seit 3 Tagen abgelaufen');
    expect(text(-5 * H)).toBe('Seit 5 Stunden abgelaufen');
    expect(text(-H)).toBe('Gerade abgelaufen');
    expect(text(0)).toBe('Gerade abgelaufen');
  });

  it('speaks English after a language switch', () => {
    setLanguage('en');
    expect(text(9 * D)).toBe('Expires in 9 days');
    expect(text(-5 * H)).toBe('Expired 5 hours ago');
  });
});

describe('ageText', () => {
  it('reads a zone-less timestamp as UTC and leaves zoned ones alone', () => {
    const tr = get(t);
    const spy = vi.mocked(timeAgo);
    spy.mockClear();
    expect(ageText(tr, '2026-11-10T10:00:00')).toBe('AGO');
    expect(ageText(tr, '2026-11-10T10:00:00.123456')).toBe('AGO');
    ageText(tr, '2026-11-10T10:00:00Z');
    ageText(tr, '2026-11-10T10:00:00+02:00');
    ageText(tr, '2026-11-10T10:00:00-0130');
    ageText(tr, null);
    expect(spy.mock.calls.map((c) => c[0])).toEqual([
      '2026-11-10T10:00:00Z',
      '2026-11-10T10:00:00.123456Z',
      '2026-11-10T10:00:00Z',
      '2026-11-10T10:00:00+02:00',
      '2026-11-10T10:00:00-0130',
      null,
    ]);
  });
});

describe('spanText', () => {
  it('uses the largest whole unit', () => {
    const tr = get(t);
    expect(spanText(tr, 45)).toBe('45 s');
    expect(spanText(tr, 59.9)).toBe('59 s');
    expect(spanText(tr, 60)).toBe('1 min');
    expect(spanText(tr, H - 1)).toBe('59 min');
    expect(spanText(tr, H)).toBe('1 h');
    expect(spanText(tr, D - 1)).toBe('23 h');
    expect(spanText(tr, D)).toBe('1 Tag');
    expect(spanText(tr, 4 * D)).toBe('4 Tage');
    expect(spanText(tr, -5)).toBe('0 s');
  });
});

describe('bytesText', () => {
  it('steps by 1024 with one decimal in the language of the UI', () => {
    expect(bytesText(512)).toBe('512 B');
    expect(bytesText(1536)).toBe('1,5 KiB');
    expect(bytesText(2 * 1024 ** 3)).toBe('2 GiB');
    expect(bytesText(3 * 1024 ** 5)).toBe('3.072 TiB');
    setLanguage('en');
    expect(bytesText(1536)).toBe('1.5 KiB');
  });
});

describe('valueText', () => {
  it('shows a dash for no value and words for booleans', () => {
    const tr = get(t);
    expect(valueText(tr, 'x', null)).toBe('—');
    expect(valueText(tr, 'x', undefined)).toBe('—');
    expect(valueText(tr, 'x', '')).toBe('—');
    expect(valueText(tr, 'x', true)).toBe('ja');
    expect(valueText(tr, 'x', false)).toBe('nein');
    expect(valueText(tr, 'x', 'active')).toBe('active');
  });

  it('takes the unit from the last segment of the field name', () => {
    const tr = get(t);
    // Noon UTC: the same calendar day in every time zone the CI runs in.
    expect(valueText(tr, 'tls.not_after', Date.UTC(2026, 10, 10, 12) / 1000)).toBe('10.11.2026');
    expect(valueText(tr, 'tls.days_left', 1)).toBe('1 Tag');
    expect(valueText(tr, 'days_left', 9.7)).toBe('9 Tage');
    expect(valueText(tr, 'disk.free_bytes', 1536)).toBe('1,5 KiB');
    expect(valueText(tr, 'http.rtt_ms', 42)).toBe('42 ms');
    expect(valueText(tr, 'uptime_s', 2 * H)).toBe('2 h');
    expect(valueText(tr, 'load', 1.234)).toBe('1,23');
    expect(valueText(tr, 'connections', 3)).toBe('3');
  });
});

describe('findingDetail', () => {
  it('names the image, the compose services, the unit, the process or the match', () => {
    expect(findingDetail({ image: 'nginx:1.27', unit: 'nginx.service' })).toBe('nginx:1.27');
    expect(findingDetail({ services: { web: {}, db: {} } })).toBe('web, db');
    expect(findingDetail({ unit: 'nginx.service' })).toBe('nginx.service');
    expect(findingDetail({ process: 'mysqld' })).toBe('mysqld');
    expect(findingDetail({ matched_by: ['package', 'unit'] })).toBe('package, unit');
  });

  it('is null when nothing identifies the instance', () => {
    expect(findingDetail({})).toBeNull();
    expect(findingDetail({ image: '', services: {}, matched_by: [] })).toBeNull();
    expect(findingDetail({ services: ['web'] })).toBeNull();
    expect(findingDetail({ image: 42 })).toBeNull();
  });
});

function finding(id: string, over: Partial<MonitorFinding> = {}): MonitorFinding {
  return {
    id,
    serverId: 'srv-1',
    moduleId: 'nginx',
    moduleName: 'Nginx',
    instanceKey: `nginx@${id}`,
    kind: 'new',
    status: 'open',
    summary: {},
    catalogVersion: '1',
    firstSeen: null,
    lastSeen: null,
    decidedAt: null,
    silentChecks: [],
    droppedChecks: [],
    ...over,
  };
}

describe('findingLabel', () => {
  it('names the module and an instance that is not the module itself', () => {
    expect(findingLabel(finding('a'))).toBe('Nginx · nginx@a');
    expect(findingLabel(finding('a', { instanceKey: 'nginx' }))).toBe('Nginx');
    expect(findingLabel(finding('a', { moduleName: null }))).toBe('nginx · nginx@a');
  });
});

describe('adoptNoteLines', () => {
  const CATALOG: MonitorCatalog = {
    version: '1',
    modules: [
      {
        id: 'nginx',
        name: 'Nginx',
        version: 1,
        description: '',
        instance: 'config',
        checks: [
          {
            key: 'tls',
            name: 'Zertifikat',
            sensor: 'nginx',
            interval: 60,
            fields: [],
            testObject: false,
            credential: null,
          },
        ],
        card: [],
      },
    ],
  };
  const adopted = (f: MonitorFinding, keys: string[]) => ({
    finding: f,
    enabledChecks: [],
    disabledChecks: [],
    skippedChecks: keys.map((key) => ({ key, reason: `no ${key}` })),
  });

  it('names a skipped check from the catalog, else by its key', () => {
    const tr = get(t);
    const lines = adoptNoteLines(tr, [adopted(finding('a'), ['tls', 'gone'])], [], CATALOG);
    expect(lines).toEqual([
      'Nginx · nginx@a: Check „Zertifikat“ nicht angelegt — no tls',
      'Nginx · nginx@a: Check „gone“ nicht angelegt — no gone',
    ]);
    expect(adoptNoteLines(tr, [adopted(finding('a'), ['tls'])], [], null)).toEqual([
      'Nginx · nginx@a: Check „tls“ nicht angelegt — no tls',
    ]);
  });

  it('names a failed finding from the list before adopting, else by its id', () => {
    const tr = get(t);
    const failed = [
      { findingId: 'b', reason: 'instance is gone' },
      { findingId: 'x', reason: 'unknown' },
    ];
    expect(adoptNoteLines(tr, [], failed, CATALOG, [finding('b')])).toEqual([
      'Nginx · nginx@b: nicht übernommen — instance is gone',
      'x: nicht übernommen — unknown',
    ]);
  });

  it('names findings with the given label, skipped checks first', () => {
    const tr = get(t);
    const label = (f: MonitorFinding) => `srv · ${f.id}`;
    const lines = adoptNoteLines(
      tr,
      [adopted(finding('a'), ['tls'])],
      [{ findingId: 'b', reason: 'r' }],
      CATALOG,
      [finding('b')],
      label,
    );
    expect(lines).toEqual([
      'srv · a: Check „Zertifikat“ nicht angelegt — no tls',
      'srv · b: nicht übernommen — r',
    ]);
  });

  it('is empty when nothing was left out', () => {
    expect(adoptNoteLines(get(t), [adopted(finding('a'), [])], [], CATALOG)).toEqual([]);
  });
});
