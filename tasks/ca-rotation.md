<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CA-Issuer: Intermediates rotieren — Task-Ledger
Status: aktiv · Branch: feature/ca-rotation · Review: pro Task
Spec: docs/features/ca-rotation.md (Roadmap R-0667; hängt ab von R-0666, feature/ca-issuer-lifetime)
Heavy: linux-full + scenario --agents 1 --tunnel — `apps/ca-issuer` (PKI: neue Intermediates, Trust-Bundles alt+neu, Re-Mint der Server-Leaves, `/renew` über retired Intermediates), `apps/gateway/nginx.conf` und der Entrypoint des ca-issuer laufen im Sammellauf über `main` (`integration-stack` mit dem Rotationsschritt aus T9, `backup-restore`, `upgrade-path` vom letzten Release); auf PRs läuft der Stack-Job nicht, daher vor dem Merge `gh workflow run ci.yml --ref feature/ca-rotation`. `scenario` vor dem Merge (ask-first): mit T7 präsentiert das Gateway auf `:443`, `:8444` und `:8445` eine Kette mit Root, die ein Agent auf einem zweiten Host über `--ca-fp`, mTLS, das Repo und den frpc-Tunnel prüft. Kein `windows`: der Agent bleibt unverändert, die Desktop-Änderung (T8) ist plattformunabhängige PEM-Auswahl ohne Keyring- oder Pfad-Änderung
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Ein Befehl stellt unter derselben Root neue Intermediates für alle drei Scopes aus und legt die alten als
„retired“ ab; er geht auch bei gestopptem Issuer. (2) Nach dem Neustart signiert der Issuer neu, erneuert aber auch
Leaves der retired Intermediates; Gateway- und frps-Bundles tragen alt und neu, bis das alte abläuft; die Server-Leaves
werden unter dem neuen Intermediate neu ausgestellt. (3) `--ca-fp` wird der Root-Fingerprint (Kevin 2026-10-22).
Zeilenangaben: origin/main@e2304a8b; vor dem Bau `origin/main` mit R-0666 hineinmergen und neu greppen.

Für alle Tasks:
- **Start erst nach dem Merge von R-0666** (`feature/ca-issuer-lifetime`): T1–T6 nutzen `pki.IssuerNotValid`,
  `pki.days_left`, `pki.EXPIRY_WARN_DAYS`, die Begrenzung in `sign_leaf`/`build_intermediate_ca` und die Prüfung der
  Hierarchie in `ensure_hierarchy` aus R-0666. Vor T1 `git merge origin/main` im Worktree.
- Reihenfolge: T1 → T2 → T3 → T4 (T2 und T3 brauchen `Intermediate.retired` aus T1; T4 schreibt das Format, das T1
  liest); T5 nach T4; T6 nach T5; T7 unabhängig von T1–T6; T8 nach T7; T9 nach T5 (und T7, falls gebaut); T10 nach T5.
- T1–T8 berühren Risikopfade (`apps/ca-issuer/*`, `apps/gateway/*`, `apps/desktop/src-tauri/src/enrollment.rs`):
  zusätzlich `security`.
- Neue Code-Strings (Ausgaben, Log-Zeilen, Fehlertexte) englisch; bestehende deutsche Texte bleiben.
- Zertifikate mit wenig oder ohne Restlaufzeit entstehen im Test über `monkeypatch.setattr(pki, "_now", …)` beim
  Bauen, wie in R-0666; die Root-Passphrase im Test ist ein fester Testwert (`b"pw"` wie
  `apps/ca-issuer/tests/test_storage.py:37`), nie aus der Umgebung.
- Die bestehenden Tests in `apps/ca-issuer/tests/` bleiben unverändert grün; `Intermediate(...)` mit vier
  Positionsargumenten (`apps/ca-issuer/tests/test_gateway_cert.py:23`, `test_frps_cert.py:66-67`) bleibt gültig
  (`retired` hat einen Default).

### T1 — storage: retired Intermediates mit der Hierarchie laden  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_storage.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @8ef85f36 2026-10-23T19:58:04+02:00
Review: approve (.ah-out/review/ca-rotation/T1.verdict.json)
Änderung: `Intermediate` (`apps/ca-issuer/app/storage.py:59-64`) bekommt `retired: tuple[x509.Certificate, ...] = ()`. `ensure_hierarchy` (`:85-138`) liest je Scope die optionale Datei `<scope>-retired.pem` (`x509.load_pem_x509_certificates`): jedes Zertifikat muss von `root.crt` signiert sein (sonst `RuntimeError` wie die Prüfungen aus R-0666, Text nennt Datei und Scope); abgelaufene werden übersprungen (eine INFO-Zeile je Zertifikat mit CN und `notAfter`), eins, das DER-gleich dem aktuellen ist, ebenso; die übrigen gehen in `retired`, neuestes zuerst. Der Docstring des Moduls (`:7-14`) nennt die Datei im Layout und sagt, dass sie nur Zertifikate enthält. Tests in `test_storage.py`: (a) Hierarchie ohne retired-Datei → `retired == ()` für jeden Scope (heutiges Verhalten); (b) `access-retired.pem` mit einem gültigen und einem abgelaufenen, von der Root signierten Intermediate → `retired` enthält genau das gültige; (c) ein Zertifikat einer fremden Root in `tunnel-retired.pem` → `RuntimeError`, Text nennt `tunnel-retired.pem`; (d) das aktuelle Intermediate zusätzlich in der retired-Datei → nicht in `retired`. Zuerst rot: (b), (c), (d).
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: keine (intern; die Betreiber-Doku kommt mit T10)
Orakel: contract — `retired` enthält genau die gültigen, von der Root signierten, nicht aktuellen Zertifikate der Datei
Dedup-Key: feat:ca-issuer:storage.py:retired-intermediates
HEAD: e2304a8b

### T2 — storage: Trust-Bundles mit alt und neu, Re-Mint unter dem aktuellen Intermediate  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @d7043440 2026-10-23T20:09:02+02:00
Review: approve (.ah-out/review/ca-rotation/T2.verdict.json)
Änderung: In `_provision_server_material` (`apps/ca-issuer/app/storage.py:182-225`): (1) das Bundle (`:203-204`) ist `inter.chain` + `inter.retired` + für jedes `extra_trust` dessen Zertifikat und dessen `retired`, so tragen `client-ca.pem` (Gateway) und `ca.crt` (frps) die retired Intermediates, bis sie ablaufen; (2) die Bedingung zum Behalten des Leafs (`:212-217`) verlangt zusätzlich, dass das Leaf vom aktuellen Intermediate signiert ist (`leaf.verify_directly_issued_by(inter.cert)`; `ValueError`, `TypeError`, `InvalidSignature` → neu ausstellen), so stellt der erste Start nach einer Rotation die Leaves von Gateway und frps unter dem neuen Intermediate aus. Der Kommentar `:208-211` und die Docstrings von `ensure_gateway_cert`/`ensure_frps_cert` (`:228-287`) nennen beides. Tests: `test_gateway_cert.py` — (a) `access` mit einem retired Intermediate → `client-ca.pem` enthält aktuelles, Root und retired; ein Leaf nur des retired (ohne Kette) lässt sich gegen ein Intermediate der Datei prüfen; (b) vorhandenes, frisches Leaf eines anderen (retired) Intermediates → neu ausgestellt, das neue Leaf `verify_directly_issued_by(access.cert)`; (c) vorhandenes, frisches Leaf des aktuellen Intermediates → bleibt (Schlüssel unverändert, wie `test_idempotent_keeps_existing_leaf_key`, `:94-103`). `test_frps_cert.py` — (d) `tunnel` und `extra_trust=(access,)` je mit retired → `ca.crt` enthält beide aktuellen, beide retired und die Root; (e) wie (b) für `frps.crt`. Zuerst rot: (a), (b), (d), (e). `test_client_ca_is_the_access_trust_bundle` (`test_gateway_cert.py:71-80`) und `test_ca_is_the_tunnel_trust_bundle` (`test_frps_cert.py:51-57`) bleiben grün (ohne retired ist das Bundle unverändert).
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: keine (intern; T10)
Abhängt von: T1
Orakel: contract — jedes gültige Intermediate eines Scopes (aktuell oder retired) steht im Bundle; das ausgelieferte Server-Leaf stammt vom aktuellen
Dedup-Key: feat:ca-issuer:storage.py:bundles-old-and-new
HEAD: e2304a8b

### T3 — Issuer: /renew akzeptiert Leaves eines retired Intermediates des eigenen Scopes  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/issuer.py, apps/ca-issuer/tests/test_enroll_renew.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @f79e88f2 2026-10-23T20:32:15+02:00
Review: approve (.ah-out/review/ca-rotation/T3.verdict.json)
Änderung: `_verify_ca_signed` (`apps/ca-issuer/app/issuer.py:46-75`) prüft die Signatur gegen das aktuelle Intermediate des Scopes und, wenn das scheitert, gegen jedes aus `inter.retired`; passt keins, bleibt der bisherige Fehler. Nur Intermediates des eigenen Scopes zählen (die Regel aus `:51-54` bleibt); die Zeitprüfung des Leafs (`:55-57`) bleibt. Signiert wird immer mit dem aktuellen (`_sign`, `:77-90`). Der Docstring nennt die retired Intermediates. Tests in `test_enroll_renew.py` (`register_client`, Issuer mit selbst gebauten Intermediates wie in R-0666): (a) ein registriertes Leaf eines retired `access`-Intermediates erneuert, das neue Leaf `verify_directly_issued_by` das aktuelle; (b) ein Leaf eines retired `tunnel`-Intermediates mit OU `access` → 403 (wie `test_a_leaf_signed_by_another_scopes_intermediate_does_not_renew`, `:658-670`); (c) ein Leaf eines Intermediates, das weder aktuell noch retired ist → 403. Zuerst rot: (a).
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_enroll_renew.py
Doku: keine (intern; T10)
Abhängt von: T1
Beweis: origin/main@e2304a8b · Code-Lesung `apps/ca-issuer/app/issuer.py:58-66`: `/renew` prüft nur gegen `self._inter.get(scope)`, `storage.py:132-137` lädt genau ein Intermediate je Scope — nach einer Rotation erneuert kein Leaf des alten
Orakel: contract — ein Leaf erneuert genau dann, wenn ein gültiges (aktuelles oder retired) Intermediate seines Scopes es signiert hat
Dedup-Key: feat:ca-issuer:issuer.py:renew-via-retired
HEAD: e2304a8b

### T4 — Rotation: neue Intermediates unter der Root, alte als retired  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/rotation.py, apps/ca-issuer/app/pki.py, apps/ca-issuer/tests/test_rotation.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @6a6ed8fa 2026-10-23T20:40:33+02:00
Review: approve (.ah-out/review/ca-rotation/T4.verdict.json)
Änderung: Neues Modul `apps/ca-issuer/app/rotation.py` (SPDX-Header wie `apps/ca-issuer/app/pki.py:1-3`) mit `RotationError(Exception)` und `rotate_intermediates(pki_dir: Path, passphrase: bytes) -> list[RotatedScope]` (Dataclass: Scope, altes und neues Zertifikat). Ablauf: (1) Sperre `pki_dir/.rotate.lock` per `fcntl.flock(LOCK_EX | LOCK_NB)`, belegt → `RotationError("another rotation is running")`; (2) `root.crt` laden, `root.key.enc` mit der Passphrase entschlüsseln (`pki.key_from_pem`; jede Exception dort → `RotationError("wrong passphrase or unreadable root key")`), öffentlicher Schlüssel gleich dem von `root.crt`, Root zeitlich gültig — sonst `RotationError`, alles vor dem ersten Schreibzugriff; (3) je Scope in `pki.SCOPES`: vom aktuellen Paar nur `<scope>.crt` lesen (nicht den Schlüssel; ein Abbruch eines früheren Laufs zwischen Schlüssel und Zertifikat wird so repariert); ist es von der Root signiert und gültig, kommt es in die retired-Liste, abgelaufene Einträge der bestehenden `<scope>-retired.pem` fallen weg, Duplikate (DER) auch; neues Paar per `pki.build_intermediate_ca(scope, root_cert, root_key, label=<UTC-Datum YYYY-MM-DD>)`; schreiben in dieser Reihenfolge, jeweils Temp-Datei im selben Verzeichnis + `fsync` + `os.replace`, am Ende `fsync` des Verzeichnisses: `<scope>-retired.pem`, `<scope>.key` (0600, wie `storage._write_private`, `apps/ca-issuer/app/storage.py:67-82`), `<scope>.crt`, `<scope>-chain.pem` (`pki.chain_pem(new, root)`). In `pki.py`: `build_intermediate_ca(..., label: str | None = None)` hängt `label` an den CN an (`AdminHelper Access Intermediate 2031-05-04`; ohne `label` wie bisher, `:156`). Kommentar im Modul: warum der alte Schlüssel nicht aufgehoben wird und warum die Reihenfolge. Tests in der neuen `apps/ca-issuer/tests/test_rotation.py` (SPDX-Header): (a) nach `rotate_intermediates(d, b"pw")` lädt `storage.ensure_hierarchy(d, None)` je Scope ein neues Intermediate (anderer öffentlicher Schlüssel, CN mit Datum) und das alte in `retired`; ein Leaf des alten wird gegen `retired` geprüft, ein neues per `sign_leaf` gegen das aktuelle; (b) `notAfter` des neuen ≤ `notAfter` der Root (Root mit 100 Tagen Restlaufzeit); (c) falsche Passphrase → `RotationError`, alle Dateien in `d` byte-gleich vorher/nachher (Hash-Vergleich), keine Temp-Dateien; (d) `root.crt` einer anderen Root → `RotationError`, nichts geschrieben; (e) zwei Rotationen → `retired` enthält beide Vorgänger; ein inzwischen abgelaufener Vorgänger fällt bei der zweiten aus der Datei; (f) Sperre von einem zweiten Dateideskriptor gehalten → `RotationError`; (g) Abbruch nach dem Schlüssel (das Schreiben von `<scope>.crt` per monkeypatch scheitern lassen) → `ensure_hierarchy` bricht ab (R-0666), ein zweiter Lauf → `ensure_hierarchy` lädt, das ursprüngliche Intermediate steht in `retired`; (h) `<scope>.key` hat 0600; (i) aktuelles Intermediate abgelaufen (der Fall, in dem der Issuer nicht startet) → Rotation gelingt, das abgelaufene steht nicht in `retired`. Zuerst rot: das Modul fehlt auf HEAD.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_rotation.py tests/test_pki.py tests/test_storage.py
Doku: keine (intern; T5 bringt den Befehl, T10 die Betreiber-Doku)
Abhängt von: T1
Beweis: origin/main@e2304a8b · Code-Lesung: kein Aufrufer von `build_intermediate_ca` außer dem First Boot (`apps/ca-issuer/app/storage.py:125-129`), obwohl `storage.py:13-14`, `scripts/backup.sh:18-20`, `:112-114` und `docs/admin/betrieb.html:96` die Rotation nennen
Orakel: contract — nach einer Rotation lädt die Hierarchie mit neuen Intermediates, alle zuvor gültigen bleiben als retired prüfbar; ein Fehler vor dem Schreiben ändert nichts
Dedup-Key: feat:ca-issuer:pki.py:intermediate-rotation
HEAD: e2304a8b

### T5 — Befehl im Image: `python -m app.cli status` und `rotate-intermediates`  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/cli.py, apps/ca-issuer/tests/test_cli.py, apps/ca-issuer/docker-entrypoint.sh, CHANGELOG.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @ec8eeb54 2026-10-23T20:57:50+02:00
Review: approve (.ah-out/review/ca-rotation/T5.verdict.json)
Änderung (Kevin 2026-10-22: Befehl im Image, wie Spec Trade-off 1 und 2): Neues Modul `apps/ca-issuer/app/cli.py` (SPDX-Header) mit `argparse` und `main(argv=None) -> int`, Aufruf `python -m app.cli` (wie `python -m app.cli` im server, `scripts/tests/integration_stack_test.sh:54`). `status`: liest `root.crt`, je Scope `<scope>.crt` und `<scope>-retired.pem` aus `config.pki_dir()` (ohne Schlüssel, ohne Passphrase) und gibt je Zertifikat eine Zeile aus: Rolle (`root`, `<scope>`, `<scope> (retired)`), CN, `notAfter` (UTC, ISO), Resttage (`pki.days_left`); Exit 0, wenn Root und alle aktuellen Intermediates mehr als `pki.EXPIRY_WARN_DAYS` Tage haben, 1 bei einer Warnung, 3, wenn eins abgelaufen oder nicht lesbar ist (2 bleibt argparse). `rotate-intermediates`: Passphrase aus `config.root_passphrase()` (ein `OSError` dort → Exit 1 mit Meldung), ist sie leer und stdin ein Terminal: `getpass.getpass()`, sonst die erste Zeile von stdin ohne Zeilenende; leer → Exit 1 „no passphrase“. Dann `rotation.rotate_intermediates`; Ausgabe je Scope alter und neuer CN mit `notAfter`, danach die nächsten Schritte: „restart: docker compose restart ca-issuer gateway (frps follows by itself)“. `RotationError` → Exit 1 mit der Meldung, ohne Traceback. `apps/ca-issuer/docker-entrypoint.sh`: nach dem Wechsel auf `app` (`:8-13`) `exec "$@"`, wenn Argumente da sind, sonst wie bisher uvicorn (`:17`); Kommentar: `docker compose run … ca-issuer python -m app.cli …` läuft so als `app` und auch, wenn der Dienst nicht startet. Tests in der neuen `apps/ca-issuer/tests/test_cli.py` (SPDX-Header; `CA_DATA_DIR` auf `tmp_path` per `monkeypatch.setenv`, Hierarchie per `ensure_hierarchy`, `capsys`): (a) `status` frisch → Exit 0, vier Zeilen (Root + drei aktuelle, keine retired), jede mit CN und Datum; (b) ein Intermediate mit 30 Tagen → Exit 1; abgelaufen → Exit 3; (c) `rotate-intermediates` mit `CA_ROOT_PASSPHRASE_FILE` auf eine Datei mit `pw` → Exit 0, Ausgabe nennt alle drei Scopes und `docker compose restart ca-issuer gateway`, danach `status` mit drei retired; (d) ohne Passphrase in der Umgebung, stdin `pw\n` (kein Terminal) → Exit 0; (e) stdin leer → Exit 1, „no passphrase“, Dateien unverändert; (f) falsche Passphrase → Exit 1, keine Zeile mit „Traceback“, Dateien unverändert. Der Entrypoint hat keinen eigenen Test (Container-Wiring: `chown` und `gosu` laufen nur als root im Container); T9 fährt ihn im Stack. Zuerst rot: das Modul fehlt auf HEAD.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_cli.py
Doku: CHANGELOG.md (Added, umlautfrei: `python -m app.cli status` zeigt Ablaufdaten von Root und Zwischenzertifikaten, `rotate-intermediates` stellt neue Zwischenzertifikate unter derselben Root aus; Ablauf in Betrieb (DE+EN)) · Betreiber-Doku in T10
Abhängt von: T4
Dedup-Key: feat:ca-issuer:cli.py:rotate-command
HEAD: e2304a8b

### T6 — Meldungen nennen den Rotationsbefehl  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/tests/test_storage.py, apps/ca-issuer/tests/test_enroll_renew.py
Änderung: Die Ablaufwarnungen aus R-0666 (beim Start in `ensure_hierarchy`, beim Signieren in `Issuer._sign`), der Startabbruch bei einem abgelaufenen oder noch nicht gültigen Intermediate und der `detail`-Text der 503 hängen den Befehl aus T5 an: „rotate with: docker compose run --rm --no-deps ca-issuer python -m app.cli rotate-intermediates“ (eine Konstante, an einer Stelle definiert). Die Root-Warnung nennt ihn nicht (eine Root-Erneuerung kann der Befehl nicht). Die Tests aus R-0666 zu diesen Meldungen (`test_storage.py`, `test_enroll_renew.py`) prüfen zusätzlich, dass der Text `app.cli rotate-intermediates` enthält; für die Root-Warnung, dass er es nicht enthält. Zuerst rot: die neuen Asserts.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_enroll_renew.py
Doku: keine (die Meldungen beschreibt T10)
Abhängt von: T5
HEAD: e2304a8b

### T7 — Gateway präsentiert die Root mit; `--ca-fp` kann die Root pinnen  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py, apps/gateway/nginx.conf, CHANGELOG.md
Änderung (Empfehlung, Spec Trade-off 6): `ensure_gateway_cert` (`apps/ca-issuer/app/storage.py:228-252`) schreibt `gateway-fullchain.pem` als Leaf + access-Intermediate + Root (nginx: „the primary certificate comes first, then the intermediate certificates“); frps bleibt Leaf + tunnel-Intermediate. Umsetzung über einen Parameter von `_provision_server_material` (`:182-225`, Fullchain `:222-223`), den nur der Gateway-Aufruf setzt; Docstring `:231-242` nennt die Root und warum (`--ca-fp` kann die Root pinnen, `apps/agent/internal/httpclient/httpclient.go:145-188` sucht den Fingerprint in jeder präsentierten Kette). Eine bestehende Fullchain ohne Root wird beim nächsten Start neu ausgestellt (Bedingung zum Behalten `:212-217`: Fullchain endet mit der Root). Kommentar `apps/gateway/nginx.conf:87` („access leaf + intermediate“) → „access leaf + intermediate + root“, sonst nichts an nginx.conf. Tests in `test_gateway_cert.py`: (a) die Fullchain hat drei Zertifikate, das dritte ist DER-gleich `root.crt`, `test_provisions_three_files_and_chains_to_root` (`:48-68`) bleibt grün; (b) eine vorhandene, frische Fullchain ohne Root → neu geschrieben, jetzt mit Root. In `test_frps_cert.py`: (c) `frps.crt` hat genau zwei Zertifikate (Leaf + tunnel-Intermediate, `test_provisions_serverauth_leaf_under_tunnel`, `:25-47`, um diesen Assert ergänzt). Zuerst rot: (a), (b); (c) ist auf HEAD grün und hält fest, dass nur das Gateway die Root mitschickt.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: CHANGELOG.md (Changed, umlautfrei: das Gateway sendet die Root der internen CA in seiner Zertifikatskette mit) · Agent-Doku mit T8
HEAD: e2304a8b

### T8 — Desktop: der CA-Fingerprint für `--ca-fp` ist der der Root  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Änderung (Empfehlung): `pinned_ca_fingerprint` (`apps/desktop/src-tauri/src/enrollment.rs:256-264`) liefert den SHA-256 des **letzten** Zertifikats von `enroll|ca` (die Root; die Kette ist Intermediate + Root, `apps/ca-issuer/app/issuer.py:88-89`) über einen neuen Helfer neben `ca_fingerprint_of_chain` (`:266-275`), der unverändert bleibt (`leaf_fingerprint`, `:276-277`, nutzt ihn für das erste Zertifikat). Doc-Kommentar `:256-261`: die Root, weil sie jede Intermediate-Rotation überlebt; das Gateway präsentiert sie seit T7. `ca_fingerprint_is_the_first_chain_cert` (`:1201-1222`) bleibt mit seinen Asserts (er prüft den Helfer), sein Kommentar `:1205-1207` wird richtiggestellt; neuer Test daneben: `pinned`-Helfer auf `inter.pem() + root.pem()` → Fingerprint der Root, nicht des Intermediates; Kette mit nur einem Zertifikat → dessen Fingerprint; kein PEM → `None`. Kommentar `apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:26` („access intermediate“ → Root der internen CA), sonst nichts an der UI. Zuerst rot: der neue Test.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enrollment
Doku: `docs/admin/agent-deployment.html:187` + `docs/en/admin/agent-deployment.html:186`: der Wert im Provisionierungs-Tab ist der Fingerprint der Root der internen CA und bleibt über eine Rotation der Zwischenzertifikate gültig; ältere Befehle mit dem Fingerprint des Zwischenzertifikats gelten bis zur nächsten Rotation; Desktop und Server zusammen aktualisieren (ein neuer Desktop gegen einen Server ohne Root in der Kette scheitert mit der Fingerprint-Meldung) · CHANGELOG.md (Changed, umlautfrei)
Abhängt von: T7
HEAD: e2304a8b

### T9 — Stack-Prüfung: Rotation im laufenden Stack  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Änderung: Neuer letzter Schritt vor der Summary (`scripts/tests/integration_stack_test.sh:756`; Nummer nach dem letzten Schritt auf `main` zur Bauzeit), weil er die Hierarchie für alle folgenden Schritte ändert. Ablauf: `e2e_dc run --rm --no-deps -T ca-issuer python -m app.cli status` (Exit 0); `e2e_dc run --rm --no-deps -T ca-issuer python -m app.cli rotate-intermediates` mit der Passphrase des Test-Stacks (`scripts/tests/lib_e2e_stack.sh:233`; über Secret-Datei, falls compose-hardening gemergt ist, sonst auf stdin) → Exit 0; `e2e_dc restart ca-issuer`, warten bis healthy, `e2e_dc restart gateway`. Danach: (a) `status` listet drei retired; (b) das Leaf, das das Gateway auf `:443` präsentiert (`openssl s_client -showcerts`), hat als Issuer-CN ein Intermediate mit dem Datum des Laufs (mit T7 zusätzlich: drittes Zertifikat = Root); (c) das vor der Rotation enrollte Client-Zertifikat erreicht die API über `:443` mit Fullchain **und** nur mit dem Leaf (Leaf-only wie ein Browser-`.p12`: geht nur, weil `client-ca.pem` das retired Intermediate trägt); (d) `/ca/renew` mit dem alten Zertifikat → ok, das neue Leaf stammt vom neuen Intermediate; (e) eine frische Enrollment → Leaf vom neuen Intermediate, erreicht die API; (f) `ca.crt` im frps-Volume (`e2e_dc exec -T ca-issuer cat /app/frps-certs/ca.crt`) enthält altes und neues tunnel-Intermediate. Gegenprobe im Commit-Body (einmal lokal, nicht im Skript): ohne `e2e_dc restart gateway` scheitert (b), weil das Gateway noch das Leaf des alten Intermediates zeigt — die Prüfung kann fallen. Den echten Lauf fährt die Session (Dispatch des `integration-stack`-Jobs auf dem Branch oder `/test` in der Lane); seine Summary-Zeile kommt in den PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T5
HEAD: e2304a8b

### T10 — Doku: Zwischenzertifikate rotieren (Betrieb, DE+EN)  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html
Änderung: Neuer Abschnitt `<h2 id="ca-rotation">` nach „Zertifikate erneuern“ (`docs/admin/betrieb.html:172-173`, EN `docs/en/admin/operations.html:130-131`): wann (Warnung im Log ab 180 Tagen, `status`; spätestens wenn der `ca-issuer` wegen abgelaufener Zwischenzertifikate nicht startet), vorher `scripts/backup.sh`; die Befehle (`docker compose run --rm --no-deps ca-issuer python -m app.cli status`, `… rotate-intermediates` mit Passphrase-Abfrage oder aus der Secret-Datei, `docker compose restart ca-issuer gateway`); was passiert (neue Zwischenzertifikate unter derselben Root, alte bleiben bis zu ihrem Ablauf vertraut, Agenten und Desktops erneuern bei halber Laufzeit auf die neuen, Browser-Zertifikate gelten bis zu ihrem Ablauf, Gateway- und frps-Zertifikat neu ausgestellt, frps startet selbst neu, Tunnel kurz unterbrochen); was nicht (keine Root-Erneuerung, kein sofortiger Entzug bei einem Leck; ein Desktop mit TOFU-Pin vor dem Enrollment bestätigt neu; mit T7/T8 bleibt `--ca-fp` gültig, sonst: neuen Wert nach der nächsten Erneuerung des Desktops). Im Abschnitt „Zertifikate erneuern“: „ein Redeploy/Neustart des `ca-issuer` erneuert es bei Bedarf“ → der `ca-issuer` stellt es beim Start bei Bedarf neu aus, das Gateway lädt es mit seinem eigenen Neustart; „Die FRP-Client-Zertifikate laufen nach 12 Monaten ab“ → Agent-Zertifikate gelten 90 Tage und erneuern sich bei halber Laufzeit selbst (`apps/ca-issuer/app/pki.py:38`, `apps/agent/internal/enroll/renew.go:18-21`). Passphrase-Callout (`betrieb.html:96`, EN `:63`): Link auf `#ca-rotation`. Der builder fährt zusätzlich `python3 scripts/dev/doc-smoke.py --paths --env --strict` (Exit 0, Ergebnis in den Commit-Body).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; CHANGELOG trägt T5
Abhängt von: T5
Semantik: Soll ist der Ablauf nach T5 und T2; die heutige Doku verspricht die Rotation schon (`docs/admin/betrieb.html:96` — „gebraucht wird sie nur zum Rotieren der Intermediates“, EN `docs/en/admin/operations.html:63`) und nennt beim Gateway-Zertifikat den falschen Neustart (`betrieb.html:173` — „ein Redeploy/Neustart des <code>ca-issuer</code> erneuert es bei Bedarf“; das Gateway lädt Dateien nur beim Start, `apps/gateway/docker-entrypoint.sh:57`)
HEAD: e2304a8b
