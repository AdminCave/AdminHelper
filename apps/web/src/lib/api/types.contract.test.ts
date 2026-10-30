// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

/**
 * The hand-written interfaces of types.ts vs. the server's OpenAPI snapshot (R-0686).
 *
 * types.ts describes the server API a second time, and nothing compared the two: a
 * field the server sends as null was typed as a plain string, and the compiler then
 * vouched for code that breaks on the first null. This test reads types.ts with the
 * TypeScript compiler API and holds each mapped interface against its schema.
 *
 * Compared are keys, optionality, nullability and the kind of primitive fields
 * (spec api-contracts, rules for the client contract test), not the depth of free
 * form fields. A response type may be wider than its schema (optional or nullable
 * where the schema is not); a request type may not ask for less than the schema
 * requires, nor send null where the schema forbids it.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import ts from 'typescript';

const HERE = dirname(fileURLToPath(import.meta.url));
// src/lib/api -> the repo root
const ROOT = join(HERE, '..', '..', '..', '..', '..');
const SNAPSHOT = join(ROOT, 'apps', 'server', 'tests', 'openapi.snapshot.json');
const TYPES = join(HERE, 'types.ts');

interface Schema {
  $ref?: string;
  type?: string | string[];
  enum?: unknown[];
  items?: Schema;
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean | Schema;
  anyOf?: Schema[];
  allOf?: Schema[];
}

type Schemas = Record<string, Schema>;
type Kind = 'string' | 'number' | 'boolean' | 'array' | 'other';
type Direction = 'response' | 'request';

interface Mapping {
  ts: string;
  // More than one schema: the interface stands for several answers (fields
  // required only where every schema requires them).
  schema: string | string[];
  direction: Direction;
  omit?: Record<string, string>;
}

const MAPPINGS: Mapping[] = [
  {
    ts: 'LoginResponse',
    schema: 'TokenResponse',
    direction: 'response',
    omit: { refresh_token: 'the browser keeps it only in the HttpOnly cookie' },
  },
  {
    ts: 'RefreshResponse',
    schema: 'TokenResponse',
    direction: 'response',
    omit: { refresh_token: 'the browser keeps it only in the HttpOnly cookie' },
  },
  // GET /api/auth/me and the user list share one type in this client.
  { ts: 'User', schema: ['UserResponse', 'UserMe'], direction: 'response' },
  { ts: 'EnrollmentGrant', schema: 'EnrollmentGrantOut', direction: 'response' },
  { ts: 'ApiKey', schema: 'ApiKeyResponse', direction: 'response' },
  { ts: 'ApiKeyCreateResult', schema: 'ApiKeyCreatedResponse', direction: 'response' },
  { ts: 'ServerSummary', schema: 'ServerSummary', direction: 'response' },
  { ts: 'Hook', schema: 'HookResponse', direction: 'response' },
  { ts: 'HookDetail', schema: 'HookDetailResponse', direction: 'response' },
  { ts: 'HookCreateResult', schema: 'HookCreatedResponse', direction: 'response' },
  { ts: 'HookTokenResult', schema: 'HookTokenOut', direction: 'response' },
  {
    ts: 'FrpConfig',
    schema: 'FrpServerConfigOut',
    direction: 'response',
    omit: { extraConfig: 'free form frps settings; no client reads or edits them' },
  },
  {
    ts: 'FrpStatusProxy',
    schema: 'FrpStatusProxy',
    direction: 'response',
    omit: { tunnel: 'the matched tunnel row; no client reads it' },
  },
  { ts: 'FrpStatus', schema: 'FrpStatus', direction: 'response' },
  { ts: 'AuditEntry', schema: 'AuditLogOut', direction: 'response' },
  { ts: 'UserCreate', schema: 'UserCreate', direction: 'request' },
  { ts: 'UserUpdate', schema: 'UserUpdate', direction: 'request' },
  { ts: 'ApiKeyCreate', schema: 'ApiKeyCreate', direction: 'request' },
  { ts: 'HookCreate', schema: 'HookCreate', direction: 'request' },
  { ts: 'HookUpdate', schema: 'HookUpdate', direction: 'request' },
  { ts: 'FrpConfigInput', schema: 'FrpServerConfigCreate', direction: 'request' },
];

// Interfaces of types.ts that describe no server schema.
const EXEMPT: Record<string, string> = {
  HookRunResult: 'the run route returns the script result as it comes (spec non-goal)',
  AuditQuery: 'query string parameters, not a JSON body',
};

// ── TypeScript side ─────────────────────────────────────────────────────

interface TsField {
  optional: boolean;
  nullable: boolean;
  kinds: Set<Kind>;
}

function tsKinds(
  node: ts.TypeNode,
  aliases: Map<string, ts.TypeNode>,
  out: { kinds: Set<Kind>; nullable: boolean },
): void {
  if (ts.isUnionTypeNode(node)) {
    for (const t of node.types) tsKinds(t, aliases, out);
    return;
  }
  if (ts.isParenthesizedTypeNode(node)) return tsKinds(node.type, aliases, out);
  if (ts.isLiteralTypeNode(node)) {
    if (node.literal.kind === ts.SyntaxKind.NullKeyword) out.nullable = true;
    else if (ts.isStringLiteral(node.literal)) out.kinds.add('string');
    else if (ts.isNumericLiteral(node.literal)) out.kinds.add('number');
    else out.kinds.add('boolean');
    return;
  }
  switch (node.kind) {
    case ts.SyntaxKind.StringKeyword:
      out.kinds.add('string');
      return;
    case ts.SyntaxKind.NumberKeyword:
      out.kinds.add('number');
      return;
    case ts.SyntaxKind.BooleanKeyword:
      out.kinds.add('boolean');
      return;
    case ts.SyntaxKind.UndefinedKeyword:
      return;
  }
  if (ts.isArrayTypeNode(node)) {
    out.kinds.add('array');
    return;
  }
  if (ts.isTypeReferenceNode(node) && ts.isIdentifier(node.typeName)) {
    const alias = aliases.get(node.typeName.text);
    if (alias) return tsKinds(alias, aliases, out);
  }
  out.kinds.add('other');
}

/** Every interface of a source text with its fields, `extends` resolved. */
function readInterfaces(source: string): Map<string, Map<string, TsField>> {
  const file = ts.createSourceFile('types.ts', source, ts.ScriptTarget.Latest, true);
  const decls = new Map<string, ts.InterfaceDeclaration>();
  const aliases = new Map<string, ts.TypeNode>();
  for (const st of file.statements) {
    if (ts.isInterfaceDeclaration(st)) decls.set(st.name.text, st);
    if (ts.isTypeAliasDeclaration(st)) aliases.set(st.name.text, st.type);
  }

  const resolved = new Map<string, Map<string, TsField>>();
  function resolve(name: string): Map<string, TsField> {
    const done = resolved.get(name);
    if (done) return done;
    const decl = decls.get(name);
    if (!decl) throw new Error(`interface ${name} not found`);
    const fields = new Map<string, TsField>();
    for (const clause of decl.heritageClauses ?? []) {
      for (const base of clause.types) {
        if (!ts.isIdentifier(base.expression)) throw new Error(`${name}: unreadable extends`);
        for (const [k, v] of resolve(base.expression.text)) fields.set(k, v);
      }
    }
    for (const m of decl.members) {
      if (!ts.isPropertySignature(m) || !m.type) continue;
      const out = { kinds: new Set<Kind>(), nullable: false };
      tsKinds(m.type, aliases, out);
      fields.set(m.name.getText(file), {
        optional: m.questionToken !== undefined,
        nullable: out.nullable,
        kinds: out.kinds,
      });
    }
    resolved.set(name, fields);
    return fields;
  }
  for (const name of decls.keys()) resolve(name);
  return resolved;
}

// ── Schema side ─────────────────────────────────────────────────────────

interface SchemaField {
  required: boolean;
  nullable: boolean;
  kinds: Set<Kind>;
}

interface SchemaShape {
  fields: Map<string, SchemaField>;
  open: boolean;
}

function deref(schemas: Schemas, s: Schema): Schema {
  let cur = s;
  const seen = new Set<string>();
  while (cur.$ref) {
    const name = cur.$ref.replace('#/components/schemas/', '');
    if (seen.has(name)) break;
    seen.add(name);
    const next = schemas[name];
    if (!next) throw new Error(`unknown schema ${name}`);
    cur = next;
  }
  return cur;
}

function schemaKinds(
  schemas: Schemas,
  raw: Schema,
  out: { kinds: Set<Kind>; nullable: boolean },
): void {
  const s = deref(schemas, raw);
  for (const branch of [...(s.anyOf ?? []), ...(s.allOf ?? [])]) schemaKinds(schemas, branch, out);
  if (s.anyOf || s.allOf) return;
  const types = Array.isArray(s.type) ? s.type : s.type ? [s.type] : [];
  if (types.length === 0) out.kinds.add('other');
  for (const t of types) {
    if (t === 'null') out.nullable = true;
    else if (t === 'string') out.kinds.add('string');
    else if (t === 'integer' || t === 'number') out.kinds.add('number');
    else if (t === 'boolean') out.kinds.add('boolean');
    else if (t === 'array') out.kinds.add('array');
    else out.kinds.add('other');
  }
}

/** One or several component schemas merged into one shape. */
function schemaShape(schemas: Schemas, names: string[]): SchemaShape {
  const fields = new Map<string, SchemaField>();
  let open = false;
  const parts = names.map((n) => {
    const s = schemas[n];
    if (!s) throw new Error(`unknown schema ${n}`);
    return s;
  });
  for (const s of parts) {
    if (s.additionalProperties === true || (s.type === 'object' && !s.properties)) open = true;
    const required = new Set(s.required ?? []);
    for (const [key, prop] of Object.entries(s.properties ?? {})) {
      const out = { kinds: new Set<Kind>(), nullable: false };
      schemaKinds(schemas, prop, out);
      const prev = fields.get(key);
      fields.set(key, {
        required: (prev?.required ?? true) && required.has(key),
        nullable: (prev?.nullable ?? false) || out.nullable,
        kinds: new Set([...(prev?.kinds ?? []), ...out.kinds]),
      });
    }
  }
  // A field that one of the merged schemas lacks is not always sent.
  for (const [key, f] of fields) {
    if (parts.some((s) => !(key in (s.properties ?? {})))) f.required = false;
  }
  return { fields, open };
}

// ── The rules ───────────────────────────────────────────────────────────

const PRIMITIVE: Kind[] = ['string', 'number', 'boolean', 'array'];

function primitiveOnly(kinds: Set<Kind>): boolean {
  return kinds.size > 0 && [...kinds].every((k) => PRIMITIVE.includes(k));
}

/** Rule violations of one interface against its schema shape, as readable lines. */
function compare(
  tsFields: Map<string, TsField>,
  shape: SchemaShape,
  direction: Direction,
  omit: Record<string, string> = {},
): string[] {
  const problems: string[] = [];
  for (const [key, f] of tsFields) {
    const s = shape.fields.get(key);
    if (!s) {
      if (!shape.open) problems.push(`${key}: not a schema field`);
      continue;
    }
    if (key in omit) problems.push(`${key}: in omit but described`);
    if (direction === 'response') {
      if (!s.required && !f.optional) problems.push(`${key}: not required, needs ?`);
      if (s.nullable && !f.nullable) problems.push(`${key}: nullable, needs | null`);
    } else {
      if (s.required && f.optional) problems.push(`${key}: required, must not have ?`);
      if (f.nullable && !s.nullable) problems.push(`${key}: not nullable, must not allow null`);
    }
    if (primitiveOnly(f.kinds) && primitiveOnly(s.kinds)) {
      const a = [...f.kinds].sort().join('|');
      const b = [...s.kinds].sort().join('|');
      if (a !== b) problems.push(`${key}: kind ${a}, schema ${b}`);
    }
  }
  for (const [key, s] of shape.fields) {
    if (tsFields.has(key) || key in omit) continue;
    if (direction === 'response') problems.push(`${key}: schema field missing`);
    else if (s.required) problems.push(`${key}: required schema field missing`);
  }
  for (const key of Object.keys(omit)) {
    if (!shape.fields.has(key)) problems.push(`${key}: in omit but not a schema field`);
  }
  return problems;
}

// ── The test ────────────────────────────────────────────────────────────

const spec = JSON.parse(readFileSync(SNAPSHOT, 'utf-8')) as {
  components?: { schemas?: Schemas };
};
const SCHEMAS: Schemas = spec.components?.schemas ?? {};
const INTERFACES = readInterfaces(readFileSync(TYPES, 'utf-8'));

const names = (m: Mapping) => (Array.isArray(m.schema) ? m.schema : [m.schema]);

describe('types.ts vs. the server OpenAPI snapshot', () => {
  it('maps every interface, and every mapping names what exists', () => {
    // Pinned at the real number: a mapping quietly dropped is a failure, not a smaller green.
    expect(MAPPINGS.length).toBe(21);
    expect(MAPPINGS.filter((m) => !INTERFACES.has(m.ts)).map((m) => m.ts)).toEqual([]);
    expect(MAPPINGS.flatMap(names).filter((n) => !SCHEMAS[n])).toEqual([]);
    const classified = new Set([...MAPPINGS.map((m) => m.ts), ...Object.keys(EXEMPT)]);
    expect([...INTERFACES.keys()].filter((n) => !classified.has(n)).sort()).toEqual([]);
    expect(Object.keys(EXEMPT).filter((n) => !INTERFACES.has(n))).toEqual([]);
  });

  it('describes each mapped schema as the rules ask', () => {
    const drift: Record<string, string[]> = {};
    for (const m of MAPPINGS) {
      const fields = INTERFACES.get(m.ts);
      if (!fields) continue; // reported by the guard above
      const problems = compare(fields, schemaShape(SCHEMAS, names(m)), m.direction, m.omit);
      if (problems.length) drift[m.ts] = problems;
    }
    expect(drift).toEqual({});
  });
});

describe('the contract rules catch each kind of drift', () => {
  const schemas: Schemas = {
    Out: {
      type: 'object',
      properties: {
        id: { type: 'integer' },
        name: { type: 'string' },
        note: { anyOf: [{ type: 'string' }, { type: 'null' }] },
        tags: { type: 'array', items: { type: 'string' } },
        extra: { type: 'object' },
      },
      required: ['id', 'name', 'note'],
    },
    In: {
      type: 'object',
      properties: {
        name: { type: 'string' },
        size: { type: 'integer' },
      },
      required: ['name'],
    },
    Other: {
      type: 'object',
      properties: { id: { type: 'integer' }, flag: { type: 'boolean' } },
      required: ['id', 'flag'],
    },
  };
  const good = `
    type Label = 'a' | 'b';
    interface Base { id: number; }
    export interface Out extends Base { name: Label; note: string | null; tags?: string[]; extra?: unknown; }
    export interface In { name: string; size?: number; }
  `;

  function check(source: string, name: string, schema: string[], dir: Direction, omit = {}) {
    const fields = readInterfaces(source).get(name);
    if (!fields) throw new Error(`no ${name}`);
    return compare(fields, schemaShape(schemas, schema), dir, omit);
  }

  it('passes a matching pair, with extends and an alias resolved', () => {
    expect(check(good, 'Out', ['Out'], 'response')).toEqual([]);
    expect(check(good, 'In', ['In'], 'request')).toEqual([]);
  });

  it('flags a field the schema does not declare', () => {
    const src = good.replace('extra?: unknown;', 'extra?: unknown; ghost: string;');
    expect(check(src, 'Out', ['Out'], 'response')).toEqual(['ghost: not a schema field']);
  });

  it('flags a schema field the response type leaves out, unless omitted', () => {
    const src = good.replace(' extra?: unknown;', '');
    expect(check(src, 'Out', ['Out'], 'response')).toEqual(['extra: schema field missing']);
    expect(check(src, 'Out', ['Out'], 'response', { extra: 'why' })).toEqual([]);
    expect(check(good, 'Out', ['Out'], 'response', { extra: 'why' })).toEqual([
      'extra: in omit but described',
    ]);
    expect(check(src, 'Out', ['Out'], 'response', { extra: 'why', gone: 'why' })).toEqual([
      'gone: in omit but not a schema field',
    ]);
  });

  it('flags a response field without ? that the schema does not require', () => {
    const src = good.replace('tags?: string[]', 'tags: string[]');
    expect(check(src, 'Out', ['Out'], 'response')).toEqual(['tags: not required, needs ?']);
  });

  it('flags a nullable schema field the response type gives no null', () => {
    const src = good.replace('note: string | null', 'note: string');
    expect(check(src, 'Out', ['Out'], 'response')).toEqual(['note: nullable, needs | null']);
  });

  it('flags a primitive of the wrong kind', () => {
    const src = good.replace('interface Base { id: number; }', 'interface Base { id: string; }');
    expect(check(src, 'Out', ['Out'], 'response')).toEqual(['id: kind string, schema number']);
  });

  it('flags a request that leaves out a required field or sends a forbidden null', () => {
    const optional = good.replace('In { name: string;', 'In { name?: string;');
    expect(check(optional, 'In', ['In'], 'request')).toEqual(['name: required, must not have ?']);
    const nulled = good.replace('size?: number;', 'size?: number | null;');
    expect(check(nulled, 'In', ['In'], 'request')).toEqual([
      'size: not nullable, must not allow null',
    ]);
  });

  it('flags a required schema field the request type leaves out, unless omitted', () => {
    const src = good.replace('In { name: string; size?: number; }', 'In { size?: number; }');
    expect(check(src, 'In', ['In'], 'request')).toEqual(['name: required schema field missing']);
    expect(check(src, 'In', ['In'], 'request', { name: 'why' })).toEqual([]);
    // An optional schema field a request does not send is fine.
    const noSize = good.replace('In { name: string; size?: number; }', 'In { name: string; }');
    expect(check(noSize, 'In', ['In'], 'request')).toEqual([]);
  });

  it('requires a field of merged schemas only where every schema requires it', () => {
    const src =
      'export interface Both { id: number; name: string; note: string | null; flag: boolean; }';
    expect(check(src, 'Both', ['Out', 'Other'], 'response', { tags: 'x', extra: 'x' })).toEqual([
      'name: not required, needs ?',
      'note: not required, needs ?',
      'flag: not required, needs ?',
    ]);
  });
});
