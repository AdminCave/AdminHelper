<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web-Stores: nach dem Anlegen nur die Felder der Liste halten

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/web-store-cleanup.md`. Härtung (Kevin 2026-10-22).

## Problem / Motivation

1. **Hooks-Store.** `hooks.create` (`apps/web/src/lib/stores/hooks.ts:24-29`) hängt die ganze Antwort von
   `POST /api/hooks` an die Liste (`:27`). Diese Antwort ist `HookCreatedResponse`
   (`apps/server/app/modules/hooks/schemas.py:74-75`): die Listenfelder plus `script` und bei einem Webhook den
   einmalig angezeigten `token` (`apps/server/app/modules/hooks/router.py:172-175`). `hooks.update` (`:31-36`) merged
   die `HookDetail`-Antwort samt `script` in den Eintrag (`:34`). Die Liste aus `GET /api/hooks` trägt beides nicht
   (`response_model=list[HookResponse]`, `router.py:127`; `schemas.py:57-67`). Der Store ist ein Modul-`writable`
   (`hooks.ts:9`) und hält beides, bis die Seite neu lädt, auch nachdem `apps/web/src/pages/Hooks.svelte:224-228` den
   angezeigten Token beim Schließen des Dialogs geleert hat. Ein Hook-Skript trägt oft Zugangsdaten (das Beispiel
   `docs/examples/event_hook_notify.py:19` eine Webhook-URL mit Token im Pfad).

2. **FRP-Store.** `frpConfig.save` (`apps/web/src/lib/stores/frp.ts:19-25`) legt die Antwort ungekürzt ab (`:23`).
   Nach einem Anlegen ist das `config.to_dict()` ohne Maske (`apps/server/app/modules/frp/config_router.py:96`), also
   `authToken` und `dashboardPassword` im Klartext, auch die vom Server erzeugten (`:64`, `:72-74`). `GET` und `PUT`
   liefern beide als `null` (`:38`, `:106`, `:189`); das Modell begründet das in
   `apps/server/app/modules/frp/models.py:42-46`: „the client never needs them read back“. Die Web-Oberfläche liest
   beide Werte nirgends: das Formular füllt sie nie vor (`apps/web/src/modals/FrpConfigModal.svelte:49-57`),
   `restartsFrps` vergleicht sie nicht (`:85-96`), die Rückgabe von `save` wird verworfen (`:136`).

3. **Vorbild im selben Verzeichnis.** `apikeys.create` (`apps/web/src/lib/stores/apikeys.ts:24-32`) legt nur `id`,
   `name` und `permission` in die Liste (`:27-30`) und gibt den Key nur dem Aufrufer; gepinnt in
   `apps/web/src/lib/stores/apikeys.test.ts:35-50`.

## Ziel & Nicht-Ziele

Ziel:
- Nach `create` und `update` hält der Hooks-Store je Hook genau die Felder von `Hook`
  (`apps/web/src/lib/api/types.ts:93-104`), also die der Listenantwort; kein `token`, kein `script`. `create` gibt die
  ganze Antwort weiter an den Aufrufer zurück (der Token wird wie bisher einmal angezeigt).
- Der FRP-Store hält die Konfiguration nach `save` so, wie `GET` sie liefert: `authToken` und `dashboardPassword` sind
  `null`; `save` gibt dasselbe Objekt zurück.
- Tests pinnen beides; die Feldliste der Hooks ist gegen den Typ `Hook` geprüft.

Nicht-Ziele (YAGNI):
- Keine Änderung am Server und an der API: die Antwort von `POST /api/frp/server-config` bleibt
  (`config_router.py:186-188`), keine Route, kein Schema, `types.ts` bleibt.
- Kein Leeren der Stores beim Abmelden (R-0653, Paket web-fixes).
- Kein gemeinsamer Store-Helfer für den Generationszähler, kein Kopieren-Helfer, kein Entfernen toten Codes (R-0724;
  Trade-off 3).
- `users` und `apikeys` bleiben: `users` bekommt beim Anlegen dieselbe Form wie die Liste (`UserResponse`,
  `apps/server/app/modules/users/router.py:39`, `:45`), `apikeys` projiziert schon.
- `toggle` im Hooks-Store bleibt: seine Antwort ist schon `HookResponse` (`router.py:302`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | web | `apps/web/src/lib/stores/hooks.ts`, `apps/web/src/lib/stores/hooks.test.ts` |
| T2 | web | `apps/web/src/lib/stores/frp.ts`, `apps/web/src/lib/stores/frp.test.ts`, `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` |

Kein Pfad aus `scripts/dev/review-risk.txt`.

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Schema, OpenAPI unverändert. Web-Typen bleiben: `hooks.create` gibt weiter
`HookCreateResult` zurück, `hooks.update` `HookDetail`, `frpConfig.save` `FrpConfig` (mit `null` in den zwei Feldern,
die der Typ schon als `string | null` führt, `types.ts:151`, `:156`). Kein Vertrags-Drift zu Desktop oder Agent (sie
nutzen diese Stores nicht).

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

1. **Allowlist statt Denylist (T1).** Eine Liste der `Hook`-Felder, wie `apikeys.ts:29` — **Empfehlung**: ein neues
   Feld der Create- oder Detail-Antwort landet nicht still in der Liste. Damit umgekehrt ein neues Listenfeld nicht
   fehlt, ist die Liste typgeprüft: ein Feld von `Hook`, das in ihr fehlt, macht `npm run check` rot. Alternative
   Denylist (`token`, `script` streichen): kürzer, lässt ein künftiges Feld der Create-Antwort durch.
2. **FRP: im Store auf `null` setzen statt neu laden (T2).** Wie `GET` es liefert, lokal und ohne zweiten Request
   — **Empfehlung**. Alternative `refresh()` nach `save`: ein Request mehr und ein zweiter Pfad, auf dem eine
   langsame Antwort eine neuere überschreiben kann. Alternative Server maskiert auch beim Anlegen: ändert die
   API-Antwort gegen `config_router.py:186-188`, nicht nötig für die Web-Oberfläche.
3. **R-0724 nicht in diesem Paket.** Sein Generationszähler-Helfer ändert `users.ts`, `hooks.ts` und `apikeys.ts`,
   dieselben Stores, die R-0653 (web-fixes) für das Leeren beim Abmelden ändert — ein gemeinsamer Helfer sollte das
   Leeren mittragen und kommt besser danach. Sein toter Code liegt in `apps/web/src/lib/stores/auth.ts:63` und
   `apps/web/src/lib/api/client.ts:36` (Dateien von web-fixes und auth-sessions), dazu `apps/web/src/lib/router.ts:20`,
   `:39` mit Test-Löschungen in `apps/web/src/lib/router.test.ts`. Das Paket wüchse von zwei auf fünf bis sechs Tasks
   und über zehn Dateien. Empfehlung: R-0724 nach web-fixes und auth-sessions als eigenes Paket.

## Risiken & Rollback

- Nach `create` fehlt dem Listeneintrag `script`: die Liste liest es nicht (`Hooks.svelte:147-212`), Bearbeiten holt
  den Hook frisch (`hookApi.get`, `Hooks.svelte:52-60`) — wie nach einem Neuladen heute schon.
- Nach `save` sieht `FrpConfigModal` als `editing` (`apps/web/src/pages/Frp.svelte:261`) `null` in beiden Feldern —
  wie nach einem Neuladen heute schon.
- Die Web-E2E mockt `/api/hooks` und `/api/frp/server-config` (`apps/web/tests/e2e/mocks.ts:117`, `:244`, `:374`);
  keine Spec liest `token`, `script`, `authToken` oder `dashboardPassword` aus der Liste.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T2: ein Satz im Abschnitt „Stores“ von `docs/developer/webui.html:64` und `docs/en/developer/webui.html:64`: die
Daten-Stores halten nur, was die Listen- bzw. Leseantwort trägt; ein einmalig angezeigter Wert aus einer
Create-Antwort (API-Key, Webhook-Token) geht nur an den Aufrufer, Zugangsdaten der FRP-Server-Konfiguration hält der
Store nicht. CHANGELOG (Changed). T1: keine eigene (den Satz und den Eintrag schreibt T2 für beide Stores).

## Offene Fragen

Keine, die eine Task anhält. R-0724 (Trade-off 3) entscheidet die Session.
