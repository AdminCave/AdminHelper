<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Prüfungen: die Rennen-Tests des Issuers gegen Postgres, der frpc-Sync im Multibox — Task-Ledger
Status: erledigt · Branch: harness/harness-checks · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0309, R-0315, Triage Kevin 2026-10-12; der Postgres-Service im CA-Issuer-Job bleibt draussen und geht als eigene Zeile an Kevin; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0309, R-0315 (Kurz-Ledger ohne Spec)
Heavy: linux-full + scenario --enforce --agents 1 --tunnel — T1: `run.sh integration` fährt `stack_pytest.sh` (Schritt `stack-pytest`) gegen das Postgres des Stacks; T2: ein Multibox-Lauf, `--tunnel`, weil die Route ohne FRP-Config mit 404 antwortet, und `--enforce`, weil erst dann ein gelungener Sync das Agent-Zertifikat beweist.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku DE+EN im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat beide Zeilen am 2026-10-12
angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@9a512413. Disjunkt zu `scripts/dev/lane.sh`, `scripts/vm/lib.sh`, `scripts/vm/vm.py`,
`scripts/vm/warm.sh` und `scripts/dev/session-status.sh`; keine Task berührt sie. `scripts/tests/multibox.sh`
steht in `scripts/dev/harness-paths.txt`.

**Was die CI mit Postgres fährt (R-0309, geprüft):**
- **Server:** `pg_engine` (`apps/server/tests/conftest.py:119-157`) skippt nie. Es nimmt `DATABASE_URL` oder
  startet einen Testcontainer, und die Server-Jobs haben einen Postgres-Service (`.github/workflows/ci.yml:38-68`).
  Lauf auf main@9a512413 (CI 38301964664), alle drei Server-Jobs: `1022 passed`, ohne Skip. Damit laufen die
  Rennen-Tests aus R-0292 (`test_identity_revocation.py:315`), R-0306 (`:345`) und R-0311 (`test_provisioning.py`,
  zwei Tests) in jedem PR gegen Postgres, ebenso der aus R-0322 nach dem Merge von product-followups-3.
- **CA-Issuer:** Der Job `CA-Issuer (pytest)` (`ci.yml:150-169`) hat keinen Datenbank-Service und kein
  `AH_TEST_DB` (`:168`: „Tests opt into the in-memory token store … no DB service needed“). Derselbe CI-Lauf:
  `106 passed, 6 skipped`. Lokal unter denselben Bedingungen (ohne `AH_TEST_DB`, `-rs`) sind die sechs genau die
  `pg_engine`-Tests in `apps/ca-issuer/tests/test_db_token_store.py` (`:118`, `:157`, `:202`, `:294`, `:323`, `:402`).
  `stack_pytest.sh` führt die ersten drei (`:100-109`). Die Tests aus R-0292 (`:294`, `:323`) und R-0306 (`:402`)
  laufen nirgends gegen Postgres als bei einem Lauf mit `AH_TEST_DB` von Hand.

### T1 — stack_pytest: die drei Postgres-Tests des Issuers, die bisher nirgends laufen (R-0309)  [x]
Komponente: scripts · Dateien: scripts/tests/stack_pytest.sh, scripts/tests/stack_pytest_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dfa75ec0 2026-10-12T23:40:24+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `stack_pytest.sh` bekommt nach `:109` drei `stack_test`-Einträge (ca-issuer, `AH_TEST_DB=$ITEST_DATABASE_URL`,
  wie `:100-109`), mit einem Kommentar zur Sperre der Identität (R-0292, R-0306):
  - `test_db_token_store.py::test_a_renewal_that_takes_over_waits_for_a_revocation_and_is_refused`
  - `test_db_token_store.py::test_a_revocation_waits_for_a_renewal_that_takes_over_and_covers_its_line`
  - `test_db_token_store.py::test_an_enrollment_waits_for_a_revocation_and_enrolls_nothing`
- Der Kopfkommentar (`:6-12`, „the four tests“, vier Zeilen bei heute sechs Tests) und `:28` („0 all four
  passed“) nennen keine Zahl mehr. Der Kopf führt die Tests je Komponente auf.
- `stack_pytest_test.sh`: Im grünen Fall (`:84-91`) werden aus 6 Tests 9, und die Schleife über die XML-Dateien
  nennt die drei neuen Namen. Im Skip-Fall (`:130-133`) wird `5 passed, 1 failed (server-redis)` zu `8 passed`.
  Die Zeilen sind `grep … && ok`, keine Assertion im Sinn von `diff-scan`.
- Die Doku nennt dieselbe Liste ohne Zahl:
  - `docs/developer/cicd.html:117-131`, „Vier Tests brauchen einen echten Dienst … der TOCTOU-Test in
    `test_db_token_store`“, und EN `:115-129` ebenso. Künftig: die Postgres-Tests in `test_db_token_store` des
    Issuers (TOCTOU beim Einlösen, die Zeilensperren des Registers, die Sperre der Identität).
  - Der Satz zum PR-CI bleibt sinngemäß: Diese Tests fährt das PR-CI nicht mit Postgres, mit echtem Postgres
    laufen sie nur hier.
  - `DEVELOPMENT.md:1580-1583` ebenso.
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --paths --env --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html · DEVELOPMENT.md
Beweis: origin/main@9a512413:
- CI 38301964664, Job `CA-Issuer (pytest)`: `106 passed, 6 skipped`.
- Lokal mit `env -u AH_TEST_DB -u DATABASE_URL python -m pytest -q -rs -m "not schemathesis"` in `apps/ca-issuer`:
  `106 passed, 6 skipped`; `SKIPPED` an `test_db_token_store.py:118, :157, :202, :294, :323, :402`.
- `grep -n '^stack_test ca-issuer' scripts/tests/stack_pytest.sh` → drei Einträge (`:100`, `:104`, `:107`), die Tests
  `:118`, `:157`, `:202`.
- Mit `AH_TEST_DB` laufen die drei übrigen grün: `3 passed`.
Metrik: `pg_engine`-Tests des Issuers, die in keinem Lauf gegen Postgres stehen: 3 → 0.
Orakel: mutation-sample — einen der drei neuen Einträge in `stack_pytest.sh` streichen: `stack_pytest_test.sh` rot
(die Zahl im grünen Fall und die fehlende XML-Datei).
Dedup-Key: ref:scripts:stack_pytest.sh:r0292-race-tests
HEAD: 9a512413
Semantik: `docs/developer/cicd.html:117-131`: „Pflicht-Tests gegen den Stack. Vier Tests brauchen einen echten Dienst
und skippen sich überall, wo er fehlt … Der `integration`-Layer fährt sie im Schritt `stack-pytest` … Den
TOCTOU-Test fährt das PR-CI nicht mit Postgres – der Job `ca-issuer` nutzt den In-Memory-Token-Store –, mit echtem
Postgres läuft er nur hier.“ Ein Postgres-Test des Issuers, der nicht in der Liste steht, läuft also nirgends.

### T2 — multibox --tunnel: der Tunnel-Agent synct einmal über die Route seines Servers (R-0315)  [x]
Komponente: scripts · Dateien: scripts/tests/box_tunnelbox.sh, scripts/tests/multibox.sh, scripts/tests/multibox_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @be16ab9d 2026-10-13T00:13:38+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Änderung:
- `box_tunnelbox.sh`: Nach dem Provisionieren (`:29-32`) und dem Start von frpc (`:36-45`) ruft die Box einmal
  `sudo adminhelper-agent frpc sync` (`apps/agent/cmd/adminhelper-agent/main.go:110-125`, `frpc` → `sync` →
  `frpc.Sync`). Der holt
  `/api/frp/provision/{id}/config-hash` mit der mTLS-Identität des Agents und seinem API-Key
  (`apps/agent/internal/frpc/sync.go:47-58`) und vergleicht mit der Hash-Datei, die das Provisionieren geschrieben
  hat (`config.FrpHashFile()`, `sync.go:136`).
- Die Box druckt eine Marke:
  - `TUNNEL_SYNC_HASH_OK`: Exit 0, die Hash-Datei ist vorher nicht leer und nachher gleich, und die Ausgabe meldet
    keine Änderung („Config-Aenderung erkannt“, `sync.go:69`).
  - `TUNNEL_SYNC_HASH_CHANGED`: Exit 0, aber eine Änderung.
  - `TUNNEL_SYNC_FAILED`: Exit ≠ 0, die Ausgabe eingerückt dahinter.
- `multibox.sh`: Nach der Prüfung von `TUNNEL_FRPC_CONNECTED` (`:249-251`) ein `ok`, wenn die Marke
  `TUNNEL_SYNC_HASH_OK` lautet, sonst ein `bad` mit der Marke.
- `multibox_test.sh` (hermetisch, `vm.py` ist dort eine Attrappe, `:41-66`): Die Attrappe antwortet für
  `box_tunnelbox.sh` mit `TUNNEL_FRPC_CONNECTED` und einer Sync-Marke, die eine Variable wählt (wie
  `FAKE_SERVER_RC`). Ein Lauf mit `--tunnel` und `TUNNEL_SYNC_HASH_OK` zeigt das neue `ok`, einer mit
  `TUNNEL_SYNC_FAILED` das neue `bad` und einen Exit ≠ 0.
- Warum das die gebundene Route mit dem Agent-Zertifikat beweist: Unter `--enforce` kommt ein Request ohne
  Zertifikat nicht durch das Gateway. `require_cert_server` (`apps/server/app/core/identity.py:156-172`) weist ein
  Agent-Zertifikat eines anderen Servers mit 403 ab. Ein gelungener Sync heißt also: das eigene Zertifikat, die
  Route des eigenen Servers, und der Hash stimmt mit dem provisionierten überein.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (die Prüfung eines Testlaufs)
Beweis: feature/server-identity-followups@268e3eae, `multibox.sh --enforce --agents 1 --tunnel`: `16 ok`, im Log kein
Abruf von `config-hash` (Zeile R-0315). origin/main@9a512413: `git grep -n 'config-hash\|adminhelper-agent frpc sync' --
scripts/tests/multibox.sh scripts/tests/box_tunnelbox.sh` → kein Treffer.
Metrik: Abrufe der gebundenen Sync-Route mit dem Agent-Zertifikat in einem Multibox-Lauf mit `--tunnel`: 0 → 1.
Orakel: mutation-sample — in `multibox.sh` die neue Prüfung entfernt oder auf `ok` gestellt: der neue Fall in
`multibox_test.sh` rot.
Dedup-Key: ref:scripts:multibox.sh:frpc-sync-check
HEAD: 9a512413
Semantik: `apps/server/app/core/identity.py:157-161`, „An agent certificate belongs to the server it was provisioned
for (R-0283): on a route of one server … must carry that server_id as its CN, or the request gets a 403“. Die
Route des Syncs ist eine solche Route (`apps/server/app/modules/frp/provision_router.py:70`, `:82`). In docs/
keine Stelle zum Multibox-Inhalt; gesucht nach `TUNNEL_FRPC`, „S4“, `config-hash`.
