<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Identität: Übernahme, Enroll, Aktivierung und Neu-Provisionieren nach dem Zertifikats-Register — Task-Ledger
Status: aktiv · Branch: feature/identity-followups-2 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0306, R-0311, R-0312, Triage Kevin 2026-10-12; R-0312 Weg (a) als Bugfix im Sinn der Doku; die Zeitpruefung beim Enroll in T1 angenommen, sie schliesst eine zurueckgestellte Zeile, die jetzt belegt ist; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0306, R-0311, R-0312
Heavy: linux-full + scenario --enforce --agents 1 — `apps/ca-issuer`, Server-API und `apps/agent`: `run.sh integration` (Enroll und Erneuern über das Gateway, Stack-Test Schritt 8b, Register-Sperrtests) und ein Multibox-Lauf, weil sich die Aktivierung über `:8444` und die Agent-Provisionierung ändern.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, gofmt und go vet sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeilen am 2026-10-12
angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@2ebdef55. Jede Aussage über das heutige Verhalten ist mit einer Probe auf diesem Stand belegt
(nicht committet, dreimal identisch).

**Die Regel, die alle drei vervollständigen:** Der Widerruf einer Identität ist ein Zeitpunkt; was bis dahin für sie
ausgestellt oder angelegt wurde, gilt danach nicht mehr, und wer gleichzeitig eine Linie für sie anlegt, wartet auf die
Sperre der Identität (`IDENTITY_LOCK_SQL`). Eine Aktivierung ersetzt alles, was ein Agent für seinen Server bekommt, auf
einmal.

### T1 — Übernahme und Enroll nehmen die Sperre der Identität; ein Token von vor dem Widerruf gilt nicht mehr (R-0306)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/db.py, apps/ca-issuer/app/tokens.py, apps/ca-issuer/tests/test_db_token_store.py, apps/server/app/modules/enrollment/models.py, apps/server/app/core/identity.py, apps/server/tests/test_identity_revocation.py, CHANGELOG.md, docs/admin/benutzer.html, docs/en/admin/users.html, apps/ca-issuer/tests/test_enroll_renew.py
Evidenz: run.sh[quick] ca-issuer server: 5 passed, 0 failed, 13 skipped · contracts: 1 ok @5a0791e4 2026-10-12T17:35:13+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- **ca-issuer, Enroll** (`db.py:190-216`): nach dem Einlösen (`_consume`, `:164-185`) die Sperre der Identität des
  Grants (`_lock_identity`, `:123`), dann der Zeitpunkt: Ist die Identität zu oder nach dem Prägen des Tokens widerrufen,
  gilt der Token nicht (wie ein unbekannter: `None`, nichts ausgestellt). Dazu liest die Sicht des Issuers auf
  `enrollment_tokens` (`db.py:54-64`) die Spalte `created_at`, die die Tabelle am Server schon hat (`models.py:60`);
  `_consume` gibt sie mit zurück. Ohne Prägezeit gilt die vorsichtige Lesart von `_active` (`:355-367`): jede
  Widerrufung zählt. Der `InMemoryTokenStore` (`tokens.py`, `_Entry` `:154`) folgt derselben Regel.
- **Server, Übernahme** (`models.py:265-301`): vor `_take_over` (`:297`) die Sperre der Identität und danach noch einmal
  `is_identity_revoked` mit dem notBefore; ist sie inzwischen widerrufen, wird nichts übernommen.
- Die Reihenfolge bleibt ohne Zyklus: Das Löschen (`revoke_identity`) nimmt nur die Sperre und schreibt
  `revoked_identities` und die Linien, nie eine Token-Zeile.
- Kommentare: `db.py:114-119` („The lock both writers …“) nennt alle Stellen, die die Sperre nehmen, und `models.py`
  bei `IDENTITY_LOCK_SQL` (`:102-105`) ebenso. `identity.py:123-124`: der Kommentar zu `CERT_REVOKED` verweist auf
  `CERT_USER_MISMATCH`, nicht mehr auf „the one above“.
- Tests, je am Dateiende:
  - ca-issuer: ein Token, geprägt vor dem Widerruf seiner Identität, stellt danach nichts aus; einer, geprägt danach,
    stellt aus. Auf zwei echten Postgres-Verbindungen: ein Enroll, während ein Widerruf läuft, wartet und wird danach
    abgelehnt.
  - Server: eine Übernahme während eines laufenden Widerrufs wartet und legt danach keine Linie an.
- CHANGELOG `### Changed`, neutral: Ein noch nicht eingelöstes Enrollment-Token gilt nach dem Löschen seines Benutzers
  oder Servers nicht mehr. `benutzer.html` / `users.html` (DE und EN): der Punkt „Benutzer löschen“ nennt das.
Verify: bash scripts/tests/run.sh quick --strict --only ca-issuer server
Doku: CHANGELOG · docs/admin/benutzer.html + docs/en/admin/users.html
Beweis: origin/main@2ebdef55: `_consume` (`db.py:164-185`) prüft Ablauf und Verwendung des Tokens, nicht den Zeitpunkt
der Identität; `enroll` (`:190-216`) und `admit_certificate` (`models.py:265`) legen Linien an, ohne
`IDENTITY_LOCK_SQL` zu nehmen, das `revoke_identity` (`models.py:108`) und das Erneuern nehmen.
HEAD: 2ebdef55
Semantik: `docs/admin/benutzer.html:106`: „Benutzer löschen sperrt alle Zertifikate, die bis dahin für diesen Benutzer
ausgestellt wurden, am Server wie beim Erneuern.“

### T2 — Aktivierung: API-Key, Monitor-Key und Enrollment-Token entstehen unter einer Sperre (R-0311)  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/tests/test_provisioning.py
Änderung: `activate_provision` (`router.py:107`) hält die Zeile des Servers (`:134`, `FOR NO KEY UPDATE`) heute nur bis
zum ersten Commit (`:167`); Monitor-Key (`:180`) und Enrollment-Token (`:190`) entstehen danach. Künftig: Keys ersetzen,
Monitor-Key holen, FRP-Bundle, Enrollment-Token prägen, und erst dann committen; die Audit-Einträge folgen danach
(`audit.record` committet selbst, ebenso `mint_enrollment_token`, `enrollment/service.py:29-50`: diese Commits dürfen
nicht vor dem Monitor-Key liegen). Eine zweite Aktivierung desselben Servers wartet so, bis die erste alles hat, und
ersetzt dann beides; der Monitor-Dienst ersetzt den Key je Server selbst (`apps/monitoring/app/routers/admin.py:23-43`)
und ruft den Server dabei nicht zurück. Der Kommentar `:131-133` sagt, bis wann die Sperre hält.
- Test in `test_provisioning.py`, am Dateiende, auf echten Postgres-Verbindungen: der Monitor-Dienst als Attrappe mit
  seiner Regel (ein Key je Server, der neue ersetzt den alten); die erste Aktivierung hält beim Monitor-Key an, die
  zweite wartet (`pg_blocking_pids`), danach stammen gültiger API-Key und gültiger Monitor-Key aus derselben
  Aktivierung. Die Zeilen des Tests werden am Ende entfernt, Audit-Zeilen per Id.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (R-0279 beschreibt das Ergebnis: es gilt, was der Agent bei der letzten Provisionierung bekommt)
Beweis: origin/main@2ebdef55, Probe (erste Aktivierung hält nach ihrem Commit vor dem Monitor-Key an, die zweite läuft
ganz durch): `AssertionError: valid API key from b, valid monitor key from a`, dreimal identisch.
Dedup-Key: bug:server:provisioning-router.py:activate-lock-ends-early
HEAD: 2ebdef55
Semantik: `docs/admin/agent-deployment.html:149`: „Der Server löscht den API-Key der vorigen Provisionierung; es gilt nur
noch der Key, den der Agent jetzt bekommt.“

### T3 — Agent: Neu-Provisionieren für einen anderen Server verwirft dessen Identität (R-0312)  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/enroll/enroll_test.go, apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Änderung (Empfehlung, siehe Gate): `runEnrollment` (`provision.go:240`) prüft vor `CheckStorable` (`:264`) den CN der
gespeicherten Identität. Gehört sie zu einem anderen Server als `info.SubjectID`, entfernt der Agent sie (Key,
Zertifikat, CA), bevor er das Zertifikat für den neuen Server beantragt: Seit R-0283 nimmt der neue Server ein
Zertifikat des alten nicht an. Scheitert das Enrollment danach, läuft der Agent wie dokumentiert vorerst mit dem
API-Key. Eine Identität desselben Servers bleibt bis zum `Store`, wie heute.
- Ein Helfer in `enroll.go` neben `LeafFingerprint` (`:233`) liest den CN des gespeicherten Leafs; ein zweiter entfernt
  die drei Dateien.
- Tests: in `provision_test.go` eine Identität von srv-1, Neu-Provisionierung für srv-2 mit scheiterndem Issuer →
  danach keine Identität von srv-1; dieselbe Lage für srv-1 → die Identität bleibt. In `enroll_test.go` die Helfer.
- `agent-deployment.html` (DE und EN), Abschnitt Neu provisionieren: Wird der Host für einen anderen Server provisioniert,
  verwirft der Agent die Identität des bisherigen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html
Beweis: origin/main@2ebdef55, Probe (Identität von srv-1, Neu-Provisionierung für srv-2, der Issuer antwortet 500): `the
identity of server "srv-1" stays after provisioning for srv-2`, dreimal identisch. `ServerClient`
(`enroll/client.go:35-50`) legt eine vorhandene Identität immer vor.
Dedup-Key: bug:agent:provision:foreign-identity-stays
HEAD: 2ebdef55
Semantik: `docs/admin/agent-deployment.html:148`: „Best-effort: schlägt das Enrollment fehl (z. B. Port 8444 nicht
erreichbar), läuft der Agent vorerst mit dem API-Key weiter.“
