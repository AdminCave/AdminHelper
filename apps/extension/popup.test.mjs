// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, 'popup.js'), 'utf8');

// Nur den Funktions-Prolog bis zum Ende von filterConnections uebernehmen.
// Marker stammt aus popup.js (Kommentar-Banner direkt nach filterConnections).
const marker = '// ─── Card rendering';
const cut = source.indexOf(marker);
assert.ok(cut !== -1, 'Marker fuer Funktions-Prolog in popup.js nicht gefunden');
const prologue = source.slice(0, cut);

// Den Haupt-Realm als globalen Kontext nutzen (statt vm.createContext), damit
// im Sandbox erzeugte Arrays/Objekte dieselben Prototypen haben wie im Test —
// sonst scheitert assert.deepStrictEqual an "same structure but not
// reference-equal" (Cross-Realm-Prototypen).
// Minimaler document-Stub: popup.js holt sich im Prolog (Zeilen 10-31) per
// getElementById die DOM-Refs. Die zu testenden Funktionen nutzen diese Refs
// nicht, daher reicht ein No-op-Stub, damit der Prolog ohne Browser laeuft.
const sandbox = globalThis;
sandbox.document = { getElementById: () => null };
// 'use strict' ist bereits im Quelltext enthalten; daher die Funktionen
// explizit an globalThis haengen, damit sie aus dem Test sichtbar sind.
vm.runInThisContext(
  prologue +
    '\nglobalThis.parseTags = parseTags;' +
    '\nglobalThis.filterConnections = filterConnections;' +
    '\nglobalThis.escapeHtml = escapeHtml;',
);
const { parseTags, filterConnections, escapeHtml } = globalThis;

test('parseTags: leerer/falsy Input ergibt leeres Array', () => {
  assert.deepEqual(parseTags(''), []);
  assert.deepEqual(parseTags(null), []);
  assert.deepEqual(parseTags(undefined), []);
});

test('parseTags: trennt an Kommata und trimmt', () => {
  assert.deepEqual(parseTags('a,b,c'), ['a', 'b', 'c']);
  assert.deepEqual(parseTags(' a , b ,c '), ['a', 'b', 'c']);
});

test('parseTags: filtert leere Segmente (doppelte Kommata, fuehrend/abschliessend)', () => {
  assert.deepEqual(parseTags('a,,b,'), ['a', 'b']);
  assert.deepEqual(parseTags(',a,'), ['a']);
  assert.deepEqual(parseTags('   '), []);
});

test('escapeHtml: maskiert &, <, >, "', () => {
  assert.equal(escapeHtml('<a href="x">&'), '&lt;a href=&quot;x&quot;&gt;&amp;');
});

test('escapeHtml: & wird zuerst ersetzt (kein Doppel-Escaping)', () => {
  // Wenn & nicht zuerst kaeme, wuerde aus < -> &lt; ein &amp;lt; werden.
  assert.equal(escapeHtml('<'), '&lt;');
  assert.equal(escapeHtml('&amp;'), '&amp;amp;');
});

test('escapeHtml: null/undefined werden zu leerem String', () => {
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
});

test('escapeHtml: nicht-string Input wird gecastet', () => {
  assert.equal(escapeHtml(42), '42');
});

const conns = [
  { name: 'Router', url: 'http://192.168.0.1', notes: 'Gateway', tags: 'netz, prod' },
  { name: 'NAS', url: 'http://nas.local', notes: '', tags: 'storage' },
  { name: 'Switch', url: 'http://sw1', tags: '' },
];

test('filterConnections: leere Query liefert alle (unveraendert)', () => {
  assert.equal(filterConnections(conns, ''), conns);
  assert.equal(filterConnections(conns, null), conns);
});

test('filterConnections: matcht Name (case-insensitive)', () => {
  assert.deepEqual(filterConnections(conns, 'ROUTER').map(c => c.name), ['Router']);
});

test('filterConnections: matcht URL', () => {
  assert.deepEqual(filterConnections(conns, 'nas.local').map(c => c.name), ['NAS']);
});

test('filterConnections: matcht Notes', () => {
  assert.deepEqual(filterConnections(conns, 'gateway').map(c => c.name), ['Router']);
});

test('filterConnections: matcht Tags', () => {
  assert.deepEqual(filterConnections(conns, 'storage').map(c => c.name), ['NAS']);
  assert.deepEqual(filterConnections(conns, 'prod').map(c => c.name), ['Router']);
});

test('filterConnections: kein Treffer liefert leeres Array', () => {
  assert.deepEqual(filterConnections(conns, 'xyz-nope'), []);
});

test('filterConnections: behandelt fehlende Felder ohne Wurf', () => {
  const partial = [{ name: 'OnlyName' }];
  assert.deepEqual(filterConnections(partial, 'onlyname').map(c => c.name), ['OnlyName']);
  assert.deepEqual(filterConnections(partial, 'http'), []);
});
