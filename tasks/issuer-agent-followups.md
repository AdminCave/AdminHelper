<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ca-issuer und Agent: Prüfung, Reihenfolge und Neu-Provisionieren nach dem Zertifikats-Register — Task-Ledger
Status: aktiv · Branch: feature/issuer-agent-followups · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0290, R-0292, R-0293, Triage Kevin 2026-10-11; kein Refuter, die Proben belegen die Funde; Teststrategie: Multibox gemeinsam mit server-identity-followups nach dessen Bau, über beide Stände; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0290, R-0292, R-0293
Heavy: linux-full — `apps/ca-issuer` und `apps/agent`: `run.sh integration` (Erneuern über das Gateway, Stack-Test Schritt 8b, die Register-Sperrtests in `stack_pytest`); der Multibox-Lauf `--enforce --agents 1 --tunnel` folgt gemeinsam mit server-identity-followups über beide Stände (Teststrategie der Aufsicht, 2026-10-12).
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, gofmt und go vet sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac), Paket „Phase-B-Folgen“, Teil 2 von 2 (Teil 1:
`tasks/server-identity-followups.md`). Kevin hat die Zeilen am 2026-10-11 angenommen. Die private Roadmap ist in diesem
Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@40d3eb0a. Jede Aussage über
das heutige Verhalten ist mit einer Probe auf diesem Stand belegt (nicht committet, dreimal identisch).

Beide Teile ändern Code der Komponente `server` und teilen sich die Test-Datenbank: Teil 1 und T2 hier laufen nacheinander.

### T1 — ca-issuer: ein Zertifikat mit unbekanntem Signatur-Algorithmus wird abgelehnt, nicht mit 500 (R-0290)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/issuer.py, apps/ca-issuer/tests/test_enroll_renew.py
Evidenz: run.sh[quick] ca-issuer: 4 passed, 0 failed, 14 skipped @f5335b73 2026-10-12T10:44:07+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `_verify_ca_signed` (`issuer.py:46-74`) fängt auch `cryptography.exceptions.UnsupportedAlgorithm`: Ein
vorgelegtes Zertifikat, dessen Signatur-Algorithmus `cryptography` nicht kennt, ist keines des Issuers und wird wie die
übrigen mit `IssuanceError` abgelehnt (4xx), nicht als 500 durchgereicht.
- Test in `test_enroll_renew.py`, am Dateiende, neben `test_renew_rejects_non_ecdsa_cert_cleanly`: ein selbst signiertes
  Leaf, dessen Signatur-OID im DER auf eine unbekannte umgeschrieben ist, an `/renew` → 4xx.
Verify: bash scripts/dev/verify.sh ca-issuer --strict
Doku: keine (intern)
Beweis: origin/main@40d3eb0a, Probe: dasselbe Leaf (ecdsa-with-SHA256 → OID `1.2.840.10045.4.3.9`) an `/renew` →
`AssertionError: expected a 4xx refusal, got 500`, dreimal identisch; die Ursache ist `UnsupportedAlgorithm` an
`issuer.py:65` (`cert.signature_hash_algorithm`).
Dedup-Key: bug:ca-issuer:issuer.py:verify-unsupported-algorithm
HEAD: 40d3eb0a
Semantik: keine Stelle in `docs/` — gesucht in `docs/developer/` und ADR 0001 nach der Ablehnung beim Erneuern. Die
Absicht steht im Code: `issuer.py:68-71` „it is a forgery and must be rejected cleanly here, never bubble up as a 500 at
the issuer“.

### T2 — Erneuern und Löschen derselben Identität laufen nacheinander (R-0292)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/db.py, apps/ca-issuer/tests/test_db_token_store.py, apps/server/app/modules/enrollment/models.py, apps/server/tests/test_identity_revocation.py
Evidenz: run.sh[quick] ca-issuer server: 5 passed, 0 failed, 13 skipped @f363b087 2026-10-12T11:01:36+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `revoke_identity` (Server, `enrollment/models.py:101-123`) und `DbTokenStore.renew` (ca-issuer, `db.py:239-285`)
nehmen am Anfang ihrer Transaktion dieselbe Sperre auf die Identität (subject, scope), einen transaktionsweiten
Advisory-Lock in Postgres. Damit sieht das Löschen auch eine Linie, die ein Erneuern gerade erst anlegt (`db.py:266-267`,
`_take_over`), und ein Erneuern, das nach dem Löschen läuft, sieht dessen Zeitpunkt.
- Der Schlüssel ist auf beiden Seiten derselbe Ausdruck; ein Server-Test liest ihn aus dem Quelltext des ca-issuer, wie
  `test_certificate_check.py` für `LEGACY_WINDOW`.
- Ohne Postgres (die sqlite-Tests des `DbTokenStore`) entfällt die Sperre.
- Tests am Dateiende, auf zwei echten Postgres-Verbindungen: im ca-issuer ein Erneuern mit Übernahme gegen ein Löschen,
  das vorher begonnen hat (das Erneuern wartet und wird danach abgelehnt), und umgekehrt (das Löschen wartet und sperrt
  danach auch die neue Linie samt Nachfolger); im Server die Kopplung des Schlüssels.
Verify: bash scripts/tests/run.sh quick --strict --only ca-issuer server
Doku: keine (das Verhalten beschreibt `docs/admin/benutzer.html:106` schon)
Beweis: origin/main@40d3eb0a: `_take_over` (`db.py:287-314`) legt beim Erneuern eines nie erfassten Zertifikats eine
Linie an; `revoke_identity` sperrt die offenen Linien, die es sieht (`models.py:119-123`); keine gemeinsame Sperre über
beide.
HEAD: 40d3eb0a
Semantik: `docs/admin/benutzer.html:106`: „Benutzer löschen sperrt alle Zertifikate, die bis dahin für diesen Benutzer
ausgestellt wurden, am Server wie beim Erneuern.“

### T3 — Agent: Neu-Provisionieren prüft vor dem Antrag, dass die Identität geschrieben werden kann (R-0293)  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/enroll/enroll_test.go, apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go
Änderung: `runEnrollment` (`provision.go:240-272`) prüft vor `enroll.Submit` (`:268`), dass das Identitäts-Verzeichnis
die neue Identität aufnehmen kann: ein Probe-Schreiben der gestagten Dateien wie in `stageIdentity` (`enroll.go:161`),
danach wieder entfernt. Scheitert das, bricht die Provisionierung vor dem Antrag ab; das bisherige Zertifikat und seine
Linie bleiben. Scheitert `enroll.Store` (`:272`) trotzdem nach dem Antrag, nennt der Fehler den Befehl zum erneuten
Provisionieren (`reprovisionHint`).
- Tests: in `provision_test.go` eine Neu-Provisionierung, deren gestagtes Zertifikat nicht geschrieben werden kann (ein
  Verzeichnis an `agent.crt.tmp`, wie `TestStageIdentityCleansUpStagedTempsOnWriteError`): kein Antrag an den Issuer,
  Fehler; in `enroll_test.go` die Probe selbst (ein schreibbares Verzeichnis bleibt ohne Rest, ein blockiertes meldet
  den Fehler).
- Ein `chmod` auf das Verzeichnis taugt als Test nicht: `Store` setzt es selbst auf 0700 (`enroll.go:141`).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (intern; `agent-deployment.html:149` beschreibt das Neu-Provisionieren schon)
Beweis: origin/main@40d3eb0a, Probe (Neu-Provisionierung mit blockiertem `agent.crt.tmp`): `expected no enrollment request
for an identity that cannot be written, the issuer got 2 in total`, dreimal identisch; der Antrag mit `replaces` ging
vor dem gescheiterten `Store` hinaus.
Dedup-Key: bug:agent:provision:store-after-submit
HEAD: 40d3eb0a
Semantik: `docs/admin/agent-deployment.html:149`: „Provisionierst du einen Server erneut …, ersetzt der neue Agent den
bisherigen.“
