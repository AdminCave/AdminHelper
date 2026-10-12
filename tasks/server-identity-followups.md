<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Logout, Agent-Routen und Aktivierung nach dem Zertifikats-Register — Task-Ledger
Status: bereit · Branch: feature/server-identity-followups · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0282, R-0283, R-0291, Triage Kevin 2026-10-11; R-0282 nach Kevins Wort vom 2026-10-12 Weg (b): Logout bleibt ungebunden und wird dokumentiert; kein Refuter; der Multibox-Lauf deckt auch issuer-agent-followups ab; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0282, R-0283, R-0291
Heavy: linux-full + scenario --enforce --agents 1 --tunnel — Server-API unter mTLS: `run.sh integration` (Gateway, Login und Logout mit Client-Zertifikat, Agent-Routen) und ein Multibox-Lauf, weil die Agent-Pushes und die frpc-Config über den Netz-Hop mit dem Agent-Zertifikat laufen.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac), Paket „Phase-B-Folgen“, Teil 1 von 2 (Teil 2:
`tasks/issuer-agent-followups.md`). Kevin hat die Zeilen am 2026-10-11 angenommen. Die private Roadmap ist in diesem
Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@40d3eb0a. Jede Aussage über
das heutige Verhalten ist mit einer Probe auf diesem Stand belegt (nicht committet, dreimal identisch).

**Die Funktion:** Unter mTLS gehört ein Client-Zertifikat einer Identität: ein access-Zertifikat dem Benutzer, ein
Agent-Zertifikat (Scope `tunnel`) dem Server, für den der Agent provisioniert wurde. Was ein Zertifikat einer Identität
zuordnet, gilt an jeder Route, die mit dieser Identität arbeitet.

### T1 — Logout: die Regel festhalten, Tokens werden entwertet, gleich welches Zertifikat (R-0282)  [x]
Komponente: server · Dateien: apps/server/tests/test_cert_user_binding.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @40c9234a 2026-10-12T12:32:21+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung (Weg (b), siehe Gate): `POST /api/auth/logout` (`auth_router.py:242-275`) bleibt ohne Bindung: er entwertet nur
die Tokens, die vorgelegt werden (Bearer, Refresh aus Body oder Cookie), verleiht nichts und gibt nichts preis. So kann
sich auch ein Gerät abmelden, dessen Zertifikat der Server nicht mehr annimmt.
- Tests in `test_cert_user_binding.py`, am Dateiende: Logout mit dem Zertifikat eines anderen Benutzers und mit einem
  gesperrten Zertifikat gibt 200, und der vorgelegte Bearer gilt danach nicht mehr (`/api/auth/me` 401).
- `api-reference.html` (DE und EN) beim Logout: ein Satz, dass der Logout die Zertifikats-Bindung bewusst nicht prüft,
  weil er nur entwertet.
- Weg (a) verworfen (Kevin, 2026-10-12, Weg (b)). Er hätte bedeutet, dass T1 eine Code-Änderung wird: `logout` ruft die Bindung aus `require_cert_user` für den Benutzer
  des vorgelegten Tokens, ohne die Register-Prüfung; die Tests erwarten dann 403 `ERR_CERT_USER_MISMATCH` mit fremdem
  Zertifikat und 200 mit dem eigenen, auch wenn es gesperrt ist.
Verify: bash scripts/dev/verify.sh server --strict
Doku: docs/developer/api-reference.html DE und EN
Beweis: origin/main@40d3eb0a: `logout` liest den Bearer mit `username_from_token_unverified` (`auth_router.py:259`) und ruft
`require_cert_user` nicht; Login (`:130`), Refresh (`:225`) und Bootstrap (`:322`) rufen es.
HEAD: 40d3eb0a
Semantik: `docs/admin/benutzer.html:90`: „Unter mTLS gehört das Zertifikat diesem Benutzer: Login, API und
Zertifikats-Ausgabe nehmen es nur für ihn an.“; `docs/developer/api-reference.html:68` beschreibt den Logout als
„Authentifizierung optional“. Ob der Logout zur gebundenen API zählt, sagt keine Stelle — die offene Frage am Gate.

### T2 — Agent-Routen: ein Agent-Zertifikat gilt nur für seinen eigenen Server (R-0283)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/modules/monitoring_proxy/router.py, apps/server/app/modules/frp/provision_router.py, apps/server/tests/test_mtls_scope.py, CHANGELOG.md, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @a76db1bd 2026-10-12T12:49:40+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Eine Route mit `server_id` im Pfad, die ein Agent-Zertifikat annimmt, verlangt, dass dessen CN diese
`server_id` ist; sonst 403. Das betrifft den Agent-Report (`monitoring_proxy/router.py:55-80`) und die frpc-Config
(`frp/provision_router.py:69` und `:81`, über `frp/router.py:21` für `tunnel` und `access`). Ein access-Zertifikat
(Admin) bleibt an der frpc-Config, wie es ist. Ohne verifizierte Identität (permissiv ohne Zertifikat) gibt es nichts zu
prüfen; mit einem vorgelegten Zertifikat gilt die Regel in beiden Modi, wie die Bindung an den Benutzer.
- Ein Helfer in `identity.py` neben `require_scope`, als Dependency an beiden Routen.
- Tests in `test_mtls_scope.py`, am Dateiende: Report und frpc-Config mit dem Agent-Zertifikat eines anderen Servers 403
  und nichts weitergereicht; mit dem eigenen durchgereicht; die frpc-Config mit einem access-Zertifikat weiter erlaubt;
  ohne Zertifikat permissiv wie bisher.
- CHANGELOG `### Changed`, neutral: „Ein Agent-Zertifikat gilt an den Agent-Routen nur für den eigenen Server.“
- `agent-deployment.html` (DE und EN): der Satz zu den Server-Pushes nennt, dass das Zertifikat nur für diesen Server gilt.
Verify: bash scripts/dev/verify.sh server --strict
Doku: CHANGELOG · docs/admin/agent-deployment.html DE und EN
Beweis: origin/main@40d3eb0a: der Agent-Report prüft den Scope (`require_scope(SCOPE_AGENT)`, `monitoring_proxy/router.py:59`),
die frpc-Config ebenso (`frp/router.py:21`); die Zuordnung zur `server_id` des Pfads kommt dazu.
HEAD: 40d3eb0a
Semantik: `docs/admin/agent-deployment.html:148`: „Danach weist sich der Agent bei allen Server-Pushes mit diesem Cert aus“.

### T3 — Aktivierung: zwei Aktivierungen desselben Servers laufen nacheinander (R-0291)  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/tests/test_provisioning.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @a2ce38b7 2026-10-12T13:03:43+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `activate_provision` (`provisioning/router.py:107`) sperrt die Zeile des Servers für die Dauer der Aktivierung
(`SELECT … FOR NO KEY UPDATE`, statt der Abfrage `:131`), bevor es die Keys des Servers ersetzt (`:151-155`). Eine zweite
Aktivierung mit einem anderen Token wartet, sieht danach den Key der ersten und ersetzt ihn. Am Ende bleibt genau ein
Key mit dieser `server_id`.
- Test in `test_provisioning.py`, am Dateiende, auf zwei echten Postgres-Verbindungen (wie der Rennen-Test in
  `test_identity_revocation.py`): eine Aktivierung hält die Zeile, die zweite wartet (`pg_blocking_pids`), danach ein Key.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (R-0279 beschreibt das Ergebnis schon: ein Key je Server)
Beweis: origin/main@40d3eb0a, Probe mit zwei Verbindungen (eine Aktivierung hat ihren Key geschrieben, noch nicht
committet; die zweite läuft über die Route): `AssertionError: expected one agent key for the server, found 2`, dreimal
identisch.
Dedup-Key: bug:server:provisioning-router.py:concurrent-activate-two-keys
HEAD: 40d3eb0a
Semantik: `docs/admin/agent-deployment.html:149`: „Der Server löscht den API-Key der vorigen Provisionierung; es gilt nur
noch der Key, den der Agent jetzt bekommt.“
