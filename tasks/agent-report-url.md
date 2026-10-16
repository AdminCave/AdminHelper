<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent-Report-Proxy kodiert die Server-ID — Task-Ledger
Status: erledigt · Branch: feature/agent-report-url · Review: am Ende
Spec: Roadmap R-0391
Heavy: linux-full — Server-API (`monitoring_proxy/router.py`); REG aus dem Sammellauf 2026-10-15-1606: der Fix beweist sich vor dem Merge auf einer Box (`/test`: `bash scripts/tests/run.sh all --strict --step schemathesis`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: `/feature-plan --kurz R-0391`. Einziger roter Schritt des Sammellaufs; bis er grün ist, gilt die Merge-Sperre für `linux-full` (`/feature-build` §5).

### T1 — Agent-Report-Proxy setzt die Server-ID kodiert in die Ziel-URL  [x]
Komponente: server · Dateien: apps/server/app/modules/monitoring_proxy/router.py, apps/server/tests/test_monitoring_ingest_ratelimit.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3bda0efb 2026-10-16T08:35:28+02:00
Review: am Ende (Branch-Review)
Änderung: `proxy_agent_report` (`router.py:84-85`) setzt `server_id` mit `quote(server_id, safe="")` in `f"{_MONITOR_BASE}/agent/{…}/report"` ein (`quote` ist schon importiert, `router.py:14`). Heute steht dort der von Starlette dekodierte Wert: ein Steuerzeichen (`%1F`) lässt httpx mit `InvalidURL` abbrechen (unbehandelt, 500), ein `?` oder `#` (`%3F`, `%23`) schneidet die Ziel-URL ab und trifft eine andere Monitoring-Route. Die Monitoring-Route (`apps/monitoring/app/routers/agent.py:68`) dekodiert den Pfad wieder, sie sieht dieselbe `server_id` wie heute. Neuer Test in `test_monitoring_ingest_ratelimit.py` neben dem T41-Test (`:105`): ein echter `httpx.AsyncClient` mit `MockTransport` als `_client` (nicht `_client.post` ersetzen, sonst greift die URL-Prüfung von httpx nicht), parametrisiert über `%1F`, `web%3Fx` und `web%231`; erwartet 200 und den kodierten Pfad `/agent/<wie gesendet>/report` am Transport. Auf HEAD rot: `%1F` mit `httpx.InvalidURL`, die beiden anderen mit abgeschnittenem Pfad. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_ingest_ratelimit.py
Doku: CHANGELOG.md (Fixed); docs/ keine (die Route reicht weiter „1:1“ durch, wie dokumentiert)
Beweis: Sammellauf 2026-10-15-1606 · main@c498bb3e · `heavy.sh all` → `run.sh[all]: 35 passed, 1 failed`, Schritt `schemathesis`: server `4 failed, 316 passed`, alle in `test_api_under_every_auth_context[POST /api/monitoring/agent/{server_id}/report]` (admin_jwt, read_key, read_write_key, internal_key) mit `httpx.InvalidURL: Invalid non-printable ASCII character in URL, '\x1f' at position 29`; lokal auf main@399bd9ff dreimal identisch rot: `( . ./.devenv.sh; cd apps/server && DATABASE_URL="$AH_TEST_DB" AH_SCHEMATHESIS_EXAMPLES=100 "$AH_VENV/bin/python" -m pytest tests/test_schemathesis.py -m schemathesis -k "monitoring and agent and report" -q )` → `4 failed, 316 deselected`, jedes Mal `'\x1f' at position 29`
Orakel: crash — unbehandelte Ausnahme im Proxy, 500 statt der Antwort des Monitoring-Dienstes
Dedup-Key: reg:server:monitoring_proxy/router.py:agent-report-url
HEAD: 399bd9ff
Semantik: docs/developer/monitoring.html:54 — „<code>POST /api/monitoring/agent/{server_id}/report</code> &ndash; <strong>&ouml;ffentlich</strong> (X-API-Key), reicht 1:1 an den Service“ (EN `docs/en/developer/monitoring.html:54`, ebenso `docs/developer/api-reference.html:170`: „Reicht den Agent-Push 1:1 an den Monitoring-Microservice durch.“)

## Beweis (Sammellauf 2026-10-15-1606, nachgeprüft 2026-10-16)
- Rot im Sammellauf über main@c498bb3e, Schritt `schemathesis` (generate-Phase, `AH_SCHEMATHESIS_EXAMPLES=100`); die PR-CI fährt nur die explicit-Phase und trifft das Steuerzeichen nicht.
- Die Interpolation steht so seit 66856951 (Juni). Beim letzten grünen Sammellauf (2026-09-25, main@62e7ac16) war die Route vom Fuzzing ausgenommen (`schemathesis_exclude.toml`, `raises = true`, „In-process nicht fuzzbar“). 7302011b (Stub für den Proxy-Client) hob die Ausnahme auf, f67af56f (R-0376, #179) gab jedem Lifespan einen offenen Client; seitdem erreicht der Fuzzer die Route. Kein Produkt-Merge hat den Fehler eingeführt, der Sammellauf sieht ihn erst jetzt. Ein „grün auf dem letzten grünen Stand“ gibt es deshalb nicht: dort lief die Route nicht.
- Die generate-Phase ist trotz `derandomize` nicht wiederholbar (`test_schemathesis.py:273-279`); den Fix beweist deshalb der neue deterministische Test, der `--step`-Lauf aus `Heavy:` bestätigt ihn auf der Box.
- Fix bewiesen (2026-10-16, feature/agent-report-url@ee3d4d09): die lokale Probe oben ist grün (`4 passed, 316 deselected`). Auf der Box (Lane agent-report-url, `AH_SCHEMATHESIS_EXAMPLES=100`) ergab `bash scripts/tests/run.sh all --strict --step schemathesis` → `run.sh[all]: 1 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns` (server `320 passed`, monitoring `114 passed`, ca-issuer `9 passed`). Der erste Schritt-Lauf auf der frischen Box war UNVERIFIED (`SKIP schemathesis (schemathesis not installed)`), weil ein reiner Schritt-Lauf die Python-Abhängigkeiten nicht installiert; davor lief deshalb `iter.sh quick --strict --only server` → `run.sh[quick]: 4 passed, 0 failed, 14 skipped` (server schemathesis `320 passed`).
- Geprüft und nicht betroffen: `servers/router.py:216` und `provisioning/helpers.py:53` setzen ebenfalls eine `server_id` unkodiert in eine URL, aber erst, nachdem ein Server mit dieser ID in der Datenbank gefunden ist (`servers/router.py:192`, `provisioning/router.py:136`), sonst 404.
