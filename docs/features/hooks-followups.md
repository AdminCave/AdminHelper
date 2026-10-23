<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Hooks: gescheiterte Läufe im Log, Fehlertexte der HTTP-Helfer, Env-Pins, Web-Typ des Laufs

Stand des Codes: `origin/main@6f05b316`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/hooks-followups.md`. Roadmap R-0558 (T2, T5), R-0587 (T3), R-0562 (T4); T1 gehört zum Paket (Kevin
2026-10-21).

## Problem / Motivation

1. **Gescheiterte Event- und Schedule-Hooks stehen nicht im Log (R-0558).** `run_hook_script`
   (`apps/server/app/modules/hooks/script_runner.py:85-262`) wirft bei einem gescheiterten Lauf nicht, sondern gibt
   ein Dict mit `success: false` und `error` zurück: Server ausgelastet (`:127-133`), Timeout (`:193-203`), Ausgabe zu
   groß (`:229-241`), Worker mit Exit-Code ungleich 0 (`:243-250`), ungültige Worker-Ausgabe (`:252-260`), Exception
   im Script (`apps/server/app/modules/hooks/script_worker.py:185-193`). Die Event-Dispatch
   (`apps/server/app/core/events.py:42-48`) und der Scheduler (`apps/server/app/modules/hooks/scheduler.py:129-136`)
   verwerfen diesen Rückgabewert; ihr `logger.exception` greift nur, wenn `run_hook_script` selbst wirft. Beleg
   (Probe an `origin/main@6f05b316`, dreimal identisch): `_run_event` und `_execute_scheduled_hook` mit einem
   Stand-in, der `{"success": False, "error": "Timeout nach 30s", …}` zurückgibt, erzeugen keinen Log-Eintrag ab
   WARNING; Gegenprobe: ein Stand-in, der wirft, erzeugt je einen ERROR.
   Die Doku verspricht das Log: `docs/developer/hooks.html:99` — „Schlägt ein Hook fehl (<code>exit_code != 0</code>
   oder Timeout), wird der Fehler protokolliert: Event- und Schedule-Hooks per <code>logger.exception</code> im
   Server-Log“; `docs/admin/betrieb.html:122` — „<code>app.modules.hooks.scheduler</code> – Hook-Ausführungen inkl.
   Subprozess-Exitcodes, im Log des <code>scheduler</code>-Dienstes“ (EN `docs/en/developer/hooks.html:99`,
   `docs/en/admin/operations.html:81`). Entscheidung Kevin 2026-10-21: der Code loggt (WARNING mit dem Namen des
   Hooks und `error`), die Doku bleibt.

2. **Fehlertexte der HTTP-Helfer (T1).** Lehnt der SSRF-Schutz ein Ziel ab, werfen `_safe_http_get` und
   `_safe_http_post` einen `ValueError`, dessen Text mit der ganzen URL endet (`script_worker.py:62-68`, `:85-91`).
   Fängt das Script ihn nicht, steht der Text in `error` und in der Zeile `Fehler: …` in `logs`
   (`script_worker.py:185-193`), damit in der Antwort von `POST /api/hooks/trigger` und `POST /api/hooks/{id}/run`
   (`apps/server/app/modules/hooks/router.py:206-225`, `:358-363`) und nach (1) im Server-Log. Für Log-Zeilen
   über ausgehende Ziele gilt im Projekt schon, vom Ziel nur den Host zu nennen: `_log_host` im Alert-Webhook des
   Monitorings (`apps/monitoring/app/alerter.py:542-549`) — „Many webhook services carry the credential in the path
   or the query, so nothing else of the URL is logged.“ Das mitgelieferte Beispiel
   `docs/examples/event_hook_notify.py:19` ist eine solche URL.

3. **Env des Hook-Workers nur teilweise gepinnt (R-0587).** `apps/server/tests/test_hook_isolation.py:116-132` prüft,
   dass `HOME` und `LANG` gesetzt sind und `HTTPS_PROXY` durchgereicht wird. Nicht gepinnt sind die Rückfallwerte
   `HOME=/tmp` und `LANG=C.UTF-8` (`script_runner.py:110-111`), die kleingeschriebenen Proxy-Variablen
   (`:116-125`) und dass eine Proxy-Variable, die der Server nicht hat, auch im Worker fehlt (`:124-125`). Die Doku
   beschreibt alle drei (`docs/developer/hooks.html:85`, EN `:85`). Messung (Probe an `origin/main@6f05b316`):
   von vier Mutationen an `script_runner.py:108-125` (unten, T3) fängt der Test keine.

4. **Web-Typ des manuellen Laufs (R-0562).** `HookRunResult` (`apps/web/src/lib/api/types.ts:132-139`) deklariert
   `output`, `exit_code` und `duration_ms`, die `POST /api/hooks/{id}/run` nie schickt, `success` als optional und
   `result`/`logs` gar nicht (nur über die Index-Signatur `[key: string]: unknown`). Die Antwort hat immer
   `success`, `result` und `logs`, bei einem Fehler dazu `error` (`router.py:358-363`; `script_runner.py:127-262`;
   `script_worker.py:184-193`). Der Dialog zeigt das Ergebnis als JSON
   (`apps/web/src/modals/HookRunResultModal.svelte:24-27`), die Doku nennt genau diese Felder
   (`docs/developer/hooks.html:112`).

## Ziel & Nicht-Ziele

Ziel:
- Ein gescheiterter Event- oder Schedule-Hook (`success` nicht `true`) schreibt eine Log-Zeile auf WARNING mit dem
  Namen des Hooks, bei Event-Hooks dem Event, und dem `error`-Text (auf eine Zeile, gekürzt). Ein erfolgreicher Lauf
  schreibt nichts Neues. Das bestehende `logger.exception` für einen Runner, der wirft, bleibt.
- Die Ablehnungstexte von `http_get`/`http_post` nennen vom Ziel nur den Hostnamen (wie `_log_host`); fehlt ein
  lesbarer Host, `?`. Typ (`ValueError`) und die Anfänge der Texte bleiben.
- Die Rückfallwerte und die Proxy-Weitergabe des Worker-Env sind durch Tests gepinnt.
- `HookRunResult` beschreibt die echte Antwort; Typ-Pins machen eine Abweichung in `npm run check` rot.

Nicht-Ziele (YAGNI):
- Kein Log für einen gescheiterten Webhook-Trigger oder einen Lauf über `/run`: der Aufrufer bekommt `success` und
  `error` in der Antwort (offene Frage 2).
- Keine Retry-Logik, kein `hook.failed`-Event, keine Persistenz von Läufen.
- Kein `response_model` für `/run` (würde das OpenAPI-Schema ändern, `tests/openapi.snapshot.json`), keine neue
  Darstellung im Dialog.
- Keine Änderung an anderen Fehlertexten aus httpx (etwa `httpx.InvalidURL`, gepinnt in
  `apps/server/tests/test_hooks_http_ssrf.py:158-167`) und keine Übersetzung der bestehenden Textanfänge.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/modules/hooks/script_worker.py`, `apps/server/tests/test_hooks_http_ssrf.py`, `docs/developer/hooks.html`, `docs/en/developer/hooks.html`, `CHANGELOG.md` |
| T2 | server | `apps/server/app/modules/hooks/script_runner.py`, `apps/server/app/core/events.py`, `apps/server/app/modules/hooks/scheduler.py`, `apps/server/tests/test_hooks.py`, `CHANGELOG.md` |
| T3 | server | `apps/server/tests/test_hook_isolation.py` |
| T4 | web | `apps/web/src/lib/api/types.ts`, `apps/web/src/lib/api/hooks.test.ts` (neu) |
| T5 | scripts | `docs/developer/hooks.html`, `docs/en/developer/hooks.html`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html` |

`script_worker.py` steht auf der Risikoliste (`scripts/dev/review-risk.txt`): T1 bekommt zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld, keine Route. Die Antworten von `/run` und `/trigger` behalten ihre Felder; nur der
Text in `error`/`logs` wird bei einer Ablehnung durch den SSRF-Schutz kürzer (T1). OpenAPI bleibt unverändert (keine
Route und kein Docstring einer Route ändert sich). Web: `HookRunResult` wird enger (T4); die einzigen Nutzer sind
`apps/web/src/lib/api/hooks.ts:40-41`, `apps/web/src/pages/Hooks.svelte:22`, `:30`, `:89-90` und
`HookRunResultModal.svelte:11`, `:16`, die keine der entfallenden Felder lesen. Kein Vertrags-Drift zu Desktop oder
Agent (sie nutzen `/api/hooks` nicht).

## Externe Integrationen

- Python `urllib.parse` (docs.python.org/3/library/urllib.parse.html, gelesen 2026-10-21): `hostname` ist „Host name
  (lower case)“, getrennt von `username`, `password` und `port`; „Unmatched square brackets in the netloc attribute
  will raise a ValueError.“ `Target.host` ist dieser `hostname` (`apps/server/app/core/ssrf.py:139-145`,
  `:159-170`), leer, wenn die URL keinen lesbaren Host hat (`:164`, `:166`).
- Sonst keine externe Schnittstelle (Logging ist Standardbibliothek; httpx bleibt unverändert, Version 0.28.1 im
  Dev-Venv).

## Trade-offs & Alternativen

1. **Wo geloggt wird (T2).** (a) In den zwei Aufrufern mit einem kleinen gemeinsamen Helfer in `script_runner.py`,
   der aus dem Ergebnis den Log-Text macht oder `None` liefert — **Empfehlung**: der Name des Hooks ist nur dort
   bekannt, die Kürzung steht an einer Stelle. (b) In `run_hook_script` selbst: kennt den Hook-Namen nicht (neuer
   Parameter für vier Aufrufer) und loggte auch Webhook und `/run` (Nicht-Ziel). (c) Je Aufrufer ohne Helfer: zwei
   Kopien der Kürzung.
2. **Kürzung des `error`-Texts im Log.** Der Text kann der stderr des Workers bis 8 MiB sein (`script_runner.py:75`,
   `:243-250`). Empfehlung: höchstens 1000 Zeichen, bei längerem Text die letzten 1000 mit vorangestelltem `…` (ein
   Traceback endet mit der Exception), ausgegeben mit `%r`, damit die Log-Zeile eine Zeile bleibt; den Namen des
   Hooks ebenso mit `%r`. Alternative: Anfang statt Ende — schneidet bei einem Traceback die Ursache ab.
3. **Was die Ablehnung vom Ziel nennt (T1).** (a) Nur den Hostnamen, `Target.host`, sonst `?` — **Empfehlung**, wie
   `_log_host`, ein Wert, den der Guard ohnehin hält. (b) Die URL ohne Benutzer und Passwort — Pfad und Query blieben
   (das Beispiel in `docs/examples/event_hook_notify.py:19`). (c) Gar nichts vom Ziel — der Autor des Hooks sähe
   nicht mehr, welches Ziel abgelehnt wurde.
4. **Typ von `result` (T4).** `unknown`: die API-Referenz sagt „ist, was das Skript zurückgibt“
   (`docs/developer/api-reference.html:54`), und der Worker liest `result` nach dem Script aus dem Namensraum
   (`script_worker.py:180-184`), ein Script kann es neu binden. `logs: string[]`: `log()` und `print()` schreiben
   Zeilen als Text (`script_worker.py:130-138`, Doku `hooks.html:78`). Alternative `Record<string, unknown>` für
   `result` wäre enger als die API-Referenz.
5. **Typ-Pins (T4)** über `// @ts-expect-error` in einer Testdatei, die `npm run check` (svelte-check, `tsconfig.json`
   schließt `src/**/*.ts` ein) prüft. Belegt (Probe 2026-10-21, svelte-check 4.6.0, TypeScript 6.0.3): auf HEAD zwei
   Fehler „Unused '@ts-expect-error' directive“, mit dem neuen Typ 0 Fehler; ESLint und Prettier ohne Befund.
   Alternative `expectTypeOf` braucht `vitest --typecheck`, das das Projekt nicht fährt.

## Risiken & Rollback

- T2 schreibt pro gescheitertem Lauf eine Zeile. Ein Schedule-Hook im Minutentakt, der dauernd scheitert, schreibt
  1440 Zeilen am Tag; die Container-Logs sind rotiert (`docker-compose.yml:5`, `x-logging`, 50 MB je Dienst laut
  `docs/admin/betrieb.html:127`). Event-Hooks laufen nur auf Ereignisse aus angemeldeten Aktionen.
- T2 schreibt den `error`-Text, wie ihn das Script oder der Runner liefert, ins Log; Fehler der Datenbankanbindung
  nennen dort schon nur den Typ (`script_worker.py:35-37`, `:186`). T1 läuft vorher, damit die Texte der HTTP-Helfer
  im Log nur den Host nennen.
- Stand-ins in `apps/server/tests/test_hooks.py` (`:97-99`, `:297`) geben `None` zurück; T2 gibt ihnen ein Erfolgs-Dict, damit
  sie nicht über den `except`-Zweig laufen. Keine Assertion ändert sich.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T1: ein Satz in `docs/developer/hooks.html:77` (DE+EN), dass der Text des `ValueError` vom Ziel nur den Hostnamen
nennt; CHANGELOG (Changed). T2: CHANGELOG (Fixed); die Doku bleibt (Kevin). T3, T4: keine (intern). T5 (offen,
Frage 1): drei Präzisierungen in `hooks.html:99`, `betrieb.html:122`, `operations.html:81`.

## Offene Fragen

1. **T5, Doku nach T2 präzisieren?** Nach T2 stimmen drei Einzelheiten nicht: `hooks.html:99` nennt
   `logger.exception` (T2 loggt auf WARNING, `logger.exception` bleibt nur für einen Runner, der wirft);
   `betrieb.html:122` nennt „inkl. Subprozess-Exitcodes“ (geloggt wird der `error`-Text, kein Exit-Code), und Event-Hooks
   loggen unter `app.core.events` im `server`-Dienst, der in der Liste fehlt. Empfehlung: T5 bauen (Präzisierung, das
   Versprechen bleibt). Kevin sagte „die Doku bleibt“; deshalb steht T5 auf `[?]`.
2. **Webhook und `/run` auch loggen?** `hooks.html:99` sagt „der Webhook-Trigger zusätzlich im Response-Body“; das
   lässt sich als „auch im Log“ lesen. Empfehlung: nein — der Aufrufer sieht `success`/`error` in der Antwort, die
   Zeile R-0558 und Kevins Entscheidung nennen Event- und Schedule-Hooks, und ein öffentlich auslösbarer Pfad schriebe
   bis zu 20 Zeilen je IP und Minute (`router.py:47-48`). T5 formuliert den Satz entsprechend. Bei „ja“ eine eigene
   Task an `router.py:206-225`.
