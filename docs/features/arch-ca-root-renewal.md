<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-ca-root-renewal — Root der internen PKI erneuern, ohne neu zu enrollen (R-1021)

## Problem / Motivation
Die Root der internen PKI (ADR 0001, `apps/ca-issuer/app/pki.py:36`, zehn Jahre) lässt sich heute nicht erneuern. Der
Boot warnt 180 Tage vor ihrem Ende mit „renewing the root means enrolling every client again“
(`apps/ca-issuer/app/storage.py:219`, Schwelle `pki.py:48`). Auch einen Leck-Fall schließt erst eine neue Root ganz.
Die Betriebsdoku sagt das zu `rotate-intermediates --compromised` (`docs/admin/betrieb.html`, Abschnitt
`ca-rotation`): Agent und Desktop nehmen jedes Zertifikat ihres Bündels als Anker (`chain` der enroll/renew-Antwort,
`apps/ca-issuer/app/issuer.py:127`), also auch die alte Root und das alte Zwischenzertifikat. Ein Leaf, das mit einem
geleakten Zwischenschlüssel signiert ist, bleibt deshalb unter der alten Root gültig. Gesucht ist ein Wechsel auf eine
neue Root, den laufende Clients über ihre normale Erneuerung mitmachen.

## Ziel & Nicht-Ziele
Ziel (Entscheidungen Kevin 2026-11-02, siehe Ledger `## Entscheidungen`):
- **Wechsel in Phasen** über `python -m app.cli rotate-root stage|abort|switch|finish`. Passphrasen kommen wie bei
  `rotate-intermediates` aus Secret-Datei, Env, Terminal oder stdin, nie als Argument. Alles läuft unter
  `.rotate.lock`, atomar je Datei und wiederaufnehmbar.
  - `stage`: neue Root N mit eigenem Schlüssel und eigener Passphrase (sie darf der alten gleichen). Signiert wird
    weiter unter der alten Root R.
  - `abort`: nur vor `switch`, entfernt N wieder.
  - `switch [--compromised SCOPE …] [--no-cross]`: neue Zwischenzertifikate unter N. Die alten wandern in die
    retired-Dateien. Dazu kommt das Cross-Zertifikat X (N, von R gegengezeichnet), und der Schlüssel von R wird
    gelöscht, nachdem X geschrieben ist. `--compromised` leert die retired-Liste des Scopes und nimmt R aus `chain`.
  - `finish [--force]`: R, X und die Zwischenzertifikate unter R verlassen alle Bündel. Ohne `--force` verweigert
    `finish`, solange das Register (`issued_certificates`/`device_lines`) gültige, nicht widerrufene Leaves zeigt, die
    vor `switch` ausgestellt wurden. Ohne erreichbare DB verweigert es ebenfalls.
- **Vertrag `chain`** (Kevin): Der Name bleibt, der Inhalt wird neu festgelegt. Zuerst kommt das ausstellende
  Zwischenzertifikat, dann jede weitere vertraute Root, zuletzt die Root, die :8444 selbstsigniert ausliefert.
  Heutige Agents (`apps/agent/internal/enroll/enroll.go`, ersetzt `ca.crt` ganz) und Desktops (`enroll|ca`)
  übernehmen N so ohne Update. Der Desktop-Pin (letztes PEM, `apps/desktop/src-tauri/src/enrollment.rs:369`) stimmt
  in jeder Phase.
- **Bündel je Phase**, R = alte, N = neue Root, I(·) = Zwischenzertifikat, A = access, T = tunnel:

  | Datei / Feld | Phase 0 | `stage` | `switch` | `finish` |
  |---|---|---|---|---|
  | `chain` | I(R) R | I(R) N R | I(N) R N (mit `--compromised`: I(N) N) | I(N) N |
  | `gateway-fullchain.pem` (:443, :8445) | leaf A(R) R | unverändert | leaf A(N) X R | leaf A(N) N |
  | neu `gateway-enroll-fullchain.pem` (:8444) | = fullchain | = fullchain | leaf A(N) X R N | = fullchain |
  | `client-ca.pem` | A(R) R + retired | unverändert | A(N) N + retired A(R) R | A(N) N + retired unter N |
  | `frps.crt` / frps `ca.crt` | leaf T(R) / Zwischenz. | unverändert | leaf T(N) X / I(N) + I(R) | leaf T(N) / I(N) |
  | `ca-trust/<scope>.pem` (Server) | I + retired | unverändert | I(N) + I(R) (ohne `--compromised`-Scope) | I(N) + retired |

  Der Advisor hat das mit OpenSSL 3.5, GnuTLS 3.8, Go 1.26 und rustls-webpki 0.103 geprobt (ohne Probe-Dateien im
  Repo). Das selbstsignierte N darf nie neben X auf einem Listener stehen, den GnuTLS-Clients nutzen: apt < 3.0 auf
  :8445 lehnt diese Kette ab, wenn es nur N vertraut. N braucht nur :8444, wo `--ca-fp` es unter den präsentierten
  Zertifikaten sucht (`apps/agent/internal/httpclient/httpclient.go:175`).
- **Boot** (`ensure_hierarchy`, `storage.py:110`) erkennt die Phase an den Dateien. Einen halben `switch` verweigert er
  mit dem Hinweis, `switch` erneut aufzurufen. Retired-Zwischenzertifikate unter R nimmt er an, das tut heute nur
  `_load_retired`, `storage.py:255`. Ist R abgelaufen, liefert er X und R nicht mehr aus und meldet „finish
  ausstehend“. `rotate-intermediates` läuft in jeder Phase.
- **Sichtbarkeit** (Kevin):
  - `status` zeigt Phase, N/R/X und die Abdeckung: Geräte, deren jüngstes Zertifikat nach `stage` bzw. `switch`
    ausgestellt ist, ohne DB „unbekannt“.
  - Die ca-issuer-Warnung für die Root kommt ab 365 Tagen, ihr Text zeigt auf `rotate-root`.
  - In der Server-Übersicht und im Alarm hat die Root eigene Schwellen: gelb < 365, rot < 120 Tage
    (`apps/server/app/modules/enrollment/expiry.py:23`). Alle anderen bleiben bei 30/7.
  - Das Inventar trägt `root:next`, `root:retired` und `root:cross`.

Nicht-Ziele:
- **Leck des Root-Schlüssels** (Volume plus Passphrase): Hier hilft nur eine frische Hierarchie mit Neu-Enrollment.
  Das wird dokumentiert, einen CLI-Pfad gibt es nicht. Ein Standby-Root hilft auch nicht, denn die Erneuerung
  authentisiert mit dem alten Leaf.
- Clients an Zwischenzertifikaten statt an der Root verankern, oder ein Signal „Vertrauen geändert, sofort erneuern“
  an Agent und Desktop: beides kommt als eigene Roadmap-Zeilen.
- Keine Code-Änderung an Agent, Desktop und Server-Identitätsprüfung (`apps/server/app/core/identity.py` prüft gegen
  die Ausstellerliste ohne Root). Agent und Desktop bekommen Tests, die den Vertrag festhalten.
- Kein Erzwingen der 90-Tage-Wartezeit zwischen `stage` und `switch`. Das Runbook empfiehlt sie.

## Betroffene Komponenten & Dateien
- `apps/ca-issuer/app/pki.py`: Root mit Label im CN (`build_root_ca`, `:160`), damit N einen eigenen Subject hat.
  Neu `build_cross_cert` (Subject, SPKI und SKI von N, AKI von R, `path_length=1`, Ende ≤ Ende von R). Dazu
  `ROOT_WARN_DAYS = 365`.
- `apps/ca-issuer/app/rotation.py`: die vier Übergänge von `rotate-root` neben `rotate_intermediates`. Dazu
  `_retired_after` (`:166`), das Einträge unter R neben der aktuellen Root annehmen muss.
- `apps/ca-issuer/app/storage.py`: Phase laden (`ensure_hierarchy`, `_load_retired`), `Intermediate` mit den
  weiteren vertrauten Roots. Bündel je Phase in `_provision_server_material` (`:420`), `ensure_gateway_cert` (`:499`,
  zweite fullchain) und `ensure_frps_cert` (`:537`, X im Tail). Warntext `:219`.
- `apps/ca-issuer/app/issuer.py:127`: Reihenfolge von `chain`.
- `apps/ca-issuer/app/inventory.py`: neue Zeilen.
- `apps/ca-issuer/app/cli.py`: Unterbefehl `rotate-root`, `status`, Register-Abfrage für die Sperre von `finish`.
- `apps/gateway/nginx.conf:158`: :8444 auf `gateway-enroll-fullchain.pem`. `apps/gateway/docker-entrypoint.sh:9`
  wartet auf die Datei.
- `apps/server/app/modules/enrollment/expiry.py`: Root-Schwellen.
- `apps/web/src/lib/i18n/dictionaries.ts:131`/`:451`: Text der Ampel.
- Tests: `apps/ca-issuer/tests/` (test_pki, test_rotation, test_storage, test_gateway_cert, test_frps_cert,
  test_enroll_renew, test_trust, test_inventory, test_cli), `apps/server/tests/test_certificate_expiry.py`,
  `apps/web/src/pages/Certificates.test.ts`, `apps/agent/internal/httpclient/` (Go),
  `apps/desktop/src-tauri/src/enrollment.rs` (Rust-Tests), `scripts/tests/integration_stack_test.sh`.

## Datenmodell / API / Migrationen
- **Keine Alembic-Migration.** Inventarnamen sind freie Strings (`infra_certificates.name`), die Web-Seite zeigt sie
  roh.
- **`/enroll` und `/renew`** behalten ihre Form. `chain` bekommt in den Phasen `stage` und `switch` eine weitere Root
  (Vertrag oben). Das bricht nichts: Agent und Desktop nehmen jedes Zertifikat als Anker, das letzte PEM ist in jeder
  Phase die Root, die :8444 ausliefert.
- **Neue Dateien im Volume `ca-pki`** (von `scripts/backup.sh:87` mitgesichert):
  - `root-next.crt`, `root-next.key.enc` (Phase 1).
  - `root-retired.pem`, `root-cross.pem`, `root-switch.json` (Phase 2: Zeitpunkt von `switch`, ob R aus `chain`
    fällt).
  - Im Volume `gateway-certs`: `gateway-enroll-fullchain.pem`.
- **Neue Env** für die CLI: `CA_NEXT_ROOT_PASSPHRASE_FILE`/`CA_NEXT_ROOT_PASSPHRASE` (Passphrase von N, sonst Terminal
  oder die nächste stdin-Zeile). Nach `switch` ist N die Root, ihre Passphrase gilt dann für `rotate-intermediates`.

## Externe Integrationen
- **nginx** `ssl_certificate` je `server`-Block (https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_certificate)
  und `ssl_client_certificate` mit mehreren Roots. `ssl_verify_depth 2` bleibt, weil X nur in der Server-Kette
  steht, nicht in Client-Ketten.
- **FRP v0.69.1:** `client/connector.go` baut die TLS-Config in `Open()`, `pkg/transport/tls.go` (`newCertPool`) liest
  `trustedCaFile` bei jedem Aufbau (Quelle gelesen). frpc übernimmt eine neue `ca.crt` also beim nächsten Reconnect.
  Den löst der Neustart von frps nach `switch` aus.
- **apt/GnuTLS** und Browser: siehe Risiken. Die Probe des Advisors lief mit gnutls-cli 3.8.9 als Stellvertreter für
  apt < 3.0. Ältere GnuTLS-Stände und Browser sind nicht verifiziert.

## Trade-offs & Alternativen
- **Gewählt:** Vorverteilen über `chain`, dann umschalten mit X (Kevin). Native Clients brauchen X nicht, wenn
  zwischen `stage` und `switch` 90 Tage liegen. Ohne Wartezeit tragen X und R den Rest:
  - veraltete `--ca-fp`-Werte von R,
  - nicht enrollte Agents mit R als Fallback-CA,
  - Browser, in die nur R importiert ist.
  Im Leck-Fall ist X Pflicht, weil `stage` und `switch` am selben Tag laufen.
- **Verworfen:**
  - Phasen ohne X: im Leck-Fall Neu-Enrollment aller Geräte.
  - Neues Root-Zertifikat mit demselben Schlüssel: Go und OpenSSL prüfen die Gültigkeit der Root, also muss trotzdem
    verteilt werden. Es schließt kein Leck, und der Schlüssel lebt 20 Jahre.
  - Ein neues Antwortfeld `trust`: Es hilft nur neuen Client-Versionen.
- **Sperre von `finish`** aus dem Register (Kevin) statt nach Zeit: Sie gibt `finish` frei, sobald kein altes Leaf
  mehr lebt, und braucht die DB. Ohne DB verweigert `finish`, `--force` übergeht beides.

## Risiken & Rollback
Hingenommen (Kevin 2026-11-02 mit der Wahl des Ansatzes):
- Native Clients, die zwischen `stage` und `finish` länger offline sind als ihr Leaf gilt (90 Tage), enrollen neu,
  wie heute.
- Bei `finish` brechen:
  - Browser, in die nur R importiert ist. Doku-Schritt: N nach `switch` und vor `finish` importieren; die `.p12`
    trägt keine CA.
  - nicht enrollte Agents im permissiven Modus,
  - gespeicherte `--ca-fp`-Werte von R, etwa in Ansible.
- Leck-Fall: Ein Client schließt die Lücke erst mit seiner nächsten Erneuerung (online nach höchstens etwa 45 Tagen,
  spätestens mit dem Ablauf nach 90). Wer schon im Netzpfad sitzt, kann diese Erneuerung abfangen.
- Ein Restore eines Backups von vor `switch` ist ein Rollback. Clients mit Leaves unter N müssen dann neu enrollen.
  Deshalb ein Backup nach jedem Schritt.
- Update-Reihenfolge: Das neue Gateway wartet auf `gateway-enroll-fullchain.pem`, die erst der neue ca-issuer
  schreibt. Beide kommen mit demselben Release über `docker compose`.

Rollback:
- `abort` vor `switch`.
- Nach `switch` gibt es keinen Rückweg ohne Backup, weil der Schlüssel von R gelöscht ist. Das ist gewollt: R soll
  nach dem Wechsel nichts mehr signieren können.
- Code-Rollback: Ohne `stage` ändert sich nichts an Bündeln und `chain`, nur die zweite Gateway-Datei kommt dazu.

## Doku-Impact
- `docs/admin/betrieb.html`, Abschnitt `ca-rotation` (EN `docs/en/admin/operations.html`): neuer Abschnitt
  „Root erneuern“ mit geplantem Wechsel, Leck-Fall, Root-Leck, Backup je Schritt und Browser-Import. Dort auch die
  Ampel-Schwellen (`betrieb.html:248`).
- `docs/admin/troubleshooting.html:71` (EN): Root-Import nach `switch`, veraltetes `--ca-fp`.
- `docs/admin/agent-deployment.html` (EN): `--ca-fp` ändert sich mit `switch`.
- ADR 0001: Nachtrag Root-Erneuerung.
- `changelog.d/arch-ca-root-renewal.md`.

## Offene Fragen
Keine aus Kevins Bereich. Die Session entscheidet beim Bau die Form der Wiederaufnahme eines abgebrochenen
`switch` (Zustand aus den Dateien, Test: Abbruch nach jedem Schreibschritt) und die Reihenfolge der Passphrase-Abfrage.
