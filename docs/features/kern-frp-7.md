<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Ergebnis des Policy-Abgleichs nach Schlüssel-Erneuerung melden (kern-frp-7)

Roadmap: R-1437 · Ledger: `tasks/kern-frp-7.md`

## Problem / Motivation

`POST /api/servers/{id}/frp-key/rotate` erhöht die Schlüssel-Generation eines Hosts und schreibt danach die
frps-Policy (`sync_policy`, `apps/server/app/modules/frp/policy.py`). Der Abgleich ist best effort: scheitert das
Schreiben, wird nur geloggt, und die Antwort ist trotzdem `200 {"generation": n}`. Bis zum nächsten periodischen
Abgleich (`SYNC_INTERVAL`, etwa 60 s) gilt in frps dann noch die alte Generation. Der Admin, der die Erneuerung
auslöst, erfährt davon nichts.

## Ziel & Nicht-Ziele

Ziel (Kevin 2026-11-14, Variante a):
- `sync_policy` gibt zurück, ob die Policy geschrieben wurde (`bool`); alle übrigen Aufrufer ignorieren den Wert
  weiter.
- Die Rotation antwortet `{"generation": n, "policySynced": true|false}`. Die Erneuerung selbst bleibt gültig
  (kein Fehlerstatus, kein Rollback der Generation); der periodische Abgleich schreibt die Policy nach.
- Desktop: zeigt die Erneuerung bei `policySynced: false` als Warnung an (Policy noch nicht geschrieben, frps
  übernimmt die neue Generation spätestens mit dem nächsten Abgleich), sonst wie heute die Erfolgsmeldung.

Nicht-Ziele:
- Kein Feld in der Antwort der Provisionierung (`/provision/activate`): ihr Verbraucher ist der Agent, keine UI;
  dort bleibt es beim Log.
- Kein synchrones Nachschreiben oder Wiederholen in der Anfrage (Variante c verworfen).
- Web-Frontend: hat keinen Rotations-Knopf.

## Betroffene Komponenten & Dateien

- Server: `app/modules/frp/policy.py` (`sync_policy` → `bool`), `app/modules/servers/router.py` (`rotate_frp_key`),
  `app/modules/servers/schemas.py` (`FrpKeyRotateOut.policySynced`), `tests/test_servers_frp_key_rotate.py`,
  `tests/openapi.snapshot.json`.
- Desktop-UI: `src/lib/api/frp.ts` (Rückgabetyp), `src/components/infra/tabs/TunnelsTab.svelte`,
  `TunnelsTab.test.ts`, `src/lib/i18n/dictionaries.ts` (DE+EN).
- Doku: `docs/developer/api-reference.html` und EN (Antwort der Rotation), `docs/admin/frp-tunnel.html` und EN
  (Hinweis zur Warnung), `changelog.d/kern-frp-7.md`.

## Datenmodell / API / Migrationen

Keine Migration. Additives Antwortfeld `policySynced` (Desktop liest es; ein älterer Desktop ignoriert es).

## Trade-offs & Alternativen

(a) Feld plus Warnung (gewählt): ehrlich, unterbricht nichts. (b) Fehlerstatus: die Generation ist schon erhöht und
committet, ein Fehler wäre irreführend. (c) Loggen und Wiederholen: der Admin erfährt weiter nichts.

## Risiken & Rollback

Gering; additive Änderung. Rollback: Revert des Branches.

## Doku-Impact

API-Referenz DE+EN (Antwortfeld), Admin-Seite FRP-Tunnel DE+EN (ein Satz zur Warnung), CHANGELOG.

## Offene Fragen

Keine (Kevin 2026-11-14: Variante a).
