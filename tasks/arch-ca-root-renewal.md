<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-ca-root-renewal — Task-Ledger
Status: geplant · Branch: feature/arch-ca-root-renewal · Review: pro Task
Spec: docs/features/arch-ca-root-renewal.md (Roadmap R-1021)
Heavy: linux-full — `apps/ca-issuer`, Gateway-Konfiguration und Server-Ampel (Sammellauf). Vor dem Merge außerdem der Stack-Job per Dispatch (`gh workflow run ci.yml --ref feature/arch-ca-root-renewal`); er fährt den Root-Wechsel aus T9. Kein `scenario`: Der Wechsel läuft in einem Stack, Agent und Desktop ändern keinen Code. Kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` je Task T1–T4 und T9 (PKI-Risikopfad), dazu `reviewer` je Task.
Reihenfolge: T1 → T2 → T3 → T4 bauen aufeinander auf. T5–T8 sind unabhängig. T9 braucht T1–T4 und den Merge von
`feature/klein-tests-stack-3` (R-1006, ändert dieselbe Datei; vorher `origin/main` hineinmergen). T10 zuletzt;
`feature/ops-5` ändert andere Abschnitte von `betrieb.html`/`operations.html`, vorher `origin/main` hineinmergen.

## Tasks

### T1 — Root-Wechsel: Zertifikate und Dateiübergänge  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/pki.py, apps/ca-issuer/app/rotation.py, apps/ca-issuer/app/root_rollover.py (neu, SPDX), apps/ca-issuer/tests/test_pki.py, apps/ca-issuer/tests/test_rotation.py, apps/ca-issuer/tests/test_root_rollover.py (neu, SPDX)
Änderung:
- `pki.py`:
  - `build_root_ca` (`:160`) bekommt ein optionales Label im CN, damit N ein eigenes Subject hat. Der CN der
    ersten Root bleibt „AdminHelper Root CA“.
  - Neu `build_cross_cert(new_root, new_key_pub, old_root, old_key)`: Subject, SPKI und SKI von N, AKI von R,
    `BasicConstraints(ca, path_length=1)`, Ende ≤ Ende von R.
- `root_rollover.py`: die Übergänge `stage`, `abort`, `switch(compromised, cross)` und `finish` als Dateioperationen
  im PKI-Verzeichnis, unter `.rotate.lock`, atomar je Datei (`rotation._replace`).
  - Schreibreihenfolge von `switch`:
    1. `root-switch.json`, `root-cross.pem`, `root-retired.pem`;
    2. je Scope retired, Key, Zertifikat und `chain` unter N;
    3. `root.crt`/`root.key.enc` ← N;
    4. `root-next.*` löschen.
  - Ein erneuter Aufruf nach einem Abbruch schließt ab.
  - Ohne X (`--no-cross`) verweigert `switch --compromised`.
- `rotation.py:_retired_after` (`:166`) nimmt in Phase 2 Einträge unter `root-retired.pem` an. `rotate_intermediates`
  läuft so in jeder Phase.
- Tests:
  - jeder Übergang mit den Dateien danach;
  - Abbruch nach jedem Schreibschritt, dann Wiederaufnahme;
  - verweigerte Übergänge (`stage` zweimal, `switch` ohne `stage`, `abort` nach `switch`, `finish` vor `switch`);
  - X mit `cryptography` gegen R und N geprüft: Pfad leaf → A(N) → X → R.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_pki.py tests/test_rotation.py tests/test_root_rollover.py
Doku: → T10

### T2 — Boot lädt die Phase, `chain` nach dem neuen Vertrag  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/tests/test_storage.py, apps/ca-issuer/tests/test_enroll_renew.py
Abhängt von: T1
Änderung:
- `ensure_hierarchy` (`storage.py:110`) erkennt Phase 0/1/2 an den Dateien.
  - Einen Zwischenstand verweigert er mit dem Hinweis, `switch` erneut aufzurufen.
  - `_load_retired` (`:255`) nimmt Zwischenzertifikate unter R an.
  - `Intermediate` trägt die weiteren vertrauten Roots. Die Prüfung `_chain_is` (`:317`) und `chain` folgen dem
    Vertrag der Spec.
  - Ist R abgelaufen, fällt R aus `chain` und der Boot warnt „finish ausstehend“.
- `issuer._sign` (`issuer.py:127`) gibt `chain` in dieser Reihenfolge zurück.
- Tests: `chain` je Phase (auch `--compromised`) aus `/enroll` und `/renew`. Das letzte PEM ist die Root, die :8444
  ausliefert. Dazu der Zwischenstand und der abgelaufene R.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_enroll_renew.py
Doku: → T10

### T3 — Server-Material je Phase und Gateway :8444  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/app/trust.py, apps/gateway/nginx.conf, apps/gateway/docker-entrypoint.sh, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py, apps/ca-issuer/tests/test_trust.py
Abhängt von: T2
Änderung:
- `_provision_server_material`/`ensure_gateway_cert`/`ensure_frps_cert` (`storage.py:420`, `:499`, `:537`) schreiben
  die Bündel aus der Tabelle der Spec:
  - `gateway-fullchain.pem` mit X und R in Phase 2;
  - neu `gateway-enroll-fullchain.pem` (in Phase 2 zusätzlich N);
  - `client-ca.pem` mit N, R und den abgelösten access-Zwischenzertifikaten;
  - frps-Leaf mit X im Tail, frps-`ca.crt` und `ca-trust` mit I(N) + I(R) ohne den kompromittierten Scope.
  - Ein Phasenwechsel stellt das Material neu aus.
- `nginx.conf:158` (:8444) nutzt die neue Datei, `docker-entrypoint.sh:9` wartet auf sie.
- Tests, tabellengetrieben je Phase. Invariante: Auf :443/:8445 steht nie N neben X.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_cert.py tests/test_frps_cert.py tests/test_trust.py
Doku: → T10

### T4 — CLI `rotate-root`, `status`, Sperre von `finish`, Warnung und Inventar  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/cli.py, apps/ca-issuer/app/config.py, apps/ca-issuer/app/pki.py, apps/ca-issuer/app/storage.py, apps/ca-issuer/app/inventory.py, apps/ca-issuer/tests/test_cli.py, apps/ca-issuer/tests/test_inventory.py, apps/ca-issuer/tests/test_config.py
Abhängt von: T3
Änderung:
- `cli.py`: Unterbefehl `rotate-root stage|abort|switch [--compromised SCOPE …] [--no-cross]|finish [--force]`.
  - Passphrasen: R wie bisher (`config.root_passphrase()`, sonst Abfrage). N aus `CA_NEXT_ROOT_PASSPHRASE_FILE`/
    `CA_NEXT_ROOT_PASSPHRASE` (`config.py`), sonst Abfrage mit Wiederholung, sonst die nächste stdin-Zeile.
  - `status` zeigt Phase, N/R/X und die Abdeckung aus `issued_certificates`/`device_lines`, ohne DB „unbekannt“.
  - `finish` verweigert bei lebenden, nicht widerrufenen Leaves von vor `switch` und ohne DB, außer mit `--force`.
- `pki.py`: `ROOT_WARN_DAYS = 365`. `storage.py:219`: Der Warntext zeigt auf `rotate-root`.
- `inventory.py`: neue Zeilen `root:next`, `root:retired`, `root:cross`.
- Tests: CLI je Unterbefehl und Passphrasen-Quelle, die Sperre gegen sqlite-Register, das Inventar je Phase.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_cli.py tests/test_inventory.py tests/test_config.py
Doku: → T10

### T5 — Server: eigene Ampel-Schwellen für die Root  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/expiry.py, apps/server/tests/test_certificate_expiry.py, apps/server/tests/test_certificate_expiry_watch.py
Änderung: Für den Namen `root` gilt gelb < 365 und rot < 120 Tage (`expiry.py:23`), alle anderen Zertifikate bleiben
bei 30/7, auch `root:retired` und `root:cross`. Der Alarm (`notify_expiring`) folgt derselben Ampel.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry.py tests/test_certificate_expiry_watch.py
Doku: → T10

### T6 — Web: Erklärtext der Ampel  [ ]
Komponente: web · Dateien: apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/pages/Certificates.test.ts
Abhängt von: T5
Änderung: Der Text zur Ampel (`dictionaries.ts:131` DE, `:451` EN) nennt die Schwellen der Root. Der Test prüft den
Text auf der Seite.
Verify: bash scripts/dev/verify.sh web --strict -- Certificates
Doku: → T10

### T7 — Agent: Tests für den Vertrag über den Wechsel  [ ]
Komponente: agent · Dateien: apps/agent/internal/httpclient/httpclient_test.go, apps/agent/internal/httpclient/cafp_test.go
Änderung: Nur Tests, kein Produktivcode.
- `NewMTLS`/`verifyGatewayIssuer` (`httpclient.go:78`, `:108`): Ein Agent mit dem Bündel aus Phase 0 oder 1
  verbindet sich gegen die Kette aus Phase 2 [leaf, A(N), X, R]. Ein Agent mit dem Bündel nach `finish` [I(N), N]
  verbindet sich ebenfalls.
- `verifyAnchorFingerprint` (`:175`): Pin auf R und Pin auf N gegen [leaf, A(N), X, R, N].
- Gegenprobe: Ein fremder Pin wird abgelehnt.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestNewMTLS|TestCAFingerprint
Doku: keine (nur Tests)

### T8 — Desktop: Tests für den Vertrag über den Wechsel  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs
Änderung: Nur Tests (rcgen), kein Produktivcode.
- `root_fingerprint_of_chain` (`enrollment.rs:374`) mit drei PEMs, Pin = letztes PEM.
- `build_mtls_client` (`:924`) mit Ankern aus Phase 1 gegen die Kette aus Phase 2 und nach `finish`.
- Gegenprobe: Anker nur R gegen die Kette nach `finish` scheitert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enroll
Doku: keine (nur Tests)

### T9 — Stack-Test fährt den Wechsel  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Abhängt von: T4
Änderung: Der Stack-Test führt im laufenden Stack `rotate-root stage` aus, dann ein Renew, dann `switch --compromised`
für einen Scope. Danach prüft er:
- Ein Client mit nur R erreicht :443.
- `gnutls-cli` mit nur N erreicht :8445.
- Der frpc-Tunnel steht nach dem Neustart von frps.
- Der Server nimmt ein altes Leaf eines nicht kompromittierten Scopes an, ein Leaf des kompromittierten Scopes
  bekommt 403.
- `finish` verweigert ohne `--force`. Nach `finish --force` wird ein altes Zertifikat abgelehnt.
Beweis über den Dispatch (Heavy).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T10

### T10 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/adr/0001-unified-pki-and-secure-deployment.md, changelog.d/arch-ca-root-renewal.md
Task-Review: am Ende
Änderung:
- `betrieb.html`/`operations.html`, Abschnitt `ca-rotation` (`betrieb.html:250`): neuer Abschnitt „Root erneuern“
  - geplanter Wechsel mit 90 Tagen zwischen `stage` und `switch`;
  - Leck eines Zwischenschlüssels, Leck des Root-Schlüssels;
  - Backup nach jedem Schritt, Browser-Import von N, `--ca-fp` erneuern;
  - Ampel-Schwellen der Root (`:248`).
- troubleshooting (`:71`): Root-Import nach `switch`, veraltetes `--ca-fp`.
- agent-deployment (`:50`, `:188`): `--ca-fp` ändert sich mit `switch`.
- ADR 0001: Nachtrag. Dazu `changelog.d/arch-ca-root-renewal.md`.
- Vorher mit `grep -rl 'Root' docs README.md DEVELOPMENT.md` nach weiteren Stellen suchen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/adr/0001-unified-pki-and-secure-deployment.md, changelog.d/arch-ca-root-renewal.md

## Entscheidungen
- 2026-11-02 Kevin:
  - Ansatz: Phasen mit Cross-Zertifikat statt Phasen ohne X, neuem Root-Zertifikat mit altem Schlüssel oder einem
    neuen Antwortfeld.
  - Vertrag: `chain` neu definieren statt eines neuen Felds `trust`.
  - `finish` sperrt nach dem Register (`--force` übergeht), nicht nach Zeit.
  - Root mit eigenen Ampel-Schwellen (365/120) und Warnung ab 365 Tagen.
- 2026-11-02 Session:
  - Dateilayout im Volume `ca-pki` und die Env `CA_NEXT_ROOT_PASSPHRASE(_FILE)` wie in der Spec.
  - N nur auf :8444 neben X, wegen GnuTLS (Probe des Advisors).
  - Agent, Desktop und Server-Identitätsprüfung ohne Code-Änderung, nur Tests.
