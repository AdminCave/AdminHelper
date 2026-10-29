<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Sitzungen: Refresh-Rotation, Tabs, Benutzerbindung, Refresh-Token im Browser, Abmeldung nach Inaktivität

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/auth-sessions.md`. Roadmap R-0649 (T6); R-0451 bekommt keine Task (Nicht-Ziele); T1–T5 und T7–T10 gehören
zum Paket (Kevin 2026-10-22).

## Problem / Motivation

1. **Refresh-Rotation, wenn zwei Aufrufe denselben Token bringen (T1).** `POST /api/auth/refresh`
   (`apps/server/app/modules/users/auth_router.py:180-235`) prüft zuerst, ob der Token schon gesperrt ist
   (`:197`, `is_token_blacklisted`), und sperrt ihn nach der Benutzerprüfung (`:230`, `blacklist_token`).
   `blacklist_token` meldet, ob dieser Aufruf den Eintrag geschrieben hat: `True` neu, `False` schon vorhanden (ein
   paralleler Aufruf mit demselben `jti`, abgefangener `IntegrityError`, `apps/server/app/core/auth.py:136-144`)
   oder Token ohne `jti`/`exp` (`:130-133`). Gewünscht ist: das neue Paar bekommt genau der Aufruf, der den alten
   Token sperrt; jeder andere zählt als Wiederverwendung wie ein späterer Replay (`:194-216`: Warn-Log,
   `tokens_valid_after` des Benutzers setzen, 401). Entscheidung Kevin 2026-10-22: **keine Kulanz** für einen gerade
   rotierten Refresh-Token; der Parallelfall wird als Wiederverwendung erkannt, die Clients bündeln ihre Refreshes
   (Web tab-übergreifend, T6; Desktop schon, siehe 6).

2. **Mehrere Tabs des Web-Panels (R-0649, T6).** `tryRefresh` (`apps/web/src/lib/api/client.ts:62-86`) bündelt
   gleichzeitige Refreshes über `refreshInFlight` (`:17`), einer Variable des Moduls, also nur innerhalb eines Tabs.
   Alle Tabs einer Origin teilen das Refresh-Cookie. Laden zwei Tabs gleichzeitig (Wiederherstellung des Browsers)
   oder erneuern sie zur selben Zeit, schicken beide denselben Token; der zweite ist eine Wiederverwendung und beendet
   alle Sitzungen des Benutzers, auch die des Desktops (die Sperre über `tokens_valid_after` gilt je Benutzer).

3. **Neu angelegte Benutzer (T2).** JWTs nennen den Benutzer über `sub` = Benutzername
   (`apps/server/app/core/auth.py:88`, `:97`); `tokens_valid_after` (`apps/server/app/modules/users/models.py:36-38`)
   ist bei einem neuen Benutzer `NULL`, die Prüfung in `_get_user_from_token` greift nur bei einem gesetzten Wert
   (`auth.py:103-118`). Gewünscht ist: ein neuer Benutzer nimmt nur Tokens an, die ab seinem Anlegen ausgestellt
   wurden. Benutzer entstehen auf vier Wegen: API (`apps/server/app/modules/users/router.py:56-60`), Bootstrap
   (`auth_router.py:324-328`), `ADMIN_PASSWORD` beim Start (`apps/server/app/main.py:97-101`), CLI
   (`apps/server/app/cli.py:53`).

4. **Refresh-Token im Browser nur als Cookie (T3, T7).** Login, Refresh und Bootstrap setzen den Refresh-Token als
   `HttpOnly`-Cookie (`auth_router.py:92-104`) und geben ihn zusätzlich im JSON-Body zurück (`:177`, `:235`,
   `:359`). Das Web-Panel liest ihn nie aus dem Body (`apps/web/src/lib/api/auth.ts:9-12`,
   `apps/web/src/lib/api/client.ts:75-76`); seine Typen deklarieren ihn trotzdem (`apps/web/src/lib/api/types.ts:5-15`).
   Desktop (`apps/desktop/src-tauri/src/auth.rs:19-28`, `:148-176`) und Skripte (`scripts/tests/lib_e2e_stack.sh:297`,
   `scripts/tests/sse_push_e2e.sh:93`) brauchen den Body. Gewünscht ist (Doku `docs/developer/webui.html:68`): der
   Browser hält den Refresh-Token nur im Cookie.

5. **Abmeldung nach Inaktivität im Web-Panel (T4, T5, T8–T10).** Ein offener, sichtbarer Tab hält die Sitzung über
   das Polling (z. B. `/frp`) und den Refresh nach einem 401 (`client.ts:95-104`) beliebig lange; verborgene Tabs
   pausieren das Polling bereits (R-0411). Entscheidung Kevin: Idle-Timeout für die ganze Web-App (2026-10-18),
   **30 Minuten, per Env einstellbar, den Wert liefert der Server** (2026-10-22). Heute gibt es keinen solchen Wert
   und kein Endpunkt liefert Einstellungen ans Web.

6. **Desktop (R-0451): schon erledigt, keine Task.** Siehe Nicht-Ziele.

## Ziel & Nicht-Ziele

Ziel:
- Refresh: das neue Paar bekommt nur der Aufruf, dessen `blacklist_token` `True` liefert; sonst dieselbe Antwort wie
  bei einer Wiederverwendung (401, `tokens_valid_after` gesetzt, Warn-Log). Das Paar entsteht vor dem Sperren, damit
  ein gleichzeitiger zweiter Aufruf, der danach das Wasserzeichen setzt, es sicher mit erfasst.
- Web: Refreshes aller Tabs einer Origin laufen nacheinander (Web Locks API); ohne Web Locks wie heute im Tab.
- Ein neuer Benutzer hat ab dem Anlegen `tokens_valid_after` = Anlegezeit, auf die ganze Sekunde abgeschnitten.
- Browser-Anfragen (Header `Sec-Fetch-Site` vorhanden) bekommen in `refresh_token` den leeren String; das Cookie wie
  heute. Anfragen ohne diesen Header (Desktop, CLI, Skripte, Node-`fetch`) bekommen den Token wie heute.
  Die Web-Typen streichen das Feld.
- Server: `WEB_IDLE_TIMEOUT_MINUTES` (Default 30, `0` = aus), ausgeliefert als `idle_timeout_minutes` in
  `GET /api/auth/me`. Web: Abmeldung, wenn in keinem Tab der Origin so lange bedient wurde (Zeiger, Tastatur, Rad,
  Touch), mit einem Hinweis, der stehen bleibt, bis man ihn schließt.

Nicht-Ziele (YAGNI):
- **R-0451 (Desktop: zwei Refreshes bei gleichzeitigen 401):** am Code überholt. Seit `ce13261c` (2026-10-19) läuft
  jede authentifizierte Desktop-Anfrage über `session::authed_send`
  (`apps/desktop/src-tauri/src/session.rs:243-272`): ein 401 erneuert unter dem `tokio::sync::Mutex` der Sitzung nur,
  wenn die Generation noch die der Anfrage ist (`:292-301`); wer danach kommt, findet die neue Generation und
  wiederholt nur (`:336-339`). Der Test `two_concurrent_401s_renew_once_and_both_retry_with_the_new_token`
  (`session.rs:482-550`) pinnt genau einen Refresh. Aufrufer: `auth.rs:182-191` (`authenticated_get`, darüber
  `sync.rs:78` und `frpc.rs:257`), `proxy.rs:45`, `notifications.rs:170`, `enrollment.rs:533`. Jeder Workspace ist ein
  eigener Prozess mit eigener Anmeldung (eigene Token-Familie). Kein Code für diese Zeile.
- Keine Kulanzzeit für gerade rotierte Refresh-Tokens am Server (Kevin 2026-10-22).
- Kein serverseitiges Idle-Timeout (der Server kann Polling nicht von Bedienung unterscheiden), keine Vorwarnung vor
  der Abmeldung, keine Einstellung je Benutzer.
- Kein neues Feld und keine Änderung am Schema von `TokenResponse` (`apps/server/app/modules/users/schemas.py:26-29`);
  kein `uid`-Claim im JWT (Trade-off 3).
- Keine Datenmigration bestehender Benutzer (`tokens_valid_after` bleibt, wie es ist).
- Kein Umbau der Wege, auf denen Benutzer entstehen (R-0690), kein Eingriff in `update_user`.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/modules/users/auth_router.py`, `apps/server/tests/test_auth_token_lifecycle.py`, `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |
| T2 | server | `apps/server/app/modules/users/models.py`, `apps/server/app/core/auth.py`, `apps/server/tests/test_user_token_watermark.py` (neu), `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |
| T3 | server | `apps/server/app/modules/users/auth_router.py`, `apps/server/tests/test_auth.py`, `apps/server/tests/test_bootstrap.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |
| T4 | server | `apps/server/app/core/config.py`, `docker-compose.yml`, `.env.example`, `apps/server/tests/test_web_idle_timeout.py` (neu), `docs/admin/installation.html`, `docs/en/admin/installation.html` |
| T5 | server | `apps/server/app/modules/users/schemas.py`, `apps/server/app/modules/users/auth_router.py`, `apps/server/tests/test_web_idle_timeout.py`, `apps/server/tests/openapi.snapshot.json`, `apps/web/tests/e2e/mocks.ts`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html` |
| T6 | web | `apps/web/src/lib/api/client.ts`, `apps/web/src/lib/api/client.crosstab.test.ts` (neu), `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` |
| T7 | web | `apps/web/src/lib/api/types.ts`, `apps/web/src/lib/api/tokens.test.ts` (neu) |
| T8 | web | `apps/web/src/lib/idle.ts` (neu), `apps/web/src/lib/idle.test.ts` (neu), `docs/developer/webui.html`, `docs/en/developer/webui.html` |
| T9 | web | `apps/web/src/App.svelte`, `apps/web/src/lib/api/types.ts`, `apps/web/src/lib/i18n/dictionaries.ts`, `apps/web/src/App.idle.test.ts` (neu), `docs/admin/benutzer.html`, `docs/en/admin/users.html`, `CHANGELOG.md` |
| T10 | web | `apps/web/src/lib/idle.ts`, `apps/web/src/lib/idle.test.ts`, `apps/web/src/App.svelte`, `docs/admin/benutzer.html`, `docs/en/admin/users.html`, `CHANGELOG.md` |

Risikopfade (`scripts/dev/review-risk.txt`): `apps/server/app/modules/users/*` (T1, T2, T3, T5),
`apps/server/app/core/auth.py` (T2), `docker-compose*.yml` (T4): diese Tasks bekommen zusätzlich `security`.

Parallel geplante Vorhaben (Überschneidungen, Stand der Planung):
- web-fixes (R-0648, R-0653, R-0654 u. a.): `apps/web/src/lib/api/client.ts` — T6 ändert nur `tryRefresh`
  (`:62-86`), web-fixes laut Zeilen `:12-14` (localStorage beim Import), `:20-34` (Timeout), `:44-48` und
  `lib/api/auth.ts`/`lib/stores/auth.ts` (Logout). T6 und T9 rufen `auth.logout()` nur auf. `dictionaries.ts` (T9,
  neue Schlüssel) kann web-fixes ebenfalls berühren. `apps/web/src/lib/api/auth.test.ts` legt T7 bewusst nicht an
  (eigener Name `tokens.test.ts`).
- audit-coverage (`users/router.py` `update_user`): T2 ändert `users/router.py` nicht (Default am Modell).
- server-hardening: `apps/server/app/core/config.py` (T4 fügt bei `:41-42` hinzu).
- desktop-blocking: keine Überschneidung (kein Desktop-Code).
- Compose-Vorhaben: `docker-compose.yml` (T4: eine Zeile im `environment` des Dienstes `server`).

## Datenmodell / API / Migrationen

- **Keine Alembic-Migration.** T2 setzt einen Python-seitigen Default (`Column(..., default=...)`), kein
  `server_default`: keine DDL, `tests/test_migrations_smoke.py` vergleicht nur `server_default`
  (`compare_server_default=True`, `apps/server/alembic/env.py:64-65`). Bestehende Zeilen bleiben.
- **`TokenResponse` unverändert** (T3): `refresh_token` bleibt ein Pflichtfeld vom Typ `string`; für Browser-Anfragen
  ist der Wert `""`. Kein Snapshot-Diff. Probe (oasdiff 1.32.0, `apps/server/tests/openapi.snapshot.json` von
  `b1432223` gegen eine Kopie): `refresh_token` nicht mehr Pflicht → 3 Fehler `response-property-became-optional`
  (login, refresh, bootstrap); `refresh_token` als `string | null` → 3 Fehler
  `response-property-list-of-types-widened`. Beides wäre ein Bruch des Vertrags; deshalb der leere String.
- **`UserMe` + `idle_timeout_minutes: int`** (T5, Pflichtfeld): additiv. Probe (oasdiff 1.32.0, dieselbe Kopie mit dem
  Feld als Pflicht in der Antwort): „No breaking changes to report“. Desktop liest `/api/auth/me` mit `serde` ohne
  `deny_unknown_fields` (`apps/desktop/src-tauri/src/auth.rs:30-35`), unbekannte Felder werden ignoriert.
  `apps/web/src/lib/api/mocks.contract.test.ts` verlangt jedes Pflichtfeld im Mock: T5 ergänzt
  `apps/web/tests/e2e/mocks.ts` (`userMe()`, `:40-47`) im selben Commit.
- **Neue Env-Variable** `WEB_IDLE_TIMEOUT_MINUTES` am Dienst `server` (Compose `:53-116`), dokumentiert in
  `.env.example` und `docs/admin/installation.html` (DE+EN); `apps/server/tests/test_env_parity.py` hält Compose,
  `.env.example` und `config.py` gleich.
- **Token-Inhalt unverändert** (keine neuen Claims).
- Vertrags-Drift Server ↔ Web ↔ Desktop ↔ Agent: Desktop sendet keinen `Sec-Fetch-Site` (reqwest), bekommt den Token
  wie heute; der Agent nutzt keine JWTs (API-Key/mTLS).

## Externe Integrationen

- **Fetch Metadata, `Sec-Fetch-Site`** (MDN, developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site,
  gelesen 2026-10-22): „Forbidden request header: Yes (`Sec-` prefix)“; Werte `cross-site`, `same-origin`,
  `same-site`, `none`; „The header is only included in requests to potentially trustworthy URLs.“; Baseline „available
  across browsers since March 2023“.
- **Node-`fetch`** (Probe 2026-10-22, Node v22.23.1, POST an einen lokalen Python-Server, der die Header ausgibt):
  gesendet werden u. a. `sec-fetch-mode`, aber **nicht** `sec-fetch-site`. Deshalb entscheidet `Sec-Fetch-Site`,
  nicht `Sec-Fetch-Mode`.
- **Web Locks API** (MDN, developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API, gelesen 2026-10-22): „Locks are
  scoped to origins“; „requests for the same lock from this execution context, or from other tabs/workers, will be
  queued“; „available only in secure contexts (HTTPS)“; „The lock is automatically released when the callback
  returns“ (bei einer async-Funktion, wenn sie ganz fertig ist); Baseline seit März 2022. Spezifikation
  (w3c.github.io/web-locks, §2.6): „Whenever the unloading document cleanup steps run with a document, terminate
  remaining locks and requests with its agent.“
- Gateway (nginx) reicht Request-Header durch; `proxy_set_header` setzt nur Identitäts- und Forward-Header
  (`apps/gateway/identity-headers.conf:6-10`).
- PyJWT: `iat` aus `datetime.now(timezone.utc)` wird als ganze Sekunden kodiert (so schon vorausgesetzt in
  `apps/server/app/core/auth.py:107-115` und `apps/server/tests/test_cli.py:117-120`).

## Trade-offs & Alternativen

1. **Erkennung des Browsers (T3).** (a) `Sec-Fetch-Site` vorhanden — **Empfehlung**: setzt nur der Browser, Skripte
  der Seite können ihn weder setzen noch entfernen; Desktop, CLI, Skripte und Node-`fetch` senden ihn nicht.
  (b) Ein eigener Header oder ein Login-Feld, mit dem das Web sich meldet: der Browser müsste sich selbst ausweisen;
  jede Anfrage ohne Kennung bekäme den Token. (c) Umgekehrt nur Clients mit Kennung bekommen den Body-Token: bricht
  Skripte und fremde Clients (Vertrag). (d) `Sec-Fetch-Mode`: Node-`fetch` sendet ihn (Probe), Skripte mit Node
  bekämen den Token nicht mehr.
2. **Form der Antwort für Browser (T3).** (a) `refresh_token: ""` — **Empfehlung**, Schema unverändert. (b) Feld
  weglassen bzw. `null`: sauberer Typ, aber oasdiff ERR (Probe oben) → Vertragsänderung. Das Web liest das Feld nicht.
3. **Bindung neuer Benutzer (T2).** (a) `tokens_valid_after` beim Anlegen, ganze Sekunde, als Default am Modell —
  **Empfehlung**: eine Stelle für alle vier Wege, keine Migration, keine neuen Claims, gleiche Uhr wie `iat`
  (Anwendung). (b) `uid`-Claim gegen `user.id`: Tokens ohne `uid` (vor dem Update ausgestellt) bräuchten eine
  Regel (annehmen oder alle Sitzungen beim Update beenden). (c) `iat` gegen `users.created_at`: `created_at` kommt
  von der Uhr der Datenbank (`apps/server/app/core/time.py:33-44`), Abweichung zur Anwendung ließe frische Logins
  scheitern. Abschneiden auf die Sekunde: sonst fielen die Tokens aus der Bootstrap-Antwort und ein Login in der
  Sekunde des Anlegens durch (`iat` ganzzahlig, `iat < watermark`).
4. **Reihenfolge in der Rotation (T1).** Paar vor `blacklist_token` erzeugen: `iat` ≤ Zeitpunkt der Erzeugung < Commit
  des Sperreintrags < Wasserzeichen eines zweiten Aufrufs, der erst nach diesem Commit scheitert. Umgekehrt könnte
  ein verzögerter erster Aufruf sein Paar in einer späteren Sekunde erzeugen und das Wasserzeichen überleben.
5. **Wo der Server den Idle-Wert liefert (T5).** (a) Feld in `GET /api/auth/me` — **Empfehlung**: das Web ruft es nach
  jedem Login und jeder Wiederherstellung ohnehin; additiv. (b) Eigener Endpunkt: mehr Fläche (Auth-Gate-Tests,
  Schema, Gateway). (c) Feld in der Token-Antwort: berührt `client.ts`/`auth.ts` (web-fixes).
6. **Was als Bedienung zählt (T8).** `pointerdown`, `pointermove`, `keydown`, `wheel`, `touchstart` in einem beliebigen
  Tab der Origin; der Zeitstempel liegt in `localStorage` und wird höchstens alle 5 s geschrieben. Ohne gemeinsame
  Uhr würde ein unbedienter zweiter Tab abmelden und damit (Logout sperrt das gemeinsame Cookie) auch den bedienten.
7. **Ungültiger Env-Wert (T4).** Warnung und 30 statt Abbruch beim Start: eine Tippfehler-Variable soll das Panel
  nicht lahmlegen; `0` schaltet ab (z. B. für eine Statusanzeige).
8. **Hinweis nach der Abmeldung (T9).** Ein Toast mit `durationMs = 0` (bleibt bis zum Schließen,
  `apps/web/src/lib/stores/notifications.ts:22-30`): der Nutzer ist bei der Abmeldung nicht da; ein Toast mit 3 s
  wäre weg. Keine Änderung an `Login.svelte`.

## Risiken & Rollback

- T1 macht jeden echten Parallel-Refresh zur Wiederverwendung: Clients ohne Bündelung (Web vor T6, Desktop-Versionen
  vor `ce13261c`) melden sich in diesem Fall überall ab, wo vorher beide Aufrufe ein Paar bekamen. Gewollt (Kevin
  2026-10-22); T6 kommt im selben PR.
- Ein Neuladen genau während eines laufenden Refreshs kann weiter alle Sitzungen beenden: die Web Lock endet mit dem
  Dokument, die Antwort mit dem neuen Cookie kann verloren gehen. Ohne Kulanzzeit am Server nicht vermeidbar.
- Browser ohne Fetch Metadata oder Seiten außerhalb eines sicheren Kontexts bekommen den Body-Token wie heute, und
  ohne Web Locks bündelt der Client nur im Tab (beides: HTTPS bzw. `localhost` nötig).
- T2: Tokens, die in der Sekunde des Anlegens für denselben Namen ausgestellt wurden, gelten weiter (Abschneiden).
- T8/T9: `localStorage` gesperrt → jeder Tab zählt für sich; ein unbedienter Tab meldet dann alle ab. Hintergrund-Tabs
  drosseln Timer (Prüfung höchstens etwa einmal je Minute) — die Abmeldung kommt dort bis zu einer Minute später.
- T5 ändert den Snapshot (`apps/server/tests/openapi.snapshot.json`), nur additiv.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt. Nach einem Revert von T2 behalten
  Benutzer, die dazwischen angelegt wurden, ihren Wert (wirkt wie ein Passwortwechsel zum Anlegezeitpunkt).

## Doku-Impact

T1: `docs/developer/server.html:83` (DE+EN, Rotation) + CHANGELOG (Changed). T2: `server.html:85` (DE+EN) + CHANGELOG
(Changed). T3: `docs/developer/api-reference.html:39`, `:61`, `:65`, `:77` und `server.html:79` (DE+EN) + CHANGELOG
(Changed). T4: Tabelle `docs/admin/installation.html:132-153` (EN `docs/en/admin/installation.html:45-66`). T5:
`api-reference.html:72-74` (DE+EN). T6: `docs/developer/webui.html:68` (DE+EN) + CHANGELOG (Fixed). T8:
`webui.html:68` (DE+EN). T9: `docs/admin/benutzer.html:62-67`, `docs/en/admin/users.html:55-61` + CHANGELOG (Added).
T10: dieselben Seiten + CHANGELOG. T7: keine (intern).

## Offene Fragen

1. **T10 — gilt die Inaktivität auch über Neuladen und Wiederöffnen?** Nach T9 meldet ein offener Tab nach 30 min ohne
   Bedienung ab; wer den Tab schließt und später wieder öffnet, ist über das 7-Tage-Cookie sofort wieder angemeldet.
   Variante: eine beim Laden wiederhergestellte Sitzung endet sofort, wenn die letzte Bedienung in diesem Browser
   (Zeitstempel aus T8) länger als das Limit her ist. **Empfehlung: ja** — sonst ist „Tab schließen“ ein Weg, die
   Abmeldung zu umgehen, und „30 min ohne Bedienung“ hieße je nach offenem Tab Verschiedenes. Trade-off: „7 Tage
   angemeldet bleiben“ entfällt für Browser, die den Zeitstempel kennen. Sichtbares Verhalten → Kevin; T10 steht auf
   `[?]`, T1–T9 hängen nicht daran.
2. **Im Rahmen entschieden (Einspruch möglich, kein `[?]`):** leerer String statt fehlendem Feld (Trade-off 2);
   `0` = aus und Rückfall auf 30 bei ungültigem Wert (Trade-off 7); bleibender Toast, keine Vorwarnung (Trade-off 8);
   was als Bedienung zählt (Trade-off 6); Name `WEB_IDLE_TIMEOUT_MINUTES`.
