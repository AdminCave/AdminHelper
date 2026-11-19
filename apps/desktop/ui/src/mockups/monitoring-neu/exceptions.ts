// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Exceptions as the server of the target model keeps them (Konzept §2, §8.1): a scope, an effect
// and a duration, optionally bound to the current value or to a condition over another check of
// the same instance (R-1515). applyExceptions() stands in for the server: it attaches to every
// object the exception that applies now, and the views read only its result.

import type { Effect, ExceptionInfo, Kind, MonObject } from './model';
import { STATUS_LABEL, dateText, formatValue, isHidden, objectLabel } from './grammar';

export type ScopeKind = 'object' | 'rule' | 'check' | 'check-type' | 'server' | 'tag' | 'cluster';

export const SCOPE_LABEL: Record<ScopeKind, string> = {
  object: 'Objekt',
  rule: 'Regel',
  check: 'Check',
  'check-type': 'Check-Typ',
  server: 'Server',
  tag: 'Tag',
  cluster: 'Cluster',
};

// Most specific first: of two exceptions in force on one object, the narrower one applies. What
// the object is (object, rule, check, check type) ranks before where it runs (server, tag,
// cluster): a check-type exception says something lasting about one kind of object ("SMART means
// nothing in a VM"), a server-wide one is a blanket like a maintenance window.
export const SPECIFICITY: readonly ScopeKind[] = [
  'object',
  'rule',
  'check',
  'check-type',
  'server',
  'tag',
  'cluster',
];

export interface Scope {
  kind: ScopeKind;
  /** Object key (object, rule), check id, check type, server, tag or cluster name. */
  value: string;
  /** Scope rule: the key of the rule on that object. */
  rule?: string;
  /** Scope check type: only on servers with this tag. */
  tag?: string;
}

export type Duration =
  | { kind: 'permanent' }
  | { kind: 'until'; until: string }
  /** Days 1 = Monday … 7 = Sunday; a window with to <= from ends the next morning. */
  | { kind: 'window'; days: number[]; from: string; to: string; tz: string };

/** R-1515: the exception holds only while this field of another object reports this value. */
export interface Condition {
  object: string;
  /** 'status' or a metric key. */
  field: string;
  equals: string;
}

export interface Exception {
  id: string;
  scope: Scope;
  effect: Effect;
  duration: Duration;
  /** Bound to the value at creation: ends once the metric reports anything else. */
  bound?: { metric: string; value: number | string; text: string };
  condition?: Condition;
  reason?: string;
  by?: string;
  at?: string;
  /** The setting it was migrated from (Konzept §8.1); wer and wann are unknown then. */
  migrated?: string;
  /** Confirmed in the review of old exceptions. */
  reviewed?: boolean;
}

/** What the server knows about the servers beside the objects: tags and cluster membership. */
export interface Topology {
  tags: Record<string, string[]>;
  clusters: Record<string, string[]>;
}

export type ExceptionState =
  { state: 'active' } | { state: 'resting'; text: string } | { state: 'ended'; text: string };

export const MIGRATED_BY = 'unbekannt (migriert)';

const CHECK_TYPE: Record<Kind, string> = {
  disk: 'smart_health',
  pool: 'zfs_health',
  'guest-backup': 'proxmox_backup',
  'backup-job': 'proxmox_backup',
  host: 'agent_ping',
  cpu: 'agent_resources',
  memory: 'agent_resources',
  mount: 'agent_resources',
  sensor: 'agent_resources',
  reboot: 'system_state',
  updates: 'system_state',
  clock: 'system_state',
  service: 'service_process',
  container: 'docker_health',
  'compose-project': 'docker_health',
  module: 'probe',
  certificate: 'central',
  domain: 'central',
  endpoint: 'http',
};

/** The check type of app/check_types.py that produces the object. */
export function checkTypeOf(o: MonObject): string {
  if (o.kind === 'endpoint' && ['ping', 'tcp', 'http'].includes(o.identity[0]))
    return o.identity[0];
  return CHECK_TYPE[o.kind];
}

const CENTRAL: Kind[] = ['certificate', 'domain', 'endpoint'];

/** The configured check behind the object: one per server and type, one per module instance,
 * one per central target. */
export function checkOf(o: MonObject): string {
  if (o.kind === 'module') return o.parent ?? o.key;
  if (CENTRAL.includes(o.kind)) return o.key;
  return `${o.server}/${checkTypeOf(o)}`;
}

export function covers(s: Scope, o: MonObject, topo: Topology): boolean {
  switch (s.kind) {
    case 'object':
    case 'rule':
      return o.key === s.value;
    case 'check':
      return checkOf(o) === s.value;
    case 'check-type':
      return checkTypeOf(o) === s.value && (!s.tag || tagsOf(o.server, topo).includes(s.tag));
    case 'server':
      return o.server === s.value;
    case 'tag':
      return tagsOf(o.server, topo).includes(s.value);
    case 'cluster':
      return (topo.clusters[s.value] ?? []).includes(o.server);
  }
}

function tagsOf(server: string, topo: Topology): string[] {
  return topo.tags[server] ?? [];
}

export function affected(e: Exception, objects: readonly MonObject[], topo: Topology): MonObject[] {
  return objects.filter((o) => covers(e.scope, o, topo));
}

// ---------------------------------------------------------------------------------------------
// state

const WEEKDAY: Record<string, number> = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };

function localTime(now: Date, tz: string): { day: number; minutes: number } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now);
  const get = (t: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === t)?.value ?? '';
  return {
    day: WEEKDAY[get('weekday')],
    minutes: Number(get('hour')) * 60 + Number(get('minute')),
  };
}

function minutesOf(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

/** Whether now lies in the window, in the window's own time zone. */
export function inWindow(d: Extract<Duration, { kind: 'window' }>, now: Date): boolean {
  const { day, minutes } = localTime(now, d.tz);
  const from = minutesOf(d.from);
  const to = minutesOf(d.to);
  if (from < to) return d.days.includes(day) && minutes >= from && minutes < to;
  const before = day === 1 ? 7 : day - 1;
  return (d.days.includes(day) && minutes >= from) || (d.days.includes(before) && minutes < to);
}

function fieldOf(o: MonObject, field: string): { label: string; value: string } {
  if (field === 'status') return { label: 'Zustand', value: o.status };
  const m = o.metrics.find((x) => x.key === field);
  return { label: m?.label ?? field, value: m ? String(m.value) : '' };
}

function fieldText(field: string, value: string): string {
  return field === 'status' ? (STATUS_LABEL[value as MonObject['status']] ?? value) : value;
}

export function exceptionState(
  e: Exception,
  objects: readonly MonObject[],
  now: Date,
): ExceptionState {
  const d = e.duration;
  if (d.kind === 'until' && now.getTime() >= new Date(d.until).getTime())
    return { state: 'ended', text: `abgelaufen am ${dateText(d.until)}` };
  if (e.bound) {
    const o = objects.find((x) => x.key === e.scope.value);
    const m = o?.metrics.find((x) => x.key === e.bound?.metric);
    if (!m) return { state: 'ended', text: 'der gebundene Wert wird nicht mehr gemeldet' };
    if (m.value !== e.bound.value)
      return {
        state: 'ended',
        text: `${m.label} jetzt ${formatValue(m.value, m.unit)}, gebunden an ${formatValue(e.bound.value, m.unit)}`,
      };
  }
  if (d.kind === 'window' && !inWindow(d, now))
    return { state: 'resting', text: 'außerhalb des Fensters' };
  if (e.condition) {
    const c = e.condition;
    const o = objects.find((x) => x.key === c.object);
    if (!o) return { state: 'resting', text: 'Bedingung: Objekt wird nicht gemeldet' };
    const f = fieldOf(o, c.field);
    if (f.value !== c.equals)
      return {
        state: 'resting',
        text: `Bedingung nicht erfüllt: ${f.label} ${fieldText(c.field, f.value)}`,
      };
  }
  return { state: 'active' };
}

// ---------------------------------------------------------------------------------------------
// texts

const DAY_SHORT = ['', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

export function durationText(d: Duration): string {
  if (d.kind === 'permanent') return 'dauerhaft';
  if (d.kind === 'until') return `bis ${dateText(d.until)}`;
  return `wiederkehrend ${d.days.map((x) => DAY_SHORT[x]).join(', ')} ${d.from}–${d.to} (${d.tz})`;
}

function placeOf(o: MonObject): string {
  return `${objectLabel(o)} auf ${o.server}`;
}

export function conditionText(c: Condition, objects: readonly MonObject[]): string {
  const o = objects.find((x) => x.key === c.object);
  const label = o ? fieldOf(o, c.field).label : c.field;
  return `nur solange ${o ? placeOf(o) : c.object} „${label}: ${fieldText(c.field, c.equals)}“ meldet`;
}

/** The check in words: the module instance, the central target, or the type on its server. */
export function checkText(check: string, objects: readonly MonObject[]): string {
  const o = objects.find((x) => x.key === check);
  if (o) return placeOf(o);
  const [server, type] = check.split('/');
  return `${type} auf ${server}`;
}

/** The scope in words; relative to the object it is attached to, or on its own for the list. */
export function scopeText(s: Scope, objects: readonly MonObject[], own?: MonObject): string {
  const o = objects.find((x) => x.key === s.value);
  switch (s.kind) {
    case 'object':
      return own ? 'dieses Objekt' : o ? placeOf(o) : s.value;
    case 'rule': {
      const text = o?.rules?.find((r) => r.key === s.rule)?.text ?? s.rule;
      return own || !o ? `Regel „${text}“` : `Regel „${text}“ an ${placeOf(o)}`;
    }
    case 'check':
      return `Check ${checkText(s.value, objects)}`;
    case 'check-type':
      return `alle Checks ${s.value}${s.tag ? ` auf Servern mit Tag ${s.tag}` : ''}`;
    case 'server':
      return `Server ${s.value}`;
    case 'tag':
      return `Tag ${s.value}`;
    case 'cluster':
      return `Cluster ${s.value}`;
  }
}

const REVIEW_AFTER_DAYS = 90;

/** Why an exception is put up for review, or nothing (Konzept §8.1: alte zur Prüfung vorgelegt). */
export function reviewReason(e: Exception, count: number, now: Date): string | undefined {
  if (e.reviewed) return undefined;
  if (e.migrated) return `migriert aus ${e.migrated}, wer und wann unbekannt`;
  if (count === 0) return 'betrifft kein Objekt mehr';
  if (e.duration.kind === 'permanent' && e.at) {
    const days = (now.getTime() - new Date(e.at).getTime()) / 86_400_000;
    if (days > REVIEW_AFTER_DAYS) return `dauerhaft, seit über ${REVIEW_AFTER_DAYS} Tagen`;
  }
  return undefined;
}

// ---------------------------------------------------------------------------------------------
// apply

function hides(effect: Effect): boolean {
  return effect === 'skip' || effect === 'no-rating';
}

function infoOf(
  e: Exception,
  o: MonObject,
  objects: readonly MonObject[],
  st: ExceptionState,
): ExceptionInfo {
  return {
    id: e.id,
    effect: e.effect,
    scope: scopeText(e.scope, objects, o),
    reason: e.reason,
    by: e.by ?? MIGRATED_BY,
    at: e.at,
    until: e.duration.kind === 'until' ? e.duration.until : undefined,
    window: e.duration.kind === 'window' ? durationText(e.duration) : undefined,
    condition: e.condition ? conditionText(e.condition, objects) : undefined,
    boundValue: e.bound?.text,
    rule: e.scope.kind === 'rule' ? e.scope.rule : undefined,
    wide: e.scope.kind !== 'object' && e.scope.kind !== 'rule',
    ended: st.state === 'ended' ? st.text : undefined,
  };
}

// A rule taken out of the rating stops firing and the other rules rate on: the object takes the
// worst level still firing, or is ok without one.
function withoutRule(o: MonObject, info: ExceptionInfo): MonObject {
  const rule = o.rules?.find((r) => r.key === info.rule);
  const rules = o.rules?.map((r) => (r.key === info.rule ? { ...r, firing: false } : r));
  if (!rule?.firing) return { ...o, rules, exception: info };
  const left = rules?.filter((r) => r.enabled && r.firing) ?? [];
  const worst = left.find((r) => r.level === 'critical') ?? left[0];
  if (worst?.level === o.status) {
    // Another rule of the level fires on: the reason moves to it when it named the excepted one.
    const reason = o.reason === rule.text ? worst.text : o.reason;
    return { ...o, rules, exception: info, reason };
  }
  if (worst) return { ...o, rules, exception: info, status: worst.level, reason: worst.text };
  return {
    ...o,
    rules,
    exception: info,
    status: 'ok',
    reason: `Regel ausgenommen: ${rule.text}`,
    badSince: undefined,
  };
}

/**
 * Attaches to every object the most specific exception in force; without one in force the most
 * specific ended one, so the object reports again with the reason. A resting exception (outside
 * its window, condition not met) changes nothing and shows only in the list "Ausgeblendet".
 */
export function applyExceptions(
  objects: readonly MonObject[],
  exceptions: readonly Exception[],
  now: Date,
  topo: Topology,
): MonObject[] {
  const states = new Map(exceptions.map((e) => [e.id, exceptionState(e, objects, now)]));
  const rank = (e: Exception) => SPECIFICITY.indexOf(e.scope.kind);
  return objects.map((o) => {
    const own = exceptions
      .filter((e) => covers(e.scope, o, topo))
      .sort((a, b) => rank(a) - rank(b));
    const e =
      own.find((x) => states.get(x.id)?.state === 'active') ??
      own.find((x) => states.get(x.id)?.state === 'ended');
    if (!e) return o;
    const st = states.get(e.id) as ExceptionState;
    const info = infoOf(e, o, objects, st);
    if (st.state === 'ended') return { ...o, exception: info };
    if (e.scope.kind === 'rule')
      return hides(e.effect) ? withoutRule(o, info) : { ...o, exception: info };
    if (e.effect === 'skip')
      return {
        ...o,
        exception: info,
        status: 'not-collected',
        reason: 'Nicht geprüft',
        badSince: undefined,
      };
    return { ...o, exception: info };
  });
}

// ---------------------------------------------------------------------------------------------
// coverage (Konzept §8.4)

/** What happens to a new finding on a server of the profile. */
export type Policy = 'vorschlagen' | 'automatisch';

/** A set of check types bound to tags. */
export interface Profile {
  name: string;
  tags: string[];
  checkTypes: string[];
  policy: Policy;
}

/** Something discovery found on a server that no check watches yet. */
export interface Finding {
  id: string;
  server: string;
  what: string;
  checkType: string;
  foundAt: string;
  decision?: 'taken' | 'declined';
}

export type FindingState = 'open' | 'taken' | 'auto' | 'declined';

export function profilesOf(
  server: string,
  profiles: readonly Profile[],
  topo: Topology,
): Profile[] {
  const tags = tagsOf(server, topo);
  return profiles.filter((p) => p.tags.some((t) => tags.includes(t)));
}

/** Taken silently when a profile of the server covers the type with the policy "automatisch". */
export function findingState(
  f: Finding,
  profiles: readonly Profile[],
  topo: Topology,
): FindingState {
  if (f.decision === 'declined') return 'declined';
  if (f.decision === 'taken') return 'taken';
  const auto = profilesOf(f.server, profiles, topo).some(
    (p) => p.policy === 'automatisch' && p.checkTypes.includes(f.checkType),
  );
  return auto ? 'auto' : 'open';
}

export interface CoverageRow {
  server: string;
  tags: string[];
  profiles: string[];
  watched: number;
  notCollected: number;
  hidden: number;
  /** Findings not watched yet: open ones wait for a decision. */
  open: Finding[];
  auto: Finding[];
}

export function coverageOf(
  objects: readonly MonObject[],
  findings: readonly Finding[],
  profiles: readonly Profile[],
  topo: Topology,
): CoverageRow[] {
  const servers = [...new Set([...objects.map((o) => o.server), ...findings.map((f) => f.server)])];
  servers.sort((a, b) => a.localeCompare(b, 'de'));
  return servers.map((server) => {
    const own = objects.filter((o) => o.server === server);
    const found = findings.filter((f) => f.server === server);
    return {
      server,
      tags: tagsOf(server, topo),
      profiles: profilesOf(server, profiles, topo).map((p) => p.name),
      watched: own.filter((o) => !isHidden(o) && o.status !== 'not-collected').length,
      notCollected: own.filter((o) => !isHidden(o) && o.status === 'not-collected').length,
      hidden: own.filter(isHidden).length,
      open: found.filter((f) => findingState(f, profiles, topo) === 'open'),
      auto: found.filter((f) => findingState(f, profiles, topo) === 'auto'),
    };
  });
}
