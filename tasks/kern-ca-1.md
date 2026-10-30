<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CA-Issuer: Startprüfung, Server-Leaves und Renew-Laufzeit — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-1 · Review: pro Task
Spec: docs/features/kern-ca-1.md (Roadmap R-0918, R-0834, R-0880, R-0912, R-0833)
Heavy: linux-full — `apps/ca-issuer` (Startprüfung der Hierarchie, Gateway-/frps-Leaf und Trust-Bundles) läuft im Sammellauf über `main` (`integration-stack`, `backup-restore`, `upgrade-path`); kein `scenario`: kein Wire-Format, kein Enrollment-Pfad und keine Agent-Seite ändert sich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben: origin/main@94aba678.

Für alle Tasks:
- Alle Tasks berühren den Risikopfad `apps/ca-issuer/*`: zusätzlich `security`.
- Neue Code-Strings englisch; bestehende deutsche Texte bleiben.
- Zertifikate im Test wie in `apps/ca-issuer/tests/test_storage.py` (Root-Passphrase fester Testwert `b"pw"`).
- Je Task ein Eintrag in `changelog.d/kern-ca-1.md` (neue Datei mit SPDX-Header in der ersten Task, die ihn braucht).

### T1 — storage: aktuelles Intermediate beim Start vollständig prüfen, lesbare Fehler  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_storage.py, changelog.d/kern-ca-1.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @159cc098 2026-10-30T01:09:19+01:00
Review: approve (.ah-out/review/kern-ca-1/T1.verdict.json)
Änderung: R-0918: `ensure_hierarchy` (`storage.py:106`) prüft das aktuelle `<scope>.crt` zusätzlich mit `pki.intermediate_problem(cert, scope, root)` wie `_load_retired` (`storage.py:247`) und bricht bei Fund mit `_invalid_hierarchy` ab. R-0834: `cert_from_pem`/`key_from_pem` für `root.crt` (`:169`), `<scope>.crt` und `<scope>.key` (`:180-181`) fangen `ValueError` und melden über `_invalid_hierarchy` Datei und Scope. Erst die roten Tests.
Beweis: R-0834 feature/ca-issuer-lifetime@7e06dfa0 apps/ca-issuer/app/storage.py ensure_hierarchy (reviewer T3) · Dedup-Key: bug:ca-issuer:storage.py:unreadable-file-error
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_rotation.py
Doku: changelog.d/kern-ca-1.md

### T2 — storage: Server-Leaf neu ausstellen, wenn sich die SANs ändern  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-ca-1.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @175bd5a3 2026-10-30T01:13:09+01:00
Review: approve (.ah-out/review/kern-ca-1/T2.verdict.json)
Änderung: R-0880: `_provision_server_material` (`storage.py:373`) vergleicht die DNS- und IP-SANs des vorhandenen Leafs als Menge mit `_classify_sans(primary, extra_sans)` (`storage.py:309`) und stellt bei Abweichung neu aus; ein unverändertes Leaf bleibt. Doku-Satz zur Neuausstellung bei geänderter `DOMAIN`/`EXTRA_SANS`.
Beweis: R-0880 feature/agent-run-ctx@f3c2b1db apps/ca-issuer/app/storage.py:212-218 (Code-Lesung) · Dedup-Key: bug:ca-issuer:storage.py:extra-sans-no-reissue
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: docs/admin/agent-deployment.html:189 · docs/en/admin/agent-deployment.html:187 · changelog.d/kern-ca-1.md

### T3 — storage: Trust-Bundles atomar schreiben  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_gateway_cert.py
Änderung: R-0912: das Trust-Bundle (`storage.py:405`) entsteht als tmp-Datei im Zielverzeichnis und ersetzt das alte mit `os.replace`; ein Fehler beim Schreiben lässt das alte Bundle unverändert. Test: ein Schreibfehler (monkeypatch) lässt das alte Bundle stehen und keine tmp-Datei zurück.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: keine (internes Schreibverhalten, kein dokumentiertes Verhalten)

### T4 — renew: Laufzeit aus der kind der Device-Line  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/issuer.py, apps/ca-issuer/app/tokens.py, apps/ca-issuer/app/db.py, apps/ca-issuer/tests/test_enroll_renew.py, apps/ca-issuer/tests/test_db_token_store.py, changelog.d/kern-ca-1.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @378a2fcd 2026-10-30T01:15:04+01:00
Review: approve (.ah-out/review/kern-ca-1/T4.verdict.json)
Änderung: R-0833: `RenewSigner` (`tokens.py:111`) bekommt die `kind` der Line; `InMemoryTokenStore.renew` (`tokens.py:254`) und `DbTokenStore.renew` (`db.py:272`, `device_lines.c.kind` mitselektieren; bei Übernahme `legacy_kind`) rufen `sign(kind)`; `issuer.py:216-221` setzt die Laufzeit `LEAF_DAYS_BROWSER` für `browser`, sonst `LEAF_DAYS_NATIVE`. Erst der rote Test: ein gekürztes Browser-Leaf einer erfassten Line erneuert mit `LEAF_DAYS_BROWSER`.
Beweis: R-0833 feature/ca-issuer-lifetime@7e06dfa0 (Prüfer-Bericht T2/T3, nicht verifiziert) · Dedup-Key: bug:ca-issuer:renew:browser-leaf-days
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_enroll_renew.py tests/test_db_token_store.py
Doku: changelog.d/kern-ca-1.md

## Entscheidungen
