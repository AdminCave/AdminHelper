<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: FRP-Konfigurationsvorschau beim Schließen leeren

Stand des Codes: `origin/main@237b450a`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/web-frp-preview.md`. Härtung (Kevin 2026-10-22), Folgepaket zu `web-store-cleanup`.

## Problem / Motivation

Die FRP-Seite zeigt `frps.toml` und `visitor.toml` in einer Vorschau (`apps/web/src/pages/Frp.svelte:162-167`).
`showPreview` (`:122-131`) holt den Text vom Server und legt ihn in den Seitenzustand `previewContent` (`:67`,
`:126`); der Dialog bekommt ihn als Prop (`:262-267`). Beim Schließen setzt die Seite nur `previewOpen = false`
(`:266`); der Text bleibt in `previewContent`, bis die FRP-Seite verlassen wird. Er trägt Zugangsdaten:
`frps.toml` das `auth.token` und das Dashboard-Passwort (`apps/server/app/modules/frp/config_generator.py:221`,
`:226`), `visitor.toml` das `auth.token` und die STCP-`secretKey`s (`:331`, `:354`).

Die anderen Dialoge mit einmalig gezeigten Werten leeren beim Schließen schon: der Webhook-Token
(`apps/web/src/pages/Hooks.svelte:224-228`), der API-Key (`apps/web/src/pages/ApiKeys.svelte:46-49`), der
Enrollment-Token (`apps/web/src/modals/EnrollTokenModal.svelte:40-47`). Die Stores halten seit `web-store-cleanup`
keine Zugangsdaten der FRP-Server-Konfiguration mehr (`docs/developer/webui.html:64`).

## Ziel & Nicht-Ziele

Ziel:
- Schließt die Vorschau, auf welchem Weg auch immer (Knopf „Schließen“, ×, Escape, Klick auf den Hintergrund), ist
  `previewContent` leer. Solange sie offen ist, zeigt sie den Text wie bisher; erneutes Öffnen holt ihn neu (wie
  heute, `Frp.svelte:122-131`).
- Ein Komponenten-Test pinnt das, und er ist ohne den Fix rot.

Nicht-Ziele (YAGNI):
- Keine Änderung an `FrpConfigPreviewModal.svelte`, `Modal.svelte`, am Server oder an der API.
- Der Titel der Vorschau (`previewTitle`, `:66`) bleibt stehen: er ist nur der Dateiname.
- Kein Leeren der Zwischenablage nach „Kopieren“ (`FrpConfigPreviewModal.svelte:22-29`): das ist eine Handlung des
  Nutzers.
- Keine Reihenfolge für zwei schnell nacheinander geklickte Vorschau-Knöpfe (heute gewinnt die spätere Antwort,
  Titel und Text kommen dabei immer paarweise, `:125-127`).
- Der ZIP-Download (`:133-148`) bleibt: er hält nur eine Blob-URL, die nach 1 s freigegeben wird (`:143`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | web | `apps/web/src/pages/Frp.svelte`, `apps/web/src/pages/Frp.preview.test.ts` (neu), `CHANGELOG.md` |

Kein Pfad aus `scripts/dev/review-risk.txt`.

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Schema, OpenAPI unverändert. Die Props von `FrpConfigPreviewModal` bleiben. Kein
Vertrags-Drift zu Desktop oder Agent (die Vorschau gibt es nur im Web-Panel).

## Externe Integrationen

Keine. Der Test nutzt, wie Svelte 5 eine eingebundene Komponente aufruft: als Funktion `(anchor, props)`, die Props
als Getter auf den Zustand der Elternkomponente. Belegt (Probe 2026-10-22, `svelte/compiler` 5.56.2, `generate:
'client'`, `dev` an und aus): `Frp.svelte` wird zu `FrpConfigPreviewModal(node, { get open() {…}, get title() {…},
get content() { return $.get(previewContent); }, onClose: () => $.set(previewOpen, false) })`. Das ist keine
dokumentierte API; dieselbe Naht nutzt die Desktop-UI schon (`vi.fn()` als Komponente,
`apps/desktop/ui/src/components/AppShell.workspace.test.ts:60-70`).

## Trade-offs & Alternativen

1. **Wo geleert wird.** (a) In der Seite, im `onClose` der Vorschau (`Frp.svelte:266`) — **Empfehlung**: jeder
   Schließweg läuft über diese eine Prop (`FrpConfigPreviewModal.svelte:32`, `:37`; `Modal.svelte:28-30`), und so
   machen es `Hooks.svelte:224-228` und `ApiKeys.svelte:46-49`. (b) Ein `$effect`, der bei `previewOpen === false`
   leert: indirekter, ein Effekt, der Zustand schreibt. (c) Den Abruf in den Dialog verlegen (holt beim Öffnen, leert
   beim Schließen, wie `EnrollTokenModal.svelte:40-47`): neue Prop, eigene Fehlerbehandlung im Dialog, mehr Code für
   dasselbe Ergebnis.
2. **Testnaht.** Die echte `Modal` rendert geschlossen nichts (`apps/web/src/lib/components/ui/Modal.svelte:71`); ein
   Test, der nach dem Schließen nur das DOM prüft, wäre auch ohne den Fix grün. (a) `FrpConfigPreviewModal` per
   `vi.mock` durch ein `vi.fn()` ersetzen und die Props aus dem Aufruf lesen — **Empfehlung**: prüft genau, was die
   Seite dem Dialog gibt, keine neue `.svelte`-Datei, Vorbild in der Desktop-UI. (b) Eine Stub-Komponente als
   `.svelte`-Datei, die `content` immer rendert: gleiche Aussage, eine Datei mehr. (c) `Modal.svelte` stubben, damit
   die echte Vorschau ihr `<pre>` immer rendert: koppelt den Test an den Aufbau der Vorschau, und die zwei anderen,
   geschlossenen Dialoge der Seite rendern ihren Inhalt mit.
3. **Eigene Testdatei** `Frp.preview.test.ts` statt `Frp.test.ts`: `Frp.test.ts` gilt dem frps-Statusblock (Kopf
   `:7-15`) und mockt `listConfigs` leer (`:149`), sodass die Vorschau-Knöpfe fehlen (`Frp.svelte:161`); `vi.mock`
   gilt je Datei, der Stub soll die Statusblock-Tests nicht berühren.

## Risiken & Rollback

- Sichtbar ändert sich nichts: geschlossen rendert die Vorschau nichts, und jedes Öffnen holt den Text neu.
- Ändert Svelte die Aufrufform einer Komponente (Abschnitt „Externe Integrationen“), wird der Test laut rot (Stub
  nicht aufgerufen oder `content` ohne Getter), nicht still grün.
- Ob der Browser den String danach sofort freigibt, steuert der Garbage Collector; die Seite hält ihn nicht mehr.
- Rollback: ein Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

CHANGELOG (Changed, wie der Eintrag von `web-store-cleanup`). `docs/` keine: keine Seite beschreibt die Vorschau
über die Knöpfe hinaus, und `docs/developer/webui.html:64` gilt den Stores.

## Offene Fragen

Keine.
