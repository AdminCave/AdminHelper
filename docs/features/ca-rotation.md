<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CA-Issuer: Intermediates rotieren

Stand des Codes: `origin/main@e2304a8b` (für `apps/ca-issuer`, Gateway, Desktop und Doku gleich `237b450a`). Alle
`datei:zeile` beziehen sich auf diesen Stand; nach dem Merge von R-0666 verschieben sich Zeilen in
`apps/ca-issuer/app/{pki,storage,issuer}.py`. Ledger: `tasks/ca-rotation.md`. Roadmap R-0667 (FEAT). Hängt ab von
R-0666 (`feature/ca-issuer-lifetime`, `docs/features/ca-issuer-lifetime.md`): Begrenzung der Leaves auf ihren
Aussteller, Prüfung der Hierarchie beim Start, `pki.IssuerNotValid`, `pki.days_left`, `pki.EXPIRY_WARN_DAYS`.

## Problem / Motivation

Die drei Intermediates (`tunnel`, `access`, `internal`) gelten 5 Jahre (`apps/ca-issuer/app/pki.py:36`), die Root
10 Jahre (`:35`). Einen Weg, neue Intermediates auszustellen, gibt es nicht: `ensure_hierarchy` erzeugt sie nur beim
ersten Start und lädt sonst, was auf der Platte liegt (`apps/ca-issuer/app/storage.py:85-138`). Trotzdem behaupten
Code und Doku ihn: `storage.py:13-14` („the root is decrypted solely to create/rotate intermediates“),
`scripts/backup.sh:18-20` und `:112-114` („the passphrase is only needed to rotate intermediates“),
`docs/admin/betrieb.html:96` bzw. `docs/en/admin/operations.html:63` („gebraucht wird sie nur zum Rotieren der
Intermediates“), ADR 0001 D7 (`docs/adr/0001-unified-pki-and-secure-deployment.md:86`, „Root nur bei
Intermediate-Rotation angefasst“). Nach R-0666 läuft ein Stack im fünften Jahr nicht mehr still weiter, sondern
warnt ab 180 Tagen und startet nach dem Ablauf nicht mehr; ohne Rotationsbefehl bliebe nur, die PKI neu zu erzeugen
und jeden Client neu zu enrollen.

Wer was pinnt und prüft (Ist-Stand, alle Verbraucher gelesen):

| Verbraucher | prüft gegen | präsentiert | nach einer Rotation (Root bleibt) |
|---|---|---|---|
| Issuer `/renew` | nur das aktuelle Intermediate des Scopes (`apps/ca-issuer/app/issuer.py:58-66`) | — | **bricht**: ein Leaf des alten Intermediates erneuert nicht mehr |
| Gateway (nginx, `:443`) | `client-ca.pem` = access-Intermediate + Root (`apps/gateway/nginx.conf:89-91`, `storage.py:203-204`, `:248`) | `gateway-fullchain.pem` = Leaf + access-Intermediate (`nginx.conf:87`, `storage.py:222-223`) | Agent und Desktop schicken Leaf + Intermediate, die Kette endet an der Root: geht. Browser-`.p12` enthält nur das Leaf (`apps/desktop/src-tauri/src/enrollment.rs:821-834`): das alte Intermediate muss in `client-ca.pem` bleiben, bis diese Leaves abgelaufen sind. nginx lädt die Dateien nur beim Start (`apps/gateway/docker-entrypoint.sh:57`, kein Reload im Repo) |
| frps | `ca.crt` = tunnel-Intermediate + Root + access-Intermediate (`storage.py:203`, `apps/ca-issuer/app/main.py:48-57`) | `frps.crt` = Leaf + tunnel-Intermediate | Der Supervisor übernimmt geänderte `frps.crt`/`ca.crt` selbst und startet frps neu (`apps/frps/frps-supervisor.sh:111`, `:183`, Takt `:93`) |
| Agent | `identity/ca.crt` = `chain` (tunnel-Intermediate + Root) als `RootCAs` (`apps/agent/internal/httpclient/httpclient.go:77-99`); nach jedem Renew überschrieben (`apps/agent/internal/enroll/enroll.go:228-235`) | `agent.crt` = Fullchain | geht (Root im Pool); frpc prüft frps gegen dieselbe Datei |
| Desktop | `enroll|ca` = `chain` (access-Intermediate + Root) als Anker (`enrollment.rs:748-763`) | Fullchain (`:765-768`) | geht (Root im Pool) |
| `--ca-fp` beim Provisionieren | SHA-256 des access-Intermediates, der Desktop zeigt ihn (`enrollment.rs:256-264`); der Agent sucht ihn in der präsentierten Kette (`httpclient.go:145-188`) | — | **bricht**: das Gateway präsentiert nach der Rotation ein anderes Intermediate; der Desktop zeigt den neuen Wert erst nach seiner nächsten Erneuerung (bei der Anmeldung ab halber Laufzeit) |
| Desktop vor dem Enrollment | TOFU auf das Gateway-Leaf (`apps/desktop/src-tauri/src/tofu.rs:12-20`) | — | bricht bei jedem Re-Mint des Gateway-Leafs, wie heute schon beim Re-Mint nach halber Laufzeit |
| Server | nichts: liest nur Header und das Leaf (`apps/server/app/core/identity.py:84-105`) | — | unberührt |

Rotierte Intermediates hätten heute denselben Subject-DN (`pki.py:156`); AKI/SKI sind gesetzt (`:169-172`, `:272`).

## Ziel & Nicht-Ziele

Ziel:
- Ein Befehl stellt für alle drei Scopes neue Intermediates unter derselben Root aus. Er entschlüsselt dazu
  `root.key.enc` mit der Passphrase, schreibt die neuen Paare atomar und legt die alten Intermediate-Zertifikate (ohne
  Schlüssel) als „retired“ ab. Er geht auch, wenn der Issuer wegen abgelaufener Intermediates nicht startet (R-0666).
- Ein Lesebefehl `status` zeigt Root, aktuelle und retired Intermediates mit Ablaufdatum und Resttagen.
- Nach dem Neustart signiert der Issuer mit den neuen Intermediates, akzeptiert bei `/renew` aber auch Leaves eines
  retired Intermediates desselben Scopes; Gateway- und frps-Trust-Bundles enthalten alt und neu, bis das alte abläuft
  (dank R-0666 überlebt kein altes Leaf sein Intermediate); die Server-Leaves von Gateway und frps werden unter dem
  neuen Intermediate neu ausgestellt.
- Clients brauchen nichts: Agent und Desktop prüfen gegen die Root und ziehen beim nächsten Renew die neue Kette.
- Empfehlung (offene Frage 2): `--ca-fp` wird der Root-Fingerprint und überlebt damit jede Intermediate-Rotation.

Nicht-Ziele (YAGNI):
- Keine Rotation einzelner Scopes und keine Kompromittierungs-Rotation (altes Intermediate sofort aus allen Bundles,
  alle Leaves des Scopes ungültig): bei einem Leck braucht es den sofortigen Entzug, das ist ein anderer Ablauf
  (ADR 0001 D1, `:80`). Vorschlag: eigene Roadmap-Zeile.
- Keine Root-Erneuerung (Cross-Signing oder neue Root mit Neu-Pinning aller Clients). Rotierte Intermediates enden
  spätestens mit der Root (R-0666); die Root-Warnung aus R-0666 sagt, wann. Vorschlag: eigene Roadmap-Zeile.
- Kein Reload ohne Neustart (nginx-Signal, Datei-Watcher im Gateway); der Neustart von `ca-issuer` und `gateway` ist
  Teil des Ablaufs.
- Keine Ablaufanzeige in der Server-UI oder im Monitoring (R-0666, offene Frage 3).
- Keine Änderung an `docker-compose.yml`, `scripts/backup.sh` und `restore.sh`: das Volume `ca-pki` enthält die
  retired Zertifikate mit, die Kommentare zur Passphrase stimmen nach diesem Vorhaben.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | ca-issuer | `apps/ca-issuer/app/storage.py`, `apps/ca-issuer/tests/test_storage.py` |
| T2 | ca-issuer | `apps/ca-issuer/app/storage.py`, `apps/ca-issuer/tests/test_gateway_cert.py`, `apps/ca-issuer/tests/test_frps_cert.py` |
| T3 | ca-issuer | `apps/ca-issuer/app/issuer.py`, `apps/ca-issuer/tests/test_enroll_renew.py` |
| T4 | ca-issuer | `apps/ca-issuer/app/rotation.py` (neu), `apps/ca-issuer/app/pki.py`, `apps/ca-issuer/tests/test_rotation.py` (neu) |
| T5 `[?]` | ca-issuer | `apps/ca-issuer/app/cli.py` (neu), `apps/ca-issuer/tests/test_cli.py` (neu), `apps/ca-issuer/docker-entrypoint.sh`, `CHANGELOG.md` |
| T6 | ca-issuer | `apps/ca-issuer/app/storage.py`, `apps/ca-issuer/app/issuer.py`, `apps/ca-issuer/tests/test_storage.py`, `apps/ca-issuer/tests/test_enroll_renew.py` |
| T7 `[?]` | ca-issuer | `apps/ca-issuer/app/storage.py`, `apps/ca-issuer/tests/test_gateway_cert.py`, `apps/gateway/nginx.conf`, `CHANGELOG.md` |
| T8 `[?]` | desktop-rs | `apps/desktop/src-tauri/src/enrollment.rs`, `apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |
| T9 | scripts | `scripts/tests/integration_stack_test.sh` |
| T10 | scripts | `docs/admin/betrieb.html`, `docs/en/admin/operations.html` |

T1–T8 berühren Risikopfade aus `scripts/dev/review-risk.txt` (`apps/ca-issuer/*`, `apps/gateway/*`,
`apps/desktop/src-tauri/src/enrollment.rs`) und bekommen zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine DB-Migration, keine Route, kein Schema. Neu auf dem Volume `ca-pki` (Layout `storage.py:7-11`):
`<scope>-retired.pem` — die abgelösten Intermediate-Zertifikate dieses Scopes (nur öffentlich, PEM-Bündel), solange
sie gültig sind; fehlt die Datei, gibt es keine. `.rotate.lock` — Sperrdatei des Rotationsbefehls. Die übrigen Dateien
behalten Namen und Inhalt-Art. Ein Restore eines Backups von vor dem Update lädt wie heute (keine retired-Datei);
ein älteres Image ignoriert die neue Datei, findet aber neue Intermediates mit anderem CN (`AdminHelper <Scope>
Intermediate <Datum>`), die es wie die alten lädt. Kein Vertrags-Drift zu Server oder Web. Mit T7/T8: die Kette, die
das Gateway auf `:443`, `:8444`, `:8445` präsentiert, endet mit der Root; der Desktop zeigt als CA-Fingerprint den der
Root. Der Agent bleibt unverändert (er sucht den Fingerprint in jeder präsentierten Kette, `httpclient.go:145-188`).

## Externe Integrationen

- cryptography 50.0.1, Doku `https://cryptography.io/en/latest/x509/reference/` (gelesen 2026-10-22):
  `serialization.load_pem_private_key(data, password)` mit falscher Passphrase wirft (`ValueError`/`TypeError`, im
  Test festhalten); `verify_directly_issued_by` prüft Name und Signatur, nicht die Zeit.
- nginx (`https://nginx.org/en/docs/http/ngx_http_ssl_module.html`, gelesen 2026-10-22): `ssl_client_certificate` —
  „Specifies a file with trusted CA certificates in the PEM format used to verify client certificates … The list of
  certificates will be sent to clients.“; `ssl_certificate` — „the primary certificate comes first, then the
  intermediate certificates“ (die Root am Ende der Fullchain in T7 ist zulässig). Mehrere Intermediates mit
  verschiedenen Subjects sind eindeutig; dass OpenSSL bei gleichem Subject über AKI/SKI das richtige wählt, ist
  **nicht verifiziert** — deshalb bekommt jede Generation einen eigenen CN.
- Go `crypto/x509` und rustls/webpki behandeln jedes Zertifikat im Anker-Pool als Anker und bauen Pfade über die
  präsentierten Zwischenzertifikate (Bibliotheksverhalten, im Repo nicht verifiziert; der Stack-Schritt T9 und der
  `scenario`-Lauf prüfen es real). Dass frpc und frps die ganze Kette aus `certFile` senden, ist **nicht
  verifiziert**; die Bundles enthalten alt und neu, damit auch ein Leaf ohne Kette passt.
- Docker Compose `run` (`https://docs.docker.com/reference/cli/docker/compose/run/`, gelesen 2026-10-22): der
  Container nimmt seine Konfiguration vom Dienst („volumes, links, and other details“), „the command passed by `run`
  overrides the command defined in the service configuration“, `--no-deps` startet keine abhängigen Dienste, `--rm`
  entfernt ihn danach, das TTY ist „auto-detected“, `-T` schaltet es ab. Dockerfile-Referenz
  (`https://docs.docker.com/reference/dockerfile/`): „Command line arguments to `docker run <image>` will be appended
  after all elements in an exec form `ENTRYPOINT`“ — der Befehl landet als `$@` in
  `apps/ca-issuer/docker-entrypoint.sh`, das ihn heute ignoriert und immer uvicorn startet (`:15-17`); T5 reicht ihn
  durch. Dass Compose die Secrets des Dienstes auch bei `run` einhängt, ist **nicht verifiziert** (Probe in T9).

## Trade-offs & Alternativen

1. **Bedienung (offene Frage 1, T5).** (a) Befehl im Image: `docker compose run --rm --no-deps ca-issuer python -m
   app.cli rotate-intermediates`, danach `docker compose restart ca-issuer`, `healthy` abwarten, dann
   `docker compose restart gateway` (T12) — **Empfehlung**: geht auch bei
   gestopptem Issuer, die Passphrase steht nie in argv, Compose-Datei oder Log, ein Image für alles; der Befehl gibt
   den Neustart-Befehl aus. (b) Zusätzlich `scripts/ca-rotate.sh` auf dem Host, der die Schritte bündelt: ein Befehl
   weniger zu vergessen, aber neue Host-Skript-Fläche mit Docker-Attrappe in den Tests, für eine Handlung alle paar
   Jahre. (c) Rotation beim Start über einen Schalter (`CA_ROTATE=1`): muss nach dem Lauf wieder weg, sonst rotiert
   jeder Neustart.
2. **Passphrase (T5).** Reihenfolge: `config.root_passphrase()` (Secret-Datei `CA_ROOT_PASSPHRASE_FILE`, sonst
   `CA_ROOT_PASSPHRASE`; nach compose-hardening ist die Datei nach dem ersten Start meist leer bzw. fehlt), sonst eine
   Abfrage am Terminal (`getpass`), ohne Terminal die erste Zeile von stdin. Nie als Argument (sichtbar in `ps`).
3. **Ablage der alten Intermediates (T1, T4).** Eine Datei `<scope>-retired.pem` je Scope, nur Zertifikate; der
   alte Schlüssel wird überschrieben (zum Prüfen braucht es ihn nicht, ein liegender Signierschlüssel wäre Risiko
   ohne Nutzen). Abgelaufene werden beim Laden übersprungen und bei der nächsten Rotation entfernt. Alternative:
   ein Verzeichnis je Generation mit Symlink auf die aktuelle — atomarer Wechsel, aber neues Layout für Backup,
   Restore und den Start.
4. **Schreibreihenfolge (T4).** retired-Datei, dann Schlüssel, Zertifikat, Kette, jeweils temporär + `fsync` +
   `os.replace`. Ein Abbruch zwischen Schlüssel und Zertifikat lässt ein Paar zurück, das nicht zusammenpasst: der
   Start bricht dann ab (R-0666), und ein zweiter Lauf des Befehls repariert (er liest vom aktuellen Paar nur das
   Zertifikat). Eine Sperrdatei (`flock`) verhindert zwei Rotationen zugleich.
5. **CN je Generation (T4).** `AdminHelper <Scope> Intermediate <YYYY-MM-DD>` für rotierte Intermediates; die erste
   Generation behält ihren Namen. Grund: eindeutige Issuer-Suche in nginx/OpenSSL bei Leaf-only-Clients, ohne sich
   auf AKI/SKI-Auswahl zu verlassen; lesbar im Log und im Browser. Seit T11 liest der `ca-issuer` den CN eines
   Intermediates (`pki.intermediate_problem`: retired-Einträge, Rotation, `status`), mit T14 auch der Agent; ein
   geändertes CN-Format ließe den Start jeden retired-Eintrag überspringen.
6. **`--ca-fp` (offene Frage 2, T7/T8).** (a) Root-Fingerprint — **Empfehlung**: das Gateway hängt die Root an seine
   Fullchain, der Desktop zeigt den Fingerprint des letzten Zertifikats seiner Kette (der Root); der Agent bleibt
   unverändert, alte Befehle mit dem Intermediate-Fingerprint gelten bis zur nächsten Rotation. Kosten: ~600 Byte je
   Handshake; ein neuer Desktop gegen einen alten Server (ohne Root in der Kette) bekommt beim Provisionieren „no
   presented certificate carries the expected CA fingerprint“, bis der Server aktualisiert ist. (b) Beim
   Intermediate-Fingerprint bleiben und dokumentieren: nach einer Rotation scheitern alle Befehle mit altem Wert, und
   ein Desktop zeigt den neuen erst nach seiner nächsten Erneuerung (bis zu ~45 Tage), dazwischen nur `--insecure`
   oder Neu-Enrollment des Desktops.

## Risiken & Rollback

- Neustart: `docker compose restart ca-issuer`, `healthy` abwarten, dann `docker compose restart gateway` (T12)
  unterbricht `:443` kurz; frps startet nach dem Re-Mint seines
  Leafs selbst neu (Tunnel kurz weg, Agenten verbinden neu). Zwischen dem Neustart des Issuers und dem des Gateways
  signiert der Issuer schon mit dem neuen Intermediate, das Gateway kennt es noch nicht: ein in diesen Sekunden
  ausgestelltes Browser-Zertifikat (nur Leaf) wird bis zum Gateway-Neustart abgelehnt; Agent und Desktop schicken die
  Kette mit und sind nicht betroffen.
- Vergisst der Betreiber den Gateway-Neustart, bleiben Gateway-Leaf und `client-ca.pem` alt, bis das Gateway neu
  startet (jedes Update); neue Browser-Zertifikate scheitern so lange. Der Befehl gibt den Neustart aus, die Doku
  nennt ihn.
- Ein Desktop mit TOFU-Pin vor dem Enrollment muss nach dem Re-Mint des Gateway-Leafs neu bestätigen (wie bei jedem
  Re-Mint).
- Falsche Passphrase oder kaputte Root: der Befehl bricht vor dem ersten Schreibzugriff ab (Test).
- Rollback: Backup von `ca-pki` vor der Rotation (die Doku sagt es); Code-Rollback per Revert, ein älteres Image lädt
  die neuen Intermediates (gleiches Layout), kennt aber die retired-Datei nicht — alte Leaves erneuern dann nicht,
  bis sie ablaufen.

## Doku-Impact

T10: neuer Abschnitt „Zwischenzertifikate der CA rotieren“ in `docs/admin/betrieb.html` / `docs/en/admin/
operations.html` (wann, Befehle, was passiert, was nicht), Link aus dem Passphrase-Callout (`betrieb.html:96`, EN
`:63`); im Abschnitt „Zertifikate erneuern“ (`betrieb.html:172-173`, EN `:130-131`) zwei falsche Angaben richtig: das
Gateway lädt ein neues Leaf erst nach seinem eigenen Neustart (nicht schon mit dem Neustart des `ca-issuer`), und
Agent-Tunnel-Zertifikate gelten 90 Tage und erneuern sich bei halber Laufzeit selbst (nicht „nach 12 Monaten“). T5:
CHANGELOG (Added). T7/T8: CHANGELOG (Changed), `docs/admin/agent-deployment.html:187` + EN `:186`.

## Offene Fragen

1. **Bedienung des Rotationsbefehls** (Trade-off 1, 2): Befehl im Image + zwei Neustarts (Empfehlung), zusätzlich
   ein Host-Skript, oder ein Start-Schalter? Betrifft T5 (und damit T6, T9, T10). Bei „Host-Skript“ eine zusätzliche
   Task `scripts/ca-rotate.sh` (Komponente scripts, Kevin-Merge ist es nicht: nur install/agent-install/update sind
   seine).
2. **`--ca-fp` auf den Root-Fingerprint umstellen** (Trade-off 6)? Empfehlung ja; betrifft T7, T8. Bei „nein“
   entfallen beide, T10 dokumentiert die Folgen der Rotation für `--ca-fp`.
3. **Neue Roadmap-Zeilen** (nicht Teil dieses Vorhabens): Kompromittierungs-Rotation eines Scopes (sofortiger
   Entzug) und Root-Erneuerung.
