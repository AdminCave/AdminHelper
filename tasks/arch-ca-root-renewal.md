<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-ca-root-renewal — Task-Ledger
Status: aktiv · Branch: feature/arch-ca-root-renewal · Review: pro Task
Spec: docs/features/arch-ca-root-renewal.md (Roadmap R-1021)
Heavy: linux-full — `apps/ca-issuer`, Gateway-Konfiguration und Server-Ampel (Sammellauf). Vor dem Merge außerdem der Stack-Job per Dispatch (`gh workflow run ci.yml --ref feature/arch-ca-root-renewal`); er fährt den Root-Wechsel aus T9. Kein `scenario`: Der Wechsel läuft in einem Stack, Agent und Desktop ändern keinen Code. Kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` je Task T1–T4 und T9 (PKI-Risikopfad), dazu `reviewer` je Task.
Reihenfolge: T1 → T2 → T3 → T4 bauen aufeinander auf. T5–T8 sind unabhängig. T9 braucht T1–T4 und den Merge von
`feature/klein-tests-stack-3` (R-1006, ändert dieselbe Datei; vorher `origin/main` hineinmergen). T10 zuletzt;
`feature/ops-5` ändert andere Abschnitte von `betrieb.html`/`operations.html`, vorher `origin/main` hineinmergen.

## Tasks

### T1 — Root-Wechsel: Zertifikate und Dateiübergänge  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/pki.py, apps/ca-issuer/app/rotation.py, apps/ca-issuer/app/root_rollover.py (neu, SPDX), apps/ca-issuer/tests/test_pki.py, apps/ca-issuer/tests/test_rotation.py, apps/ca-issuer/tests/test_root_rollover.py (neu, SPDX)
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @f5dc150d 2026-11-02T11:28:56+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T1.verdict.json)
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

### T2 — Boot lädt die Phase, `chain` nach dem neuen Vertrag  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/tests/test_storage.py, apps/ca-issuer/tests/test_enroll_renew.py, apps/ca-issuer/app/pki.py, apps/ca-issuer/app/rotation.py, apps/ca-issuer/tests/test_root_rollover.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @e6a6263b 2026-11-02T11:45:40+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T2.verdict.json)
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
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_enroll_renew.py tests/test_root_rollover.py tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: → T10

### T3 — Server-Material je Phase und Gateway :8444  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/app/trust.py, apps/gateway/nginx.conf, apps/gateway/docker-entrypoint.sh, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py, apps/ca-issuer/tests/test_trust.py, apps/ca-issuer/tests/test_storage.py, apps/server/tests/test_gateway_container.py, apps/ca-issuer/tests/renewal.py, .github/workflows/ci.yml
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @2017822a 2026-11-02T12:20:18+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T3.verdict.json)
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
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_cert.py tests/test_frps_cert.py tests/test_trust.py tests/test_storage.py
Doku: → T10

### T4 — CLI `rotate-root`, `status`, Sperre von `finish`, Warnung und Inventar  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/cli.py, apps/ca-issuer/app/config.py, apps/ca-issuer/app/pki.py, apps/ca-issuer/app/storage.py, apps/ca-issuer/app/inventory.py, apps/ca-issuer/tests/test_cli.py, apps/ca-issuer/tests/test_inventory.py, apps/ca-issuer/tests/test_config.py, apps/ca-issuer/app/rotation.py, apps/ca-issuer/tests/test_storage.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @e9eb688a 2026-11-02T12:59:51+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T4.verdict.json)
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
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_cli.py tests/test_inventory.py tests/test_config.py tests/test_storage.py
Doku: → T10

### T5 — Server: eigene Ampel-Schwellen für die Root  [x]
Komponente: server · Dateien: apps/server/app/modules/enrollment/expiry.py, apps/server/tests/test_certificate_expiry.py, apps/server/tests/test_certificate_expiry_watch.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @cd7ae11e 2026-11-02T13:25:26+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T5.verdict.json)
Änderung: Für den Namen `root` gilt gelb < 365 und rot < 120 Tage (`expiry.py:23`), alle anderen Zertifikate bleiben
bei 30/7, auch `root:retired` und `root:cross`. Der Alarm (`notify_expiring`) folgt derselben Ampel.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry.py tests/test_certificate_expiry_watch.py
Doku: → T10

### T6 — Web: Erklärtext der Ampel  [x]
Komponente: web · Dateien: apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/pages/Certificates.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @12e12554 2026-11-02T13:30:20+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T6.verdict.json)
Abhängt von: T5
Änderung: Der Text zur Ampel (`dictionaries.ts:131` DE, `:451` EN) nennt die Schwellen der Root. Der Test prüft den
Text auf der Seite.
Verify: bash scripts/dev/verify.sh web --strict -- Certificates
Doku: → T10

### T7 — Agent: Tests für den Vertrag über den Wechsel  [x]
Komponente: agent · Dateien: apps/agent/internal/httpclient/httpclient_test.go, apps/agent/internal/httpclient/cafp_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @08325205 2026-11-02T13:35:30+01:00
Review: approve (.ah-out/review/arch-ca-root-renewal/T7.verdict.json)
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
- 2026-11-02 T1: Die Übergänge (`stage_root`, `abort_root`, `switch_root`, `finish_root`) stehen in `rotation.py`,
  `root_rollover.py` liest nur die Phase — sie teilen Lock und atomares Schreiben mit `rotate_intermediates`, und
  der Boot (T2) braucht die Phase ohne den Rotationscode.
- 2026-11-02 T1: Phasen `none · staged · switching · switched · finishing` allein aus den Dateien;
  `root-switch.json` hält die Optionen des Switch, ein fortgesetzter Switch mit anderen Optionen wird verweigert —
  sonst entschiede ein zweiter Lauf still anders als der erste.
- 2026-11-02 T1: Die Passphrase von R braucht der Switch nur, solange X fehlt; ist R abgelaufen, geht nur
  `--no-cross` — ein Fortsetzen nach geschriebenem X braucht R nicht mehr, und ein abgelaufenes R signiert nichts.
- 2026-11-02 T1: `rotate_intermediates` verweigert in `switching`/`finishing`, rotiert in `staged` unter R und in
  `switched` unter N (retired behält, was unter R oder N steht); `--compromised` in `switched` schreibt
  `drop_retired_root` vor der ersten retired-Datei — ein halber Lauf lässt R sonst in `chain`.
- 2026-11-02 T1: Ein zweiter `stage` mit demselben CN wie `root.crt` (gleicher Tag) wird verweigert — Clients
  finden den Aussteller über den Namen, und R und N stehen bis `finish` nebeneinander.
- 2026-11-02 T2: `Intermediate` bekommt das Pflichtfeld `roots` (die Roots hinter dem Intermediate, `root.crt`
  zuletzt) und `trust_bundle` für `chain` aus `/enroll` und `/renew`. Das Feld `chain`, `<scope>-chain.pem` und
  `_chain_is` bleiben [I, `root.crt`]: Gateway und frps liefern das bis T3 aus, und ein Boot mitten in der
  Erneuerung prüft dieselben Dateien wie davor.
- 2026-11-02 T2: Boot und `switch` prüfen, dass N bzw. das retired R eine selbstsignierte CA ist
  (`pki.root_problem`, Nit von `security` zu T1). `root.crt` wird sonst ein Zertifikat, das keine Root ist, und
  der Schlüssel von R ist weg. `_problem` aus `rotation.py` wandert als `pki.intermediate_problem_among` nach
  `pki`, weil `storage` es für die retired-Intermediates unter R oder N braucht.
- 2026-11-02 T2: Ist R nach dem Switch abgelaufen, fällt es aus `roots` mit einer WARNING „finish“. Retired
  Intermediates unter R gelten weiter bis zu ihrem eigenen Ende, das spätestens mit R kommt.
- 2026-11-02 T2: 9 statt 8 Dateien. `pki.py`/`rotation.py`/`test_root_rollover.py` für die Root-Prüfung,
  `test_gateway_cert.py`/`test_frps_cert.py` nur für das neue Pflichtfeld in ihren `Intermediate(...)`.
- 2026-11-02 T2, fürs Runbook (T10, Nits zu T1): Bei einem Leak `switch --compromised` ohne Rotation davor
  (`rotate --compromised` in `staged` hält nichts fest). Backups von vor dem Switch tragen den Schlüssel von R
  weiter verschlüsselt. Bricht der Switch vor `root-cross.pem` ab und läuft R danach ab, hilft nur ein Restore.
- 2026-11-02 T2, Nits der Prüfer: `Verify:` nimmt alle fünf berührten Testdateien auf (reviewer). In `switched`
  nimmt der Boot ein `<scope>-retired.pem` unter R auch für einen Scope aus `--compromised` an (security). Das
  schließt T3 mit, weil T3 die Bündel je Scope ohnehin neu baut: unter R nur, was nicht `compromised` ist.
- 2026-11-02 T3: `ensure_hierarchy` liest X (`root-cross.pem`) und prüft es: Name und Schlüssel von `root.crt`,
  signiert von R, sonst bricht der Boot mit Restore-Hinweis ab. `Intermediate` trägt dazu `old_root` und `cross`,
  solange R gilt. Für einen Scope aus `compromised` zählt im `<scope>-retired.pem` nur, was N signiert hat; ein
  teilweise zurückgespieltes Intermediate unter R wird mit WARNING übersprungen (Nit von `security` zu T2).
- 2026-11-02 T3: `client-ca.pem` nimmt R nur dann auf, wenn ein gelistetes Intermediate darunter steht. nginx ist
  nicht die Grenze gegen ein ausgetauschtes Intermediate unter R: R im Bündel lässt jedes mitgeschickte durch, wie
  vor der Erneuerung. Die Grenze ist die Aussteller-Prüfung des Servers über `ca-trust/<scope>.pem` (R-1009).
- 2026-11-02 T3: `trust.py` bleibt unverändert. `write_trust` schreibt I + retired, und die retired je Phase kommen
  schon aus `ensure_hierarchy`. Die Datei bleibt in `Dateien:`, weil `set-files` nur ergänzt.
- 2026-11-02 T3: 10 Dateien statt 8: `test_storage.py` für die Prüfung von X, das neue Hilfsmodul
  `tests/renewal.py` (die Phasen über die echten Übergänge, wie `apps/server/tests/trust_ca.py`) für drei
  Testdateien, `apps/server/tests/test_gateway_container.py`, weil der Entrypoint auf die neue Datei wartet.
  `test_a_failed_bundle_write_keeps_the_old_bundle` führt `gateway-enroll-fullchain.pem` als vierte Datei, eine
  gewollte Verhaltensänderung.
- 2026-11-02 T3: Die Server-Datei steht nicht im `Verify:` (task-close fährt eine Komponente) und lief einzeln:
  `verify.sh server --strict -- tests/test_gateway_container.py` → `run.sh[quick]: 3 passed, 0 failed, 15 skipped,
  0 test-skips, 0 reruns` (pytest `12 passed`, mit Docker), exit 0.
- 2026-11-02 T3, Runde 2 (reviewer): Der CI-Job `gateway-config` legt für `nginx -t` nur Stub-Zertifikate an; ohne
  `gateway-enroll-fullchain.pem` bricht er ab (nachgestellt: rc 1 ohne, rc 0 mit der Zeile). `ci.yml` bekommt die
  Stub-Datei. Damit ändert der PR `.github/workflows/`, Kevin merged ihn (CLAUDE.md §2). Die Prüfung von X nutzt
  jetzt `pki.cross_problem` aus T1 statt einer zweiten Fassung, damit auch `path_length=1` gilt (Nit), mit eigenem
  Testfall.
- 2026-11-02 T4: Die Sperre von `finish` (Phase `switched`, ohne `--force`) fragt das Register und hält an vier
  Gründen: (1) Register unbekannt (kein `DATABASE_URL`, oder ein DB-Fehler, gemeldet nur mit dem Typ der Exception);
  (2) die letzte Start-Momentaufnahme in `infra_certificates` (`root`) ist nicht der Fingerprint von `root.crt` (N),
  der ca-issuer läuft also noch nicht unter N; (3) das Register ist jünger als R und das Legacy-Fenster
  (`tokens.LEGACY_WINDOW`) läuft noch, es kennt also eventuell nicht jedes Gerät; (4) aktive Geräte, deren jüngstes
  Zertifikat vor dem ersten Start unter N liegt (siehe „Grenze der Sperre“). Aktiv heißt: Line nicht widerrufen, Identität nach der Regel von
  `DbTokenStore._active` aktiv, jüngstes Zertifikat noch gültig. `finishing` sperrt nicht, denn der abgebrochene
  finish hat R schon aus Bündeln genommen.
- 2026-11-02 T4: Grenze der Sperre ist der erste Start unter N, nicht der switch. Bis zum Neustart signiert der
  laufende ca-issuer noch unter R. Das Inventar behält deshalb `recorded_at` einer Zeile, solange Name und
  Fingerprint gleich bleiben (für `root` also der erste Start unter N), mit der Uhr `pki._now` der Leaves; der
  Spec-Satz „vor `switch` ausgestellt“ wird damit „vor dem ersten Start unter N“ (strenger). Abgelehnt:
  `switched_at` (zählt, was der alte Prozess bis zum Neustart unter R signiert, nach dem Hinweis von security)
  und der letzte Start (jeder spätere Neustart verschöbe finish um bis zu eine Leaf-Laufzeit). `recorded_at` las
  bisher niemand; keine Migration, die Rolle hat SELECT/INSERT/DELETE.
- 2026-11-02 T4: Passphrasen. Die von N kommt aus `CA_NEXT_ROOT_PASSPHRASE_FILE`, sonst aus
  `CA_NEXT_ROOT_PASSPHRASE`, sonst vom Terminal, sonst aus der nächsten stdin-Zeile; die von R ist nie ein Ersatz.
  `stage` fragt auf dem Terminal zweimal, denn ein Tippfehler fiele erst beim switch auf. `switch` fragt zuerst R
  (nur mit Cross und solange X fehlt), dann N; auf stdin also Zeile 1 R, Zeile 2 N. Die Phase wird vor jeder
  Abfrage geprüft: `rotation.refusal` ist dafür öffentlich.
- 2026-11-02 T4: `status` zeigt in `staged` die Zeile `root (next)` und in `switched` die Zeilen `root (retired)`
  und `root (cross)`, dazu den Abschnitt `root renewal:` mit Abdeckung und nächstem Schritt. Retired-Intermediates
  werden gegen die Roots geprüft, denen auch der Boot traut. Exit 1, wenn R vor dem finish abläuft; Exit 3, wenn ein
  Schritt mittendrin abbrach oder die Phase unlesbar ist. In Phase `none` gibt es keine DB-Abfrage und die Ausgabe
  bleibt wie bisher. Das Inventar schreibt `root:next`, `root:retired` und `root:cross` über
  `root_rollover.load_state`.
- 2026-11-02 T4: 10 Dateien statt 8. `test_storage.py` kommt hinzu, weil die Root-Warnung des Boots jetzt auf
  `rotate-root` zeigt (`pki.ROOT_WARN_DAYS` = 365). `test_a_root_near_its_end_warns_that_clients_must_enroll_again`
  heißt jetzt `…_warns_to_stage_a_new_root` und prüft den neuen Hinweis: eine gewollte Verhaltensänderung.
  `rotation.py` kommt hinzu, weil `refusal` öffentlich wurde.
