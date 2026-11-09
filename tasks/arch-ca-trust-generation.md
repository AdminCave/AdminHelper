<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-ca-trust-generation — Task-Ledger
Status: aktiv · Branch: feature/arch-ca-trust-generation · Review: pro Task
Spec: docs/features/arch-ca-trust-generation.md (Roadmap R-1054)
Heavy: linux-full — neue Route in `apps/ca-issuer`, Gateway-Location, Agent-Erneuerung (Sammellauf). Vor dem Merge außerdem der Stack-Job per Dispatch (`gh workflow run ci.yml --ref feature/arch-ca-trust-generation`, fährt `ca_rotation` aus T5) und der Schritt `agent-monitoring` einzeln auf einer VM der Lane (`/test`, `run.sh integration --strict --only …`; der echte Agent fragt `/ca/trust` gegen den Stack). Kein `scenario`: kein neuer Port, kein Cross-Host-Pfad, derselbe mTLS-Client wie bei `/ca/renew`. Kein `windows`: Go- und Rust-Code sind plattformneutral, die CI-Jobs `agent-windows` und `rust-windows` fahren die Suiten nativ.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` je Task T1–T4 (Risikopfade ca-issuer, Gateway, Agent-Enrollment, Desktop-Enrollment/Auth), dazu
`reviewer` je Task.
Reihenfolge: T1 zuerst (Vertrag und Testvektor). T2, T3, T4 hängen nur am Vertrag aus T1 und sind untereinander
unabhängig. T5 braucht T1–T3. T6 zuletzt. `feature/kern-ansible-1` ändert `commands.rs` ab Z. 1322 (Ansible), T4
nur `login` (Z. 560): disjunkte Hunks, vor dem PR `origin/main` hineinmergen.

## Tasks

### T1 — ca-issuer: Route `GET /trust` und Trust-Generation  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/app/storage.py, apps/ca-issuer/app/pki.py, apps/ca-issuer/tests/test_trust_generation.py (neu, SPDX), apps/ca-issuer/tests/test_storage.py, apps/ca-issuer/tests/schemathesis_exclude.toml
Änderung:
- `pki.py`: `trust_generation(pem: bytes) -> str`. Nur `CERTIFICATE`-Blöcke, DER in Reihenfolge verkettet,
  SHA-256, hex klein.
- `storage.py` `Intermediate` (`:84`): Property `trust_generation` aus `trust_bundle` (`:104`), einmal je Scope beim
  Start berechnet. Eine Quelle für `chain` und Generation.
- `issuer.py`: `trust_generation(verified_cert_pem)`. `pki.read_identity`, dann `_verify_ca_signed` (`:57`) gegen die
  Zwischenzertifikate des Scopes, Generation des Scopes zurück. Kein Register-, kein DB-Zugriff. Fehler →
  `IssuanceError`.
- `main.py`: `GET /trust` nach dem Muster von `/renew` (`:177`). Ohne `x-client-verify: SUCCESS` 401,
  `IssuanceError` 403. Antwort-Schema `TrustGeneration {generation}` mit Muster `^[0-9a-f]{64}$`.
- Tests:
  - fester Testvektor (zwei Zertifikate, ihre Generation wörtlich), dieselben Bytes später in Agent und Desktop;
  - Generation gleich dem Hash der `chain`, die `/renew` im selben Zustand liefert, je Scope;
  - Wechsel nach `rotate-intermediates`, nach `stage` und nach `switch` (Neustart simuliert);
  - PEM mit CRLF und Leerzeilen ergibt dieselbe Generation;
  - 401 ohne Header, 403 bei fremdem, abgelaufenem und scope-losem Zertifikat;
  - Schemathesis deckt die Route ab (Ausnahme nur mit Grund in `schemathesis_exclude.toml`).
Verify: bash scripts/dev/verify.sh ca-issuer --strict
Doku: → T6

### T2 — Gateway: Location `= /ca/trust` mit eigener Zone  [ ]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py
Änderung:
- `nginx.conf`: `limit_req_zone $binary_remote_addr zone=trust` neben `zone=renew` (`:69`). Im :443-Block neben
  `= /ca/renew` (`:110`) die Location `= /ca/trust` mit `limit_req zone=trust`, kleinem `client_max_body_size` und
  `proxy_pass http://issuer/trust`. Die Identity-Header erbt sie vom Server-Block, kein eigenes `proxy_set_header`.
- Rate und Burst legt die Task fest und begründet sie in `## Entscheidungen`. Maßstab: viele Agents hinter einer
  NAT-Adresse, je Agent eine Anfrage alle 300 s.
- Test über den Konfigurations-Parser der Datei (`_servers`, `_args`): die Location steht nur im :443-Block, nicht
  auf der Enrollment-Ebene; Zone und `proxy_pass` wie oben; keine Header-Überschreibung in der Location.
  Die Container-Tests derselben Datei belegen, dass nginx die Konfiguration lädt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py tests/test_identity_header_contract.py
Doku: → T6
Abhängt von: T1

### T3 — Agent: Generation vor jeder Erneuerungsentscheidung  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/renew.go, apps/agent/internal/enroll/renew_test.go, apps/agent/internal/enroll/trust.go (neu, SPDX), apps/agent/internal/enroll/trust_test.go (neu, SPDX), apps/agent/cmd/adminhelper-agent/run.go, apps/agent/cmd/adminhelper-agent/run_test.go
Änderung:
- `trust.go`: Hash eines PEM-Bündels wie in T1, und `GET <base>/ca/trust` über den mTLS-Client
  (`httpclient.NewMTLS`). 404 heißt „Server kennt die Route nicht“, kein Fehler.
- `MaybeRenew` (`renew.go:101`): ist `renewalDue` nicht fällig, fragt er die Generation. Weicht sie vom Hash des
  `ca.crt` ab, erneuert er. Unter `LockIdentity` liest er `ca.crt` erneut und vergleicht noch einmal. Höchstens eine
  Erneuerung je Lauf. Weicht die Generation nach der Erneuerung weiter ab, Warnung. Die Abfrage bekommt eine Naht wie
  `renewFunc` (`:134`). Rückgabe nennt den Grund (halbe Laufzeit, Trust-Generation).
- `run.go:200` `maybeRenewIdentity`: Log mit Grund. 404 still, andere Fehler als Warnung, der Lauf geht weiter.
  `renewBudget` (60 s) bleibt.
- Tests: Testvektor aus T1 wörtlich; gleiche Generation → keine Erneuerung; abweichend → genau eine; 404, 429,
  Netzfehler → keine Erneuerung, Lauf geht weiter; Provisionierung ersetzt `ca.crt` vor der Sperre → keine
  Erneuerung; 50-%-Regel fällig → keine Abfrage.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestMaybeRenew|TestTrust|TestRenew|TestRun
Doku: → T6
Abhängt von: T1

### T4 — Desktop: Generation bei Anmeldung und stündlich  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/renewal.rs (neu, SPDX), apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs
Änderung:
- `enrollment.rs`: Hash von `enroll|ca` wie in T1; `maybe_renew` (`:834`) fragt nach `needs_renewal` die Generation
  über `enrolled_client()` (`:1008`) und erneuert bei Abweichung über `renew` (`:800`). 404 still. Eine prozessweite
  `tokio::sync::Mutex` um `maybe_renew`.
- `renewal.rs`: Stunden-Task je Anmeldung. Epoche wie `notifications.rs` (`StreamState`); er endet, wenn eine neuere
  Anmeldung die Epoche erhöht oder `SessionState::ensure_signed_in` (`session.rs:136`) scheitert. Intervall und
  Erneuerung als Parameter, damit Tests ohne `tokio` `test-util` laufen.
- `auth.rs:108` / `commands.rs:560`: nach erfolgreicher Anmeldung `maybe_renew` wie heute, dann den Task starten.
  Der Kommentar `auth.rs:100–107` („the only renew trigger“) wird angepasst. `main.rs`: Modul und State.
- Tests: Testvektor aus T1 wörtlich; gleiche Generation → keine Erneuerung; abweichend → Erneuerung; 404 → keine;
  zwei gleichzeitige Aufrufe erneuern einmal; der Task tickt, endet nach Abmeldung und nach einer neuen Anmeldung
  (alter Task tickt nicht mehr).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T6
Abhängt von: T1

### T5 — Stack-Tests: Generation im echten Stack  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh, scripts/tests/agent_monitoring_test.sh
Änderung:
- `integration_stack_test.sh` `ca_rotation` (`:1454`): vor der Rotation ist `/ca/trust` gleich dem Hash der `chain`
  aus `/ca/renew`; nach `rotate-intermediates` und Neustart weicht sie ab; nach der Erneuerung (`renew_into`,
  `:1569`) ist sie gleich dem Hash der neuen `chain`. Ohne Client-Zertifikat kein Durchlass.
- `agent_monitoring_test.sh`: nach `run --once` zeigt das Gateway-Log `GET /ca/trust` mit 200, und der Agent hat nicht
  erneuert.
- Beweis außer `Verify:`: Stack-Job per Dispatch und `agent-monitoring` auf der VM (Kopf `Heavy:`), Ergebnis im Ledger.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T6
Abhängt von: T1, T2, T3

### T6 — Doku DE+EN, ADR-Nachtrag, CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/benutzer.html, docs/en/admin/users.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/index.html, docs/en/developer/index.html, docs/adr/0001-unified-pki-and-secure-deployment.md, changelog.d/arch-ca-trust-generation.md
Änderung: Die Stellen aus „Doku-Impact“ der Spec, DE und EN gleich: Wartezeiten im Runbook (Agents im nächsten Lauf,
Desktops bei Anmeldung oder stündlich, offline gebliebene Geräte bleiben das Kriterium in `status`), Erneuerung des
Geräte-Zertifikats, Troubleshooting, Route `/trust` des ca-issuer, ADR 0001 §3.3 als datierter Nachtrag,
Changelog-Fragment (`### Added`, `### Changed`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5

## Entscheidungen
- 2026-11-09 Kevin: Vertrag ist eine Route am ca-issuer, `GET /ca/trust` auf :443 hinter dem Gateway, mTLS, Scope aus
  dem Client-Zertifikat, Antwort `{"generation": "<hex>"}`. Generation = SHA-256 über die DER-Bytes der
  `chain`-Zertifikate in ihrer Reihenfolge. Agent (`ca.crt`) und Desktop (`enroll|ca`) vergleichen und erneuern sofort
  bei Abweichung. Der Agent prüft in jedem Lauf. Server und Web bleiben unverändert.
- 2026-11-09 Kevin: Desktop prüft beim Login und stündlich, solange eine Sitzung offen ist (Generation und
  50-%-Regel, `maybe_renew`), als Hintergrund-Task mit Tests.
- 2026-11-09 Session: Der Agent fragt `/ca/trust` nur, wenn die 50-%-Regel nicht fällig ist. 404 still (alter
  Server), andere Fehler als Warnung, Lauf geht weiter. Unter `LockIdentity` erneut gegen `ca.crt` vergleichen.
  Höchstens eine Erneuerung je Lauf; weicht die Generation danach weiter ab, Warnung statt Schleife.
- 2026-11-09 Session: Hash nur über `CERTIFICATE`-Blöcke, DER verkettet, SHA-256, hex klein. Der ca-issuer rechnet
  aus den Zertifikaten in `trust_bundle` (eine Quelle für `chain` und Generation). Fester Testvektor wörtlich in den
  Tests von ca-issuer, Agent und Desktop.
- 2026-11-09 Session: `trust_generation` im ca-issuer liest und prüft das Zertifikat selbst (`read_identity`,
  `_verify_ca_signed`), ohne Register und DB. 401 ohne `SUCCESS`, 403 bei `IssuanceError`.
- 2026-11-09 Session: Gateway bekommt eine eigene Zone `trust`; Rate und Burst legt T2 fest und trägt sie hier nach.
- 2026-11-09 Session: Desktop hält eine prozessweite `tokio::sync::Mutex` um `maybe_renew`. Der Stunden-Task trägt eine
  Epoche, weil `ensure_signed_in` eine neue Anmeldung desselben Nutzers am selben Server gelten lässt. Intervall als
  Parameter, keine neue `tokio`-Feature in den Dev-Abhängigkeiten.
