<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Nachzüge: hingenommene Restrisiken, Drift zwischen Doku und Code, CHANGELOG-Glättung

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand, außer wo ein Branch
genannt ist (`origin/feature/monitoring-io@13f340e4` = PR #265, `origin/feature/desktop-ui-fixes` = PR #262,
lokaler Branch `feature/docs-drift`). Ledger: `tasks/docs-residual-risks.md`.
Roadmap: R-0798 (T1), R-0754 (T2), R-0758 (T3), R-0609 (T4), R-0794 (T5), R-0453 (T5, T6, T7, T15), R-0769 (T7, T8),
R-0770 (T7), R-0791 und R-0602 (T9), R-0732 (T10), R-0792 (T11), R-0601 (T12), R-0595 (T13), R-0782 (T14).

## Problem / Motivation

1. **Monitoring: ein abgelehnter Stapel kostet fremde Zeilen (R-0798).** Mit PR #265 (`monitoring-io`, noch nicht
   gemergt) schreibt ein eigener Thread den Puffer in Stapeln an VictoriaMetrics:
   `_MAX_BATCH_LINES = 10_000` (`origin/feature/monitoring-io:apps/monitoring/app/core/victoria.py:22`),
   `batch = self._pending[:_MAX_BATCH_LINES]` (`:181`). Der Puffer sammelt die Zeilen aller `write`-Aufrufe
   (`write` `:126`, Agent-Reports und Checks vieler Server). `_send` (`:189`) wiederholt Timeout,
   Verbindungsfehler und 5xx; jede andere Antwort, die nicht `is_success` ist (`:203`), also auch 3xx, landet in
   `if resp.status_code < 500:` (`:205`), wird mit „VictoriaMetrics rejected a write of %d lines with HTTP %d, not
   retried“ (`:207`) geloggt und verworfen. httpx folgt Weiterleitungen nicht von selbst (`httpx.Client(timeout=10)`,
   `:118`). Die Entwicklerdoku nach #265 (`origin/feature/monitoring-io:docs/developer/monitoring.html:263`, EN
   `:263`) sagt schon „Eine Antwort 4xx … wiederholt er nicht … der ganze Stapel ist verloren“, aber nicht, dass der
   Stapel Zeilen anderer Checks und Server trägt, dass eine einzige ungültige Zeile bis zu 10 000 Zeilen kostet und
   dass dasselbe für 3xx gilt. Kevin (2026-10-22): Verlust hinnehmen, in einem Satz dokumentieren (DE + EN).
   Belegt am Code (oben) und per Probe gegen das gepinnte Image (Abschnitt Externe Integrationen).

2. **Zugang entziehen beendet den Tunnel-Zugang nicht (R-0453).** Einen Schalter „deaktivieren“ gibt es nicht
   (`apps/server/app/modules/users/models.py`, kein `is_active`); die Wege sind Löschen, Gerät widerrufen,
   Server-Zuordnung oder Admin-Rolle entziehen, Passwort neu setzen. Was dabei mit dem Tunnel passiert:
   - Löschen widerruft die `access`-Identität (`apps/server/app/modules/users/router.py:174`); jedes Gerät des
     Benutzers bekommt danach 403 `ERR_CERT_REVOKED` (`apps/server/app/core/identity.py:125-126`, `:225`), auch auf
     `GET /api/frp/generate/visitor-bundle` (`apps/server/app/modules/frp/router.py:20`, `:26`). Der Desktop wertet
     jeden Status außer 2xx und 404 als Fehler (`apps/desktop/src-tauri/src/frpc.rs:277-287`), und ein Fehler des
     Abgleichs lässt den laufenden frpc stehen (`frpc.rs:1187-1189`; Test `:2045-2049` mit 401 und 403). Ein
     Widerruf einzelner Geräte wirkt genauso.
   - Ein 401, den die Erneuerung nicht heilt, beendet dagegen die Sitzung (`apps/desktop/src-tauri/src/session.rs:323-332`)
     und damit frpc (`apps/desktop/src-tauri/src/main.rs:199-206`, `on_sign_in_change` → `stop_frpc`). Die Hälfte
     „endgültig abgelehnter Refresh“ des optionalen Vorschlags der Zeile ist also schon gebaut; die Zeile („401/403
     laesst frpc stehen“) stimmt nur für 403. Die Entwicklerdoku sagt für 401 dasselbe Falsche
     (`docs/developer/desktop.html:259`, EN `:259`: „401 nach gescheitertem Refresh … lässt den laufenden frpc
     unangetastet“).
   - Unabhängig vom Desktop: Die `visitor.toml` trägt `auth.token` (`apps/server/app/modules/frp/config_generator.py:331`)
     und den `secretKey` jedes sichtbaren STCP-Tunnels (`:354`); sichtbar sind für einen Admin alle aktiven
     STCP-Tunnel der Konfiguration, sonst die seiner Server (`apps/server/app/modules/frp/generate_router.py:40-61`).
     Der Desktop hält sie im Laufzeitverzeichnis, solange frpc läuft (`frpc.rs:646`, `stop_frpc` `:912`); kopiert
     ist sie dauerhaft gültig. frps prüft das Client-Zertifikat nur gegen `trustedCaFile`
     (`config_generator.py:153`, `:156`), eine Sperrprüfung hat frp nicht (Externe Integrationen). Ein gelöschter
     Benutzer erreicht die Tunnel also weiter, bis die `secretKey`s rotiert sind, und frps, bis sein Zertifikat
     abläuft oder `auth.token` rotiert ist. Dasselbe gilt für Tunnel von Servern, die man ihm entzieht.
   - Die Admin-Doku sagt dazu nichts (`docs/admin/benutzer.html:104-112`, EN `docs/en/admin/users.html:98-106`;
     `docs/admin/frp-tunnel.html:65-76`, `:102`, EN gleich).

3. **Doku-Drift, gefunden in anderen Vorhaben (von Kevin am 2026-10-22 angenommen):**
   - R-0754: `docs/admin/monitoring.html:230` (EN `:230`) — „Pro Metrik werden vier Labels geschrieben: `server`,
     `check`, `type`, plus … `mountpoint` oder `device`“. Geschrieben werden `check_id`, `check_type`, `name` und
     bei Server-Checks `server_id` (`apps/monitoring/app/core/victoria.py:155-157`), für die Agent-Metriken
     `server_id` (`apps/monitoring/app/routers/agent.py:124`) plus `mount` (`:139`), `sensor` (`:147`) und heute
     `device` (`:159`). Nach #265 entfällt `device`: SMART-Werte schreibt nur noch der Check mit seinen Labels
     (`origin/feature/monitoring-io:apps/monitoring/app/routers/agent.py:126-128`). Die Beispielabfrage derselben
     Zeile (`query=up`) trifft keine Reihe: VictoriaMetrics läuft ohne Self-Scrape (`docker-compose.yml:416`, nur
     `-retentionPeriod`); die Reihen heißen `<measurement>_value` (`apps/monitoring/app/routers/checks.py:481`).
   - R-0758: `docs/developer/server.html:164-171` (EN gleich) nennt `api_key.created`/`api_key.deleted`; kein
     `fire_event` feuert sie (`git grep -n 'fire_event' apps/server/app`). Es fehlen `server.startup`
     (`apps/server/app/main.py:382`) und `alert.triggered` (`apps/server/app/modules/notifications/router.py:208-209`).
   - R-0609: `docs/admin/betrieb.html:124` / `docs/en/admin/operations.html:83` nennen für
     `app.modules.hooks.scheduler` nur gescheiterte Schedule-Hooks. Derselbe Logger schreibt die Warnung zu einem
     unlesbaren Intervall (`apps/server/app/modules/hooks/scheduler.py:210-215`), die Erfolgs- und Fehlerzeilen der
     System-Jobs (`:272`, `:274`).
   - R-0794: `docs/admin/frp-tunnel.html:54` (EN `:54`) — „trustedCaFile: beidseitig die `tunnel`-Kette“; frps
     vertraut zusätzlich dem `access`-Intermediate (`apps/ca-issuer/app/main.py:54-56`,
     `apps/ca-issuer/app/storage.py:264`). `docs/adr/0001-unified-pki-and-secure-deployment.md:34` — „Agent pinnt
     die Root“; der Agent vertraut nur seiner Kettendatei `ca.crt` (Intermediate + Root,
     `apps/agent/internal/enroll/enroll.go:39`, `apps/agent/internal/httpclient/httpclient.go:77-92`,
     Aufruf `apps/agent/internal/enroll/client.go:47`).
   - R-0769: `docs/developer/desktop.html:240` (EN `:240`) und `apps/desktop/src-tauri/src/error.rs:11-12` — die
     Pin-Verifier liefern „eigene `ERR_*`-Meldungen“; die Meldung für einen unbrauchbaren Schlüsselbund trägt
     bewusst keinen Code (`apps/desktop/src-tauri/src/tofu.rs:277-284`). Der Test-Helfer
     `get_allowing_self_signed` (`apps/desktop/src-tauri/src/session.rs:1218-1219`, „trusts the server's certificate
     on first use“) vertraut einem vorab gesetzten Pin (`serve_self_signed` → `seed_cached_pin`, `session.rs:1187`).
   - R-0770: `docs/en/admin/troubleshooting.html:73` zitiert `AdminHelper TOFU: … changed`; der echte Text ist
     deutsch: `ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für … hat sich seit dem ersten
     Verbinden geändert …` (`tofu.rs:271-274`). Die DE-Seite (`docs/admin/troubleshooting.html:73`) zitiert richtig.
   - R-0791: `DEVELOPMENT.md:760-762` und `:1434-1435` starten den Server in `apps/server` mit `DATA_DIR=../data`;
     `.secret_key`, `.bootstrap_token` und die FRP-Verzeichnisse landen in `apps/data/`
     (`apps/server/app/core/config.py:12`, `:22`, `:65`). `.gitignore:115` ignoriert nur `/data/`:
     `git check-ignore -v apps/data/.secret_key` → nichts, Exit 1. `feature/docs-drift` übernimmt denselben Befehl in
     `docs/developer/index.html:92` und EN `:65`.
   - R-0602: `DEVELOPMENT.md:894-907` („Monitoring (lokal ohne Docker)“) verschweigt, dass der Dev-Fallback
     `adminhelper:adminhelper@localhost:5432/adminhelper_monitor` (`apps/monitoring/app/core/config.py:57-66`) an
     einer Rolle mit eigenem Passwort scheitert (`DEVELOPMENT.md:205-216`). Für den Server steht der Hinweis schon
     (`DEVELOPMENT.md:771`).
   - R-0732: `docker-compose.yml:85-87` — „Only the monitoring entrypoint runs psql and needs it“; seit PR #255 legt
     der Entrypoint seine Datenbank mit psycopg an (`apps/monitoring/docker-entrypoint.sh:38-55`). Dessen
     Meldungen dort sind deutsch (`:51` „Lege Datenbank … an...“, `:54` „FEHLER: Datenbank …“), die Tests prüfen den
     Wortlaut (`apps/server/tests/test_images_exec_only.py:347`, `:357`).
   - R-0792: `docs/en/developer/index.html:38-39` — „FastAPI 0.11“, „Vite 5“; im Repo `fastapi==0.138.0`
     (`apps/server/requirements.txt:239`) und Vite 8.1.6 (`apps/web/package-lock.json`). Die DE-Seite nennt keine
     Versionen (`docs/developer/index.html:41`, `:46` auf `feature/docs-drift`). `apps/web/vite.config.ts:48-49`
     („Waehrend der Migration … Erst in Phase 11 auf '../server/frontend' umstellen“) und `:52` („after the cutover
     to ../server/frontend“): Der Build bleibt in `dist/`, das Root-`Dockerfile:40` kopiert ihn ins Server-Image
     (`COPY --from=frontend-build /build/dist/ ./frontend/`).
   - R-0601: Kein Test hält `docs/examples` frei von echten Adressen; R-0532 hat einmal gegreppt. Heute stehen dort
     nur `192.0.2.1` und `192.0.2.2` (`docs/examples/webhook_http_import.py:24-25`).
   - R-0595: `CHANGELOG.md:665-670` (Abschnitt 0.46.0, R-0551): „gilt das getippte Passwort nur fuer diesen Start“;
     unter Windows verwirft der Desktop ein getipptes Passwort, mstsc fragt selbst
     (`apps/desktop/src-tauri/src/connection/mod.rs:25-31`).
   - R-0782: Der Eintrag zu R-0659 (nur auf `origin/feature/desktop-ui-fixes`, PR #262) sagt „die Fenstergroesse
     ‚Eingepasst‘ [nimmt] die Groesse des Bildschirms“; `fit_window_size` nimmt 85 % der Breite und 85 % der Höhe
     minus 80 px, mindestens 1024x720 (`apps/desktop/src-tauri/src/connection/rdp_logic.rs:128-141`). Die Einstellung
     heißt „Fenstermodus“ (`settings.rdp.windowMode`, auf dem Branch
     `apps/desktop/ui/src/lib/i18n/dictionaries.ts:260`).

## Ziel & Nicht-Ziele

Ziel:
- Die Doku nennt die hingenommenen Restrisiken (R-0798, R-0453) so, wie der Code sich verhält, und sagt dem Admin,
  was wirkt (R-0453: `secretKey`s und `auth.token` rotieren).
- Jede Stelle aus R-0754, R-0758, R-0609, R-0794, R-0769, R-0770, R-0602, R-0792 beschreibt den Code; die zwei
  CHANGELOG-Einträge (R-0595, R-0782) sind vor dem nächsten Release genau.
- `apps/data/` ist ignoriert (R-0791), ein Test hält es fest; ein Test hält `docs/examples` frei von Adressen
  außerhalb RFC 5737 (R-0601); Compose-Kommentar und Entrypoint-Meldungen stimmen (R-0732).
- Nur auf Kevins Ja (T15): Der Desktop stoppt frpc, wenn der Server das Visitor-Bundle mit 403 verweigert.

Nicht-Ziele:
- Kein Code für R-0798 (Kevin 2026-10-22). Der `Stream-Mode: 1`-Header (VictoriaMetrics überspringt dann nur die
  ungültigen Zeilen, Probe unten) wäre eine Ein-Zeilen-Abhilfe; er steht hier als Hinweis für eine spätere Zeile,
  nicht als Task.
- Keine Sperrprüfung in frps, kein automatisches Rotieren beim Löschen (wäre Verhalten, nicht Gegenstand der
  Zeile); der Desktop-Stopp bei endgültig abgelehnter Erneuerung ist schon gebaut (oben, Punkt 2).
- R-0601 prüft IPv4 gegen RFC 5737; IPv6 (RFC 3849) nicht, `docs/examples` enthält keine IPv6-Adresse. Andere
  Ordner unter `docs/` prüft der Test nicht.
- R-0792: Die Testzahlen der EN-Karten („100+ pytest tests“, „~250 Vitest“) gehören zu keiner Zeile.
- R-0732: Die übrigen deutschen `echo`-Zeilen der Entrypoints (`apps/monitoring/docker-entrypoint.sh:17`, `:57`,
  `:59`, `apps/server/docker-entrypoint.sh:19`) sind Alt-Bestand und bleiben.
- R-0595: Der Release-Text von v0.46.0 auf GitHub ändert sich durch den Commit nicht (Release ist Kevins Bereich).
- Keine Zeile ist überholt; jede wird eine Task.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien | Zeile |
|---|---|---|---|
| T1 | scripts | `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` | R-0798 |
| T2 | scripts | `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html` | R-0754 |
| T3 | scripts | `docs/developer/server.html`, `docs/en/developer/server.html` | R-0758 |
| T4 | scripts | `docs/admin/betrieb.html`, `docs/en/admin/operations.html` | R-0609 |
| T5 | scripts | `docs/admin/frp-tunnel.html`, `docs/en/admin/frp-tunnel.html`, `docs/adr/0001-unified-pki-and-secure-deployment.md` | R-0794, R-0453 |
| T6 | scripts | `docs/admin/benutzer.html`, `docs/en/admin/users.html` | R-0453 |
| T7 | scripts | `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `docs/en/admin/troubleshooting.html` | R-0769, R-0770, R-0453 |
| T8 | desktop-rs | `apps/desktop/src-tauri/src/error.rs`, `apps/desktop/src-tauri/src/session.rs` | R-0769 |
| T9 | scripts | `.gitignore`, `scripts/tests/gitignore_test.sh`, `DEVELOPMENT.md` | R-0791, R-0602 |
| T10 | server | `docker-compose.yml`, `apps/monitoring/docker-entrypoint.sh`, `apps/server/tests/test_images_exec_only.py` | R-0732 |
| T11 | web | `docs/en/developer/index.html`, `apps/web/vite.config.ts` | R-0792 |
| T12 | server | `apps/server/tests/test_hook_examples.py` | R-0601 |
| T13 | scripts | `CHANGELOG.md` | R-0595 |
| T14 | scripts | `CHANGELOG.md` | R-0782 |
| T15 `[?]` | desktop-rs | `apps/desktop/src-tauri/src/frpc.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `CHANGELOG.md` | R-0453 (optional) |

Überschneidungen mit parallelen Branches (Stand 2026-10-22, `git diff --name-only origin/main...<branch>` und deren
Ledger), alle in anderen Abschnitten der Dateien:
- `docs/developer/monitoring.html` (+EN): `feature/docs-drift` T4, `monitoring-io` (#265, :263 ist der Absatz von T1).
- `docs/admin/monitoring.html` (+EN): `monitoring-io`, `feature/smtp-hardening`.
- `docs/developer/server.html` (+EN): `feature/docs-drift` T3 (:111, :215-220), `feature/server-hardening`,
  `feature/compose-hardening` T11.
- `docs/admin/betrieb.html` / `operations.html`: `feature/compose-hardening` (T1–T3, T7, T10), `feature/smtp-hardening`.
- `docs/admin/frp-tunnel.html` (+EN): `desktop-ui-fixes` (#262, nur :102 Visitor-Ports).
- `docs/admin/benutzer.html` / `users.html`: `feature/compose-hardening` T12.
- `docs/en/admin/troubleshooting.html`: `feature/docs-drift` T5 (:63, :123).
- `docs/en/developer/index.html`, `apps/web/vite.config.ts`: `feature/docs-drift` T1/T2 (fertig), `docs/developer/index.html`
  dazu `feature/compose-hardening` T4.
- `docker-compose.yml`: `feature/compose-hardening` (T1, T2, T4, T6, T10, T12), `feature/smtp-hardening`.
  `apps/monitoring/docker-entrypoint.sh` steht in keinem dieser Ledger.
- `CHANGELOG.md`: fast alle laufenden Vorhaben (union merge).

## Datenmodell / API / Migrationen

Keine. Keine Route, kein Schema, keine Migration, kein Tauri-Command. T15 ändert kein IPC-Format: 403 führt auf das
vorhandene Ergebnis `stopped` (`apps/desktop/src-tauri/src/models.rs:180-187`), das die UI schon als „idle“ zeigt
(`apps/desktop/ui/src/lib/stores/tunnel.ts:216-227`).

## Externe Integrationen

- **VictoriaMetrics `/write`** (`docs.victoriametrics.com/victoriametrics/integrations/influxdb/`, gelesen
  2026-10-22): Im Stream-Modus (`Stream-Mode: 1` oder `-influx.forceStreamMode`) „Invalid lines are skipped and
  logged“. Was der Normalmodus mit einer ungültigen Zeile macht und welche Statuscodes `/write` liefert, sagt die
  Doku nicht. **Probe** gegen das gepinnte Image (`docker-compose.yml:407`, v1.144.0, dreimal identisch): ein Body
  aus zwei gültigen Zeilen und einer ungültigen (`probe_bad,check_id=x value=1i,`) → HTTP 400 „cannot process influx
  line protocol data: incorrect influx line …“, **keine** der gültigen Zeilen gespeichert; derselbe Body mit
  `Stream-Mode: 1` → HTTP 204, beide gültigen Zeilen gespeichert. `GET /write` → 204. Ob VictoriaMetrics selbst je mit
  3xx antwortet: nicht verifiziert (die Doku nennt es nicht, die Probe sah keins); 3xx kommt in der Praxis von einem
  Proxy vor einer externen `VICTORIA_METRICS_URL`. Der Satz in T1 stützt sich darum auf den Code (jede Antwort unter
  500, die nicht 2xx ist), nicht auf ein Verhalten von VictoriaMetrics.
- **httpx** (`python-httpx.org/compatibility/`, gelesen 2026-10-22): „Unlike requests, HTTPX does not follow
  redirects by default“; `is_success` heißt 2xx.
- **frp** (`gofrp.org/en/docs/reference/common/`, `…/server-configures/`, gelesen 2026-10-22): `transport.tls` kennt
  `force`, Zertifikat, Schlüssel und `trustedCaFile`, keine Sperrliste (CRL/OCSP); `auth.token` muss bei Client und
  Server gleich sein. Dass frps ein widerrufenes, noch gültiges Zertifikat annimmt, ist daraus geschlossen, nicht
  geprobt („nicht verifiziert“ im Sinne einer Probe; die Doku in T5/T6 sagt nur, dass frps keine Sperre prüft).

## Trade-offs & Alternativen

- **R-0798, Ort des Satzes:** Entwicklerdoku Monitoring, im Absatz, der den Schreibweg schon beschreibt (nach
  #265 `:263`). Die Admin-Doku bekäme einen zweiten Satz und zwei weitere Dateien; der Admin sieht den Verlust als
  WARNING-Zeile von `monitor.victoria`, die die Entwicklerdoku nennt. Entschieden: nur Entwicklerdoku.
- **R-0791:** `.gitignore` um `/apps/data/` statt der vier Befehle in `DEVELOPMENT.md` (2×) und
  `docs/developer/index.html` (DE+EN, `feature/docs-drift`) auf `DATA_DIR=../../data` umzuschreiben. Eine Zeile deckt
  alle Kopien des Befehls und bestehende Checkouts ab und hängt nicht an docs-drift; Preis: die Dev-Daten liegen
  weiter unter `apps/`. `gitignore_test.sh` ist kein Harness-Pfad (`scripts/dev/review-risk.txt:66-72`).
- **R-0792, Versionen streichen statt nachziehen:** Die EN-Karten verlieren die Versionsnummern (wie die DE-Seite),
  statt sie auf FastAPI 0.138 und Vite 8 zu setzen; jede Nummer dort veraltet mit dem nächsten Dependency-Update, die
  Lockdateien sind die Quelle. Preis: die Übersicht sagt nicht mehr, welche Hauptversion gilt.
- **R-0601, Ort des Tests:** in `apps/server/tests/test_hook_examples.py`, das `docs/examples` schon liest und in der
  Server-Suite läuft. Ein neuer `scripts/tests/*_test.sh` müsste in `AH_SCRIPT_TESTS_DEFAULT` von
  `scripts/tests/run.sh:653-657` eingetragen werden, einem Harness-Pfad (CLAUDE.md §4); `doc-smoke.py` liegt unter
  `scripts/dev/`, ebenfalls Harness. Gegenprobe im Test selbst: eine Adresse außerhalb RFC 5737 (`198.18.0.1`,
  RFC 2544) muss der Prüfer melden, `192.0.2.1` nicht.
- **R-0453, Doku unabhängig von T15:** T5/T6 beschreiben, was der Server garantiert (API gesperrt, frps prüft keine
  Sperre, wer die Visitor-Konfiguration hat, kommt durch) und nicht, was der Desktop bei 403 tut. So stimmen sie mit
  und ohne T15; ein kopierter oder veränderter Client ist von T15 ohnehin nicht betroffen.
- **T15, Varianten** (Kevins Entscheidung, Offene Fragen): (a) 403 wie 404 behandeln — frpc stoppt beim nächsten
  Abgleich (≤ 60 s), Ergebnis `stopped`, UI „idle“, ohne Meldung; nur `frpc.rs`, kein IPC-Vertrag, gleich wie
  `tunnel.rs:39-43`/`sync.rs`, die bei 401/403 ihre Listen fallen lassen. (b) Stopp plus eigene Meldung — neues
  Ergebnis in `RefreshOutcome` (IPC-Vertrag, `models.rs`, Bridge-Typen, Paritätstest) und UI-Änderung, zwei
  Komponenten. (c) Nichts bauen — ein unveränderter Desktop hält den Tunnel nach dem Löschen offen, bis die App
  schließt. (a) nur bei `ERR_CERT_REVOKED` wäre enger, hängt aber an einem Text im Body.

## Risiken & Rollback

- Doku-Tasks: kein Laufzeitrisiko; Rollback = Revert des Commits. Merge-Konflikte mit den parallelen Branches nur
  bei gleichzeitigem Ändern derselben Absätze (Liste oben); T1, T2 warten auf #265, T11 auf docs-drift, T14 auf #262.
- T9: `/apps/data/` ignorieren versteckt nur dieses Verzeichnis; im Repo liegt dort nichts (`git ls-files apps/data`
  leer).
- T10: Die Entrypoint-Meldungen ändern sich; wer Logs auf den deutschen Text greppt, findet ihn nicht mehr (kein
  bekannter Verbraucher: `git grep` findet nur den Test). `docker-compose.yml` ist Risikopfad → `security`.
- T15: Ein vorübergehendes 403 (etwa eine IP-Restriktion nach Netzwechsel) stoppt den Tunnel; der nächste Abgleich
  nach einem 200 startet ihn wieder. `frpc.rs` ist Risikopfad → `security`. Rollback = Revert.

## Doku-Impact

T1–T7, T9 (DEVELOPMENT.md), T11, T13, T14 sind die Doku. CHANGELOG: nur T15 (Changed), falls gebaut; die übrigen
Tasks ändern kein Verhalten für Nutzer (Doku, Kommentare, `.gitignore`, ein Test, Log-Texte des Entrypoints).

## Offene Fragen

1. **T15 — Soll der Desktop frpc stoppen, wenn der Server das Visitor-Bundle mit 403 verweigert?** Optionen (a), (b),
   (c) wie unter Trade-offs. Empfehlung **(a)**: schließt für einen unveränderten Desktop die Lücke „Benutzer
   gelöscht oder Gerät widerrufen, Tunnel läuft weiter“ binnen 60 s, eine Datei, kein Vertrag, gleiches Verhalten wie
   die Listen bei 401/403. Trade-off: keine Meldung, warum der Tunnel weg ist (die übrigen Aufrufe zeigen
   `ERR_CERT_REVOKED`), und ein 403 aus anderem Grund stoppt ebenfalls. Ersetzt nicht die Rotation aus T5/T6.
