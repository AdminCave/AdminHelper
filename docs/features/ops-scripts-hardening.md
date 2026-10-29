<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Betriebsskripte: Backup-Archiv privat und vollständig, `.env` byte-treu, Diagnose-Bundle maskiert echte Token-Formen

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/ops-scripts-hardening.md`. Roadmap R-0559 (T2); T1, T3 und T4 gehören zum Paket (Härtung, Kevin 2026-10-22).
Das Schwester-Vorhaben `ops-install-hardening` (eigener Branch) härtet `install.sh`, `update.sh` und
`agent-install.sh`; die beiden teilen keine Datei außer `README.md` und `CHANGELOG.md`.

## Problem / Motivation

1. **Backup-Archiv (T1).** `scripts/backup.sh` legt den Zielordner mit der umask des Aufrufers an (`:50`, Default
   `./backups`, `:27`) und schreibt das Archiv direkt unter seinem endgültigen Namen (`:117-118`); den Modus 0600
   bekommt es erst nach `tar` (`:119`). Das Archiv trägt die PKI (`ca-pki`), beide Datenbank-Dumps, `server-data`
   und `env.sanitized` (Kopfkommentar `:5-10`). Während `tar` schreibt (mit `--with-victoria` Minuten), hat die Datei
   also den Modus der umask (meist 0644); bricht der Lauf ab (Platte voll, Abbruch, Absturz), bleibt ein gekürztes
   Archiv unter einem Namen, den `restore.sh` und die Doku („`./backups/<neuestes>.tar.gz`“, `scripts/update.sh:368`)
   als gültig behandeln. `scripts/pg-backup.sh:21-30` macht es schon richtig: Zwischendatei, dann Umbenennen (4.122).
   Beleg (Probe an `origin/main@b1432223`, `backup.sh` mit docker-Stub, ein tar-Wrapper notiert den Modus direkt nach
   dem Schreiben, `umask 022`, dreimal identisch): `644 ./backups/adminhelper-backup-<ts>.tar.gz`, danach Ordner 755,
   Archiv 600.

2. **`env.sanitized` verliert Zeilen (R-0559, T2).** `backup.sh:100` filtert die `.env` mit
   `grep -v '^[[:space:]]*CA_ROOT_PASSPHRASE=' .env > "$STAGE/env.sanitized" || true` unter der Locale des Aufrufers.
   GNU grep behandelt eine Zeile mit einem Byte, das die Locale nicht dekodiert, als binär und gibt sie nicht aus;
   ein NUL-Byte macht die ganze Datei binär. `|| true` verschluckt außerdem jeden Fehler von grep (Exit 2, auch ein
   Schreibfehler). Dieselbe Ursache hat R-0530 in `install.sh`/`update.sh` behoben (`LC_ALL=C grep -a`,
   `scripts/install.sh:193-203`). Beleg unten bei T2.

3. **Diagnose-Bundle (T3, T4).** `scripts/diagnostics.sh` erzeugt ein Bundle für Bug-Reports und wirbt damit, dass
   Secrets maskiert sind (Kopfkommentar `:12-15`, `docs/admin/troubleshooting.html:140-149`, EN `:128-137`,
   `README.md:298-308`). Die Maskierung arbeitet auf zwei Wegen: nach Wert (`build_redaction_sedfile`, `:42-67`) und
   nach Schlüssel für `env.sanitized` (`sanitize_env`, `:77-81`). Dabei:
   - Die Muster (`:62-66`) kennen JWT, Bearer und `ah_…`. Kein Token des Projekts beginnt mit `ah_`: API-Keys sind
     `secrets.token_urlsafe(32)` (`apps/server/app/core/auth.py:62-64`), Webhook-Trigger-Token ebenso
     (`apps/server/app/modules/hooks/router.py:153`), Provisionierungs-Token `adminhelper_prov_<…>`
     (`apps/server/app/modules/provisioning/router.py:70`). In den Logs stehen API-Keys als `?api_key=` (der
     dokumentierte Weg für Sync-URLs, `auth.py:197-210`, `docs/admin/benutzer.html:127`) in den Access-Log-Zeilen von
     Gateway (nginx `combined`, Request-Zeile samt Query) und Server (uvicorn), Webhook-Token im Pfad
     `/api/hooks/trigger/<token>` (`router.py:242-245`, Kommentar `:230-231`).
   - Die Werte aus der `.env` liest `:49` mit `grep -E` unter der Locale des Aufrufers und entfernt nur doppelte
     Anführungszeichen (`:50-51`). Ein Wert in einfachen Anführungszeichen oder mit `$$` wird in seiner Dateiform
     gesucht, im Log steht die Form, die compose daraus macht. Ein Byte außerhalb UTF-8 im Wert lässt grep die Zeile
     auslassen; `sanitize_env` (`sed -E`, `.*` endet unter UTF-8 vor einem solchen Byte) ersetzt den Wert dann nur bis
     zu diesem Byte.
   - Hostnamen und Adressen (`DOMAIN`, `EXTRA_SANS`, `ALLOWED_IPS`, Client-Adressen in den Access-Logs, der Hostname in
     `report.txt`) bleiben stehen; `report.txt` (`:100-120`) läuft nicht durch die Maskierung.
   Beleg (Probe an `origin/main@b1432223`, dreimal identisch): `build_redaction_sedfile` + `redact` mit
   `SMTP_PASSWORD='sq9pass'` und `POSTGRES_PASSWORD=pg$$9word` in der `.env` und je einer nginx- und uvicorn-Zeile mit
   `?api_key=…`, einer Zeile `POST /api/hooks/trigger/<token>`, einer mit `adminhelper_prov_<…>` und einer mit
   `sq9pass`/`pg$9word`: keine der Zeilen wird verändert. `sanitize_env` unter `LC_ALL=C.UTF-8` mit
   `POSTGRES_PASSWORD=pg\xe9tail9secret` ergibt `POSTGRES_PASSWORD=<redacted>\xe9tail9secret`.

## Ziel & Nicht-Ziele

Ziel:
- `backup.sh`: das Archiv ist vom ersten Byte an nur für den ausführenden Nutzer lesbar (0600) und erscheint unter
  `adminhelper-backup-<ts>.tar.gz` erst, wenn es vollständig geschrieben ist; ein neu angelegter Zielordner bekommt
  0700. Ein gescheiterter Lauf hinterlässt kein Archiv und keine Zwischendatei.
- `backup.sh`: `env.sanitized` ist die `.env` byte-gleich ohne die `CA_ROOT_PASSPHRASE`-Zeile(n), auch mit Bytes
  außerhalb UTF-8 und NUL-Bytes; ein Fehler beim Filtern bricht das Backup ab.
- `diagnostics.sh`: maskiert die Formen, in denen Zugangsdaten des Projekts in Logs stehen: `api_key=`, `token=` und
  `access_token=` in Query-Strings, das Token-Segment hinter `/hooks/trigger/`, `adminhelper_prov_<…>`; liest die
  `.env` byte-treu und Werte so, wie compose sie liest; maskiert auch `report.txt`. Die Regel `ah_…` entfällt.
- `diagnostics.sh --mask-hosts` maskiert zusätzlich Hostnamen und Adressen; Kopfkommentar und Doku sagen, was ohne
  den Schalter stehen bleibt.

Nicht-Ziele (YAGNI):
- Kein `chmod` an einem schon bestehenden Zielordner, kein Aufräumen alter Zwischendateien per Glob.
- Keine Verschlüsselung des Backups, keine Retention in `backup.sh`.
- Keine allgemeine Maskierung aller Query-Werte (Filter, `limit` usw. bleiben lesbar).
- Die gleiche `ah_`-Regel im Agent (`apps/agent/internal/diagnostics/diagnostics.go:31`) und im Desktop
  (`apps/desktop/src-tauri/src/diagnostics.rs:130`) bleibt; eigene Zeile, falls gewünscht (offene Frage 2).
- `.github/ISSUE_TEMPLATE/bug_report.yml` bleibt unverändert.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | scripts | `scripts/backup.sh`, `scripts/tests/restore_guard_test.sh`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T2 | scripts | `scripts/backup.sh`, `scripts/tests/restore_guard_test.sh`, `CHANGELOG.md` |
| T3 | scripts | `scripts/diagnostics.sh`, `scripts/tests/diagnostics_test.sh`, `CHANGELOG.md` |
| T4 | scripts | `scripts/diagnostics.sh`, `scripts/tests/diagnostics_test.sh`, `docs/admin/troubleshooting.html`, `docs/en/admin/troubleshooting.html`, `README.md`, `CHANGELOG.md` |

Die Tests für `backup.sh` kommen in `scripts/tests/restore_guard_test.sh` (hermetisch, schon im Block
`scripts`, `scripts/tests/run.sh:608-613`; Kopf heute „hermetic tests for restore.sh and pg-restore.sh“). Eine eigene
Testdatei bräuchte einen Eintrag in `run.sh` (Harness-Pfad); der Kopf der Datei nennt danach auch `backup.sh`.

## Datenmodell / API / Migrationen

Keine. Kein Server-, Agent- oder Desktop-Code, keine Route, kein Schema, keine Migration. Sichtbar ändern sich: der
Modus eines neu angelegten Backup-Ordners (0700), ein neuer Schalter `diagnostics.sh --mask-hosts`, der Inhalt des
Diagnose-Bundles (mehr maskiert) und die Doku-Sätze dazu.

## Externe Integrationen

- GNU grep (Handbuch, „Usage“/Binary files; R-0530 belegt das Verhalten am Projekt): eine Zeile mit einem
  Kodierungsfehler gilt als binär und wird nicht ausgegeben; `-a` liest als Text, `LC_ALL=C` dekodiert byteweise.
  Hier zusätzlich belegt mit GNU grep 3.11.
- nginx `log_format combined` (https://nginx.org/en/docs/http/ngx_http_log_module.html#log_format):
  `$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"`;
  `$request` ist die Request-Zeile samt Query. Das Gateway setzt kein eigenes Format (`apps/gateway/nginx.conf`).
- uvicorn-Access-Log: `<client>:<port> - "<METHOD> <path?query> HTTP/1.1" <status>`, aktiv über
  `apps/server/app/core/logging_config.py:61`.
- docker compose `.env`-Syntax (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/,
  gelesen 2026-10-22): einfache Anführungszeichen wörtlich, unquotierte und doppelt gequotete Werte werden
  interpoliert (`$$` → `$`), „Inline comments for unquoted values must be preceded with a space“.

## Trade-offs & Alternativen

1. **Zwischendatei für das Archiv (T1).** (a) `mktemp "$OUT_DIR/.adminhelper-backup-<ts>.XXXXXX"` im Zielordner,
   `tar` hinein, `mv -f` auf den endgültigen Namen, dazu `umask 077` am Anfang des Skripts — **Empfehlung**:
   `mktemp` legt 0600 an, unabhängig von der umask; im selben Ordner ist `mv` ein Umbenennen; der versteckte Name passt
   nicht auf `*.tar.gz`. (b) Archiv in `$STAGE` bauen und verschieben: `$STAGE` liegt unter `$TMPDIR`, oft ein anderes
   Dateisystem (tmpfs) — kein Umbenennen, eine volle Kopie, und Platz für Victoria-Daten fehlt dort. (c) Nur `umask`:
   lässt das gekürzte Archiv unter gültigem Namen.
2. **Wo die `backup.sh`-Tests liegen.** In `restore_guard_test.sh` (Empfehlung, kein Harness-Pfad) statt einer neuen
   Datei, die `run.sh` registrieren müsste.
3. **Token-Regeln (T3).** Gezielt für `api_key`, `token`, `access_token` als Query-Parameter, das Segment hinter
   `/hooks/trigger/` und `adminhelper_prov_` — Empfehlung. Alternative „jeden Query-Wert maskieren“ nimmt Diagnose
   (Filter, Paging) mit.
4. **Hosts und Adressen (T4).** (a) Schalter `--mask-hosts`, Default wie heute — **Empfehlung**, wie die Roadmap-Zeile
   („optional“): Domain- und SAN-Fehler sind eine häufige Ursache, die das Bundle zeigen soll. (b) Maskieren als
   Default mit `--keep-hosts`: wer das Bundle öffentlich anhängt, muss nichts wissen; dafür fehlen Domain und SANs in
   den meisten Bundles (offene Frage 1).
5. **IPv6 im Log (T4).** Nur Formen mit `::` und die volle Form mit acht Gruppen; eine Zeit `HH:MM:SS` bleibt stehen
   (Test). Alles Allgemeinere trifft Zeitstempel.

## Risiken & Rollback

- T1 ändert den Modus eines neu angelegten Backup-Ordners auf 0700; wer Backups mit einem anderen Nutzer abholt, muss
  den Ordner selbst freigeben (CHANGELOG nennt es). Ein bestehender Ordner bleibt, wie er ist.
- T3 maskiert mehr; ein Wert, der zufällig wie ein Token-Parameter aussieht, verschwindet aus dem Bundle (gewollt).
- Rollback je Task per `git revert`; keine Daten- oder Formatänderung am Archiv (Inhalt und Namen bleiben,
  `restore.sh` unverändert).

## Doku-Impact

T1: `docs/admin/betrieb.html:91` / `docs/en/admin/operations.html:58` ein Satz zu Modus und Vollständigkeit des
Archivs. T4: `docs/admin/troubleshooting.html:140-149` / EN `:128-137` und `README.md:298-308` — `--mask-hosts` und
was ohne ihn stehen bleibt. CHANGELOG je Task (umlautfrei). T2 und T3: nur CHANGELOG.

## Offene Fragen

1. **`--mask-hosts` als Schalter (gebaut) oder als Default?** Empfehlung: Schalter, wie die Roadmap-Zeile; der Default
   lässt sich später mit einer Zeile umdrehen. Hält T4 nicht an.
2. **Gleiche `ah_`-Regel im Agent und im Desktop** (Nicht-Ziele): eigene REF-Zeile? Empfehlung: ja, `neu`.
