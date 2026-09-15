// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

/**
 * Playwright mock bodies vs. the server's OpenAPI snapshot (harness 8a, T13).
 *
 * tests/e2e/mocks.ts is a second description of the server API, written by hand.
 * Nothing checked it against the first, so a renamed response field left the E2E
 * suite green — the mocks kept answering in the old shape — while the real app
 * broke. That is the worst kind of green: a full user journey passing against a
 * server that no longer exists.
 *
 * Compared are KEY SETS, not types (spec trade-off 3): every `required` field of
 * the response schema must be present in the mock body, and every mock key must
 * be a declared property. That catches renames and forgotten required fields
 * without pulling in a JSON-Schema validator.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { MOCK_FIXTURES, type MockFixture } from '../../../tests/e2e/mocks';

// src/lib/api -> the repo root
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..');
const SNAPSHOT = join(ROOT, 'apps', 'server', 'tests', 'openapi.snapshot.json');

interface Schema {
  $ref?: string;
  type?: string;
  items?: Schema;
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean | Schema;
  anyOf?: Schema[];
  allOf?: Schema[];
}

const spec = JSON.parse(readFileSync(SNAPSHOT, 'utf-8')) as {
  paths: Record<string, Record<string, { responses?: Record<string, unknown> }>>;
  components?: { schemas?: Record<string, Schema> };
};

function deref(schema: Schema | undefined, seen = new Set<string>()): Schema | undefined {
  if (!schema?.$ref) return schema;
  const name = schema.$ref.replace('#/components/schemas/', '');
  if (seen.has(name)) return undefined; // recursive model — nothing more to learn
  seen.add(name);
  return deref(spec.components?.schemas?.[name], seen);
}

/** The JSON response schema of one operation, or undefined if it declares none. */
function responseSchema(fixture: MockFixture): Schema | undefined {
  const op = spec.paths[`/api/${fixture.path}`]?.[fixture.method.toLowerCase()];
  const responses = op?.responses as
    | Record<string, { content?: Record<string, { schema?: Schema }> }>
    | undefined;
  const body = responses?.[String(fixture.status)]?.content?.['application/json']?.schema;
  return deref(body);
}

/** Properties and required names, following anyOf/allOf one level (nullable models). */
function shapeOf(schema: Schema): {
  properties: Set<string>;
  required: Set<string>;
  open: boolean;
} {
  const branches = schema.anyOf ?? schema.allOf ?? [schema];
  const properties = new Set<string>();
  const required = new Set<string>();
  let open = false;
  for (const raw of branches) {
    const b = deref(raw);
    if (!b) continue;
    for (const key of Object.keys(b.properties ?? {})) properties.add(key);
    for (const key of b.required ?? []) required.add(key);
    if (b.additionalProperties === true) open = true;
    // A bare `type: object` with no properties declares nothing to compare.
    if (b.type === 'object' && !b.properties) open = true;
  }
  return { properties, required, open };
}

describe('playwright mocks vs. the server OpenAPI snapshot', () => {
  it('assigns every fixture to an operation (non-empty guard)', () => {
    expect(MOCK_FIXTURES.length).toBeGreaterThanOrEqual(8);
    const unassignable = MOCK_FIXTURES.filter(
      (f) => !spec.paths[`/api/${f.path}`]?.[f.method.toLowerCase()],
    )
      .map((f) => `${f.method} /api/${f.path}`)
      .sort();
    expect(unassignable).toEqual([]);
    expect(Object.keys(spec.paths).length).toBeGreaterThanOrEqual(20);
  });

  it('answers each operation in the shape the server declares', () => {
    const drift: Record<string, { missingRequired?: string[]; unknownKeys?: string[] }> = {};
    let checked = 0;

    for (const fixture of MOCK_FIXTURES) {
      const label = `${fixture.method} /api/${fixture.path}`;
      let schema = responseSchema(fixture);
      if (!schema) continue; // no declared JSON body (e.g. a plain 204/200 without content)

      let body: unknown = fixture.body;
      if (schema.type === 'array') {
        const items = deref(schema.items);
        if (!items || !Array.isArray(body) || body.length === 0) continue;
        schema = items;
        body = body[0];
      }
      if (typeof body !== 'object' || body === null || Array.isArray(body)) continue;

      const { properties, required, open } = shapeOf(schema);
      if (properties.size === 0) continue; // nothing declared -> nothing to pin

      checked += 1;
      const keys = Object.keys(body as Record<string, unknown>);
      const missingRequired = [...required].filter((r) => !keys.includes(r)).sort();
      const unknownKeys = open ? [] : keys.filter((k) => !properties.has(k)).sort();
      if (missingRequired.length || unknownKeys.length) {
        drift[label] = {
          ...(missingRequired.length ? { missingRequired } : {}),
          ...(unknownKeys.length ? { unknownKeys } : {}),
        };
      }
    }

    expect(drift).toEqual({});

    // Four `continue` paths above skip a fixture silently — most often because
    // the server route declares no response_model at all (six do). Without this
    // the checked set could drain to zero while the test stayed green, which is
    // exactly the kind of quiet green this whole stage exists to prevent.
    expect(checked, 'too few fixtures actually reached a key check').toBeGreaterThanOrEqual(8);
  });
});
