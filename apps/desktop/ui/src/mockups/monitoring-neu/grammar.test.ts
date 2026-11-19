// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, expect, it } from 'vitest';
import type { Metric, MonObject } from './model';
import {
  badSinceText,
  duplicateKeys,
  exceptionText,
  grammarViolations,
  meterOf,
  metricText,
  objectLabel,
  sinceText,
  sortObjects,
  thresholdText,
} from './grammar';

const NOW = new Date('2026-11-18T09:00:00Z');

function obj(over: Partial<MonObject>): MonObject {
  return {
    key: 'web-01/service/nginx',
    kind: 'service',
    name: 'nginx',
    server: 'web-01',
    identity: ['web-01', 'nginx.service'],
    status: 'ok',
    reason: 'Läuft.',
    since: '2026-11-18T08:00:00Z',
    metrics: [],
    ...over,
  };
}

describe('sortObjects', () => {
  it('puts the worst status first and hidden objects at the end', () => {
    const list = [
      obj({ key: 'a', name: 'a', status: 'ok' }),
      obj({
        key: 'b',
        name: 'b',
        status: 'critical',
        exception: {
          effect: 'no-rating',
          scope: 'dieses Objekt',
          by: 'kevin',
          at: NOW.toISOString(),
        },
      }),
      obj({ key: 'c', name: 'c', status: 'warning' }),
      obj({ key: 'd', name: 'd', status: 'critical' }),
      obj({ key: 'e', name: 'e', status: 'stale' }),
      obj({ key: 'f', name: 'f', status: 'unknown' }),
      obj({ key: 'g', name: 'g', status: 'not-collected' }),
    ];
    expect(sortObjects(list).map((o) => o.key)).toEqual(['d', 'c', 'f', 'e', 'g', 'a', 'b']);
  });

  it('keeps an object that is only muted for notifications in its status place', () => {
    const muted = obj({
      key: 'm',
      status: 'critical',
      exception: {
        effect: 'no-notify',
        scope: 'dieses Objekt',
        by: 'kevin',
        at: NOW.toISOString(),
      },
    });
    expect(sortObjects([obj({ key: 'o' }), muted])[0].key).toBe('m');
  });

  it('orders equal status by server, then name, and does not mutate its input', () => {
    const list = [
      obj({ key: '2', server: 'web-01', name: 'b' }),
      obj({ key: '1', server: 'nas-01', name: 'z' }),
      obj({ key: '3', server: 'web-01', name: 'a' }),
    ];
    expect(sortObjects(list).map((o) => o.key)).toEqual(['1', '3', '2']);
    expect(list.map((o) => o.key)).toEqual(['2', '1', '3']);
  });
});

describe('threshold and metric text', () => {
  it('names warning and critical limits in plain words', () => {
    expect(thresholdText({ warn: 55, crit: 60 })).toBe('Warnung ab 55, kritisch ab 60');
    expect(thresholdText({ warn: 20, crit: 10, below: true })).toBe(
      'Warnung unter 20, kritisch unter 10',
    );
    expect(thresholdText({ crit: 1 })).toBe('Kritisch ab 1');
    expect(thresholdText(null)).toBe('');
  });

  it('formats value, unit and threshold as one text', () => {
    expect(
      metricText({ key: 't', label: 'Temperatur', value: 41, unit: '°C', threshold: { warn: 55 } }),
    ).toBe('41 °C (Warnung ab 55)');
    expect(
      metricText({ key: 'h', label: 'Laufzeit', value: 12345.67, unit: 'h', threshold: null }),
    ).toBe('12.345,7 h');
  });
});

describe('sinceText', () => {
  it.each([
    ['2026-11-18T08:59:30Z', 'seit gerade eben'],
    ['2026-11-18T08:13:00Z', 'seit 47 min'],
    ['2026-11-18T04:00:00Z', 'seit 5 h'],
    ['2026-11-17T08:00:00Z', 'seit 1 Tag'],
    ['2026-11-15T09:00:00Z', 'seit 3 Tagen'],
    ['2026-10-12T09:00:00Z', 'seit 12.10.2026'],
  ])('%s -> %s', (iso, text) => {
    expect(sinceText(iso, NOW)).toBe(text);
  });
});

describe('badSinceText', () => {
  it('names when the object turned bad if that was before its last status change', () => {
    const base = { status: 'critical' as const, since: '2026-11-18T07:00:00Z' };
    expect(badSinceText(obj({ ...base, badSince: '2026-11-15T09:00:00Z' }), NOW)).toBe(
      'nicht ok seit 3 Tagen',
    );
    expect(badSinceText(obj({ ...base, badSince: base.since }), NOW)).toBeNull();
    expect(badSinceText(obj(base), NOW)).toBeNull();
  });
});

describe('grammarViolations', () => {
  it('accepts an object that follows the grammar', () => {
    expect(grammarViolations(obj({}))).toEqual([]);
  });

  it('flags more than four metrics, a second sentence and the old rule format', () => {
    const m = (key: string) => ({ key, label: key, value: 1, threshold: null });
    const v = grammarViolations(
      obj({
        reason: 'reallocated = 8 (gt 0). Prüfen.',
        metrics: [m('a'), m('b'), m('c'), m('d'), m('e')],
      }),
    );
    expect(v).toContain('mehr als 4 Kennzahlen');
    expect(v).toContain('Grund hat mehr als einen Satz');
    expect(v).toContain('Grund im alten Regelformat');
  });

  it('flags a missing key, identity, reason or since and an empty threshold', () => {
    const v = grammarViolations(
      obj({
        key: '',
        identity: [],
        reason: ' ',
        since: 'gestern',
        metrics: [{ key: 'x', label: 'x', value: 1, threshold: {} }],
      }),
    );
    expect(v).toEqual([
      'kein Schlüssel',
      'keine Identitätszeile',
      'kein Grund',
      'seit fehlt',
      'Kennzahl x: Schwelle ohne Wert',
    ]);
  });

  it('accepts decimal numbers and abbreviations inside one sentence', () => {
    expect(grammarViolations(obj({ reason: 'Firmware 2.1 meldet ca. 3 % Verschleiß.' }))).toEqual(
      [],
    );
    expect(grammarViolations(obj({ reason: 'Lüfter z. B. Gehäuse ca. Mitte zu warm' }))).toEqual(
      [],
    );
  });

  it('flags a hidden object whose exception names nobody', () => {
    const exception = {
      effect: 'skip' as const,
      scope: 'dieses Objekt',
      by: '',
      at: '2026-11-01T09:00:00Z',
    };
    expect(grammarViolations(obj({ status: 'not-collected', exception }))).toEqual([
      'Ausnahme ohne wer',
    ]);
    expect(grammarViolations(obj({ exception: { ...exception, by: 'kevin' } }))).toEqual([]);
  });

  it('flags a bad-since after since and a bad-since on an ok object', () => {
    expect(
      grammarViolations(
        obj({
          status: 'critical',
          since: '2026-11-18T08:00:00Z',
          badSince: '2026-11-15T09:00:00Z',
        }),
      ),
    ).toEqual([]);
    expect(
      grammarViolations(
        obj({
          status: 'critical',
          since: '2026-11-15T09:00:00Z',
          badSince: '2026-11-18T08:00:00Z',
        }),
      ),
    ).toEqual(['schlecht seit nach seit']);
    expect(grammarViolations(obj({ badSince: '2026-11-15T09:00:00Z' }))).toEqual([
      'schlecht seit bei Status ok',
    ]);
  });
});

describe('duplicateKeys and exceptionText', () => {
  it('finds keys used twice', () => {
    expect(duplicateKeys([obj({ key: 'a' }), obj({ key: 'b' }), obj({ key: 'a' })])).toEqual(['a']);
  });

  it('describes an exception with effect, scope, reason, who, duration and bound value', () => {
    expect(
      exceptionText({
        effect: 'no-rating',
        scope: 'dieses Objekt',
        reason: 'alte Platte, beobachtet',
        by: 'kevin',
        at: '2026-11-01T10:00:00Z',
        boundValue: '8 umgelagerte Sektoren',
      }),
    ).toBe(
      'prüfen, nicht bewerten · dieses Objekt · Grund: alte Platte, beobachtet · von kevin · dauerhaft · gilt nur bei 8 umgelagerte Sektoren',
    );
  });
});

// arch-monitoring-neu-p0-abnahme T1 (R-1558): the label of an object does not repeat its kind, and
// the bar of a metric places value and limits on one scale.
describe('objectLabel', () => {
  it('names kind and name, but the kind only once when the name is the kind', () => {
    expect(objectLabel({ kind: 'disk', name: 'sda' })).toBe('Platte sda');
    expect(objectLabel({ kind: 'cpu', name: 'CPU' })).toBe('CPU');
    expect(objectLabel({ kind: 'memory', name: 'arbeitsspeicher' })).toBe('Arbeitsspeicher');
    expect(objectLabel({ kind: 'service', name: 'Dienst-Monitor' })).toBe('Dienst Dienst-Monitor');
  });
});

describe('meterOf', () => {
  const m = (value: Metric['value'], threshold: Metric['threshold'], unit?: string): Metric => ({
    key: 'k',
    label: 'k',
    value,
    unit,
    threshold,
  });

  it('runs a percentage to 100', () => {
    expect(meterOf(m(45, { warn: 90, crit: 95 }, '%'))).toEqual({ fill: 45, warn: 90, crit: 95 });
  });

  it('runs anything else a quarter past the largest of value and limits', () => {
    // max = 10 × 1.25 = 12.5
    expect(meterOf(m(8, { warn: 1, crit: 10 }))).toEqual({ fill: 64, warn: 8, crit: 80 });
    // The value beyond both limits sets the scale: max = 40 × 1.25 = 50.
    expect(meterOf(m(40, { warn: 20 }, 'GB'))).toEqual({ fill: 80, warn: 40, crit: undefined });
  });

  it('places limits that count downwards on the same scale', () => {
    // Free space: warning below 20, critical below 10; max = 20 × 1.25 = 25.
    expect(meterOf(m(15, { warn: 20, crit: 10, below: true }, 'GB'))).toEqual({
      fill: 60,
      warn: 80,
      crit: 40,
    });
  });

  it('keeps value and limits inside the bar', () => {
    expect(meterOf(m(130, { warn: 90, crit: 95 }, '%'))?.fill).toBe(100);
    expect(meterOf(m(-5, { warn: 90 }, '%'))?.fill).toBe(0);
    expect(meterOf(m(0, { warn: 0, crit: 0 }, '%'))).toEqual({ fill: 0, warn: 0, crit: 0 });
  });

  it('has no bar without a number, without a limit or with an empty scale', () => {
    expect(meterOf(m('aktiv', { warn: 1 }))).toBeNull();
    expect(meterOf(m(5, null))).toBeNull();
    expect(meterOf(m(5, { below: true }))).toBeNull();
    expect(meterOf(m(0, { warn: 0 }))).toBeNull();
  });
});
