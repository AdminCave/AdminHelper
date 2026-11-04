<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-8 — Task-Ledger
Status: erledigt · Branch: feature/kern-ca-8 · Review: pro Task
Spec: docs/features/kern-ca-8.md (Roadmap R-1112)
Heavy: scenario --tunnel — FRP-Tunnel-Datenpfad und PKI (frps-Leaf, frpc von Agent und Visitor über drei Hosts); ask-first
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@03c4068a`. Jede Task liegt auf einem Risikopfad (PKI, FRP): `security` je Task. T3 und T4 fahren als R-1121 in `tasks/kern-ca-9.md`.

### T1 — frps-Leaf trägt einen eigenen festen Namen (R-1112)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/config.py, apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_frps_cert.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_config.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @d3809767 2026-11-03T20:33:36+01:00
Review: approve (.ah-out/review/kern-ca-8/T1.verdict.json)
Änderung: `config.py` bekommt die Konstante `FRPS_TLS_NAME = "frps.adminhelper.invalid"`; `frps_extra_sans()` hängt sie an (einmal, auch wenn sie schon dasteht), andere Leafs tragen sie nicht (Entscheidungen im Code und unter Entscheidungen). Tests zuerst rot: das frps-Leaf trägt den Namen neben `DOMAIN` und den Extra-SANs; ein bestehendes frps-Leaf ohne ihn wird beim Start neu ausgestellt; kein anderes Leaf trägt ihn.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_frps_cert.py tests/test_gateway_cert.py tests/test_config.py
Doku: → T5

### T2 — Agent setzt transport.tls.serverName in frpc.toml (R-1112)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/rewrite.go, apps/agent/internal/frpc/rewrite_test.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/frpc/servertoml_test.go, apps/agent/internal/frpc/servertoml.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f919bad7 2026-11-03T20:54:26+01:00
Review: approve (.ah-out/review/kern-ca-8/T2.verdict.json)
Änderung: Nach `checkServerConfig` (`sync.go:252`) setzt der Agent `serverName = "frps.adminhelper.invalid"` in den `[transport.tls]`-Block des Server-Texts (ohne Kopf als `transport.tls.serverName` im Root); `checkServerConfig` lehnt einen vom Server gesendeten `serverName` weiter ab, also steht der Schlüssel nie doppelt. Die Konstante nennt im Kommentar ihr Gegenstück (ca-issuer `config.py`). Tests zuerst rot: die geschriebene `frpc.toml` trägt den Namen genau einmal im TLS-Block, für den Text mit und ohne `[transport.tls]`-Kopf; der Hash-Vergleich mit dem Server (`FrpHashFile`) bleibt am Server-Text.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5

### T5 — Doku und Changelog (R-1112)  [x]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-ca-8.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ee8d6139 2026-11-03T21:03:14+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: `frp-tunnel.html` (Abschnitt Tunnel-PKI, `trustedCaFile`-Punkt): frpc prüft das frps-Zertifikat gegen `ca.crt` und den festen Namen `frps.adminhelper.invalid`, den nur das frps-Leaf trägt; `agent.html`: der Agent setzt ihn in `frpc.toml`. `changelog.d/kern-ca-8.md` unter `### Security`, ohne Details.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/frp-tunnel.html + EN · docs/developer/agent.html + EN · changelog.d/kern-ca-8.md
Task-Review: am Ende

### T6 — Abschlussprüfung: neutrale Texte, Kommentare zum Gegenstück (R-1112)  [x]
Komponente: agent · Dateien: docs/features/kern-ca-8.md, tasks/kern-ca-8.md, changelog.d/kern-ca-8.md, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, apps/ca-issuer/app/config.py, apps/agent/internal/frpc/rewrite.go, apps/agent/internal/frpc/sync.go
Evidenz: run.sh[quick] agent ca-issuer: 6 passed, 0 failed, 12 skipped @ab1e2ab9 2026-11-03T21:18:57+01:00
Review: approve (.ah-out/review/kern-ca-8/T6.verdict.json)
Änderung: Spec, Ledger, Changelog und Admin-Doku DE+EN neutral gefasst (frpc verlangt den Namen, den nur das frps-Zertifikat trägt); die Kommentare in `config.py` und `rewrite.go` nennen nur das Gegenstück, das den Namen schon verlangt; der Kommentar am unveränderten Hash in `sync.go` nennt das Neuschreiben. Fund der Abschlussprüfung.
Verify: bash scripts/dev/verify.sh agent ca-issuer --strict
Doku: docs/admin/frp-tunnel.html + EN · changelog.d/kern-ca-8.md

## Entscheidungen
- T1: nennt `DOMAIN` selbst den frps-Namen, bricht der Start ab (`main.py`, RuntimeError); nennt ihn nur `EXTRA_SANS`, lässt der ca-issuer ihn mit Warnung weg (Spec, Trade-offs). Der Name wird über `config.frps_leaf_sans()` angehängt, `frps_extra_sans()` behält seine Bedeutung (Fallback-Test `test_config.py`). Beide Prüfungen erkennen auch `*.adminhelper.invalid` (`config.covers_frps_tls_name`, Fund der Task-Prüfung).
- Heavy 2026-11-04 auf eda2f144 (Kevins Ja): `multibox.sh --tunnel` → `multibox: 32 ok, 0 failed, 1 skipped`; der Skip ist der MTLS_ENFORCE-Wächter (ohne `--enforce` erwartet). frps nimmt den festen TLS-Namen an; die Szenario-VMs sind abgebaut.
