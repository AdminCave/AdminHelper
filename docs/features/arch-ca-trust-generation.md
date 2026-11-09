<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-ca-trust-generation — Clients erneuern sofort nach einem Wechsel des Vertrauens (R-1054)

## Problem / Motivation
Agent und Desktop übernehmen das Feld `chain` (Zwischenzertifikat und jede vertraute Root,
`apps/ca-issuer/app/issuer.py:128`, `Intermediate.trust_bundle` in `apps/ca-issuer/app/storage.py:104`) nur bei ihrer
Erneuerung. Sie erneuern bei halber Laufzeit des Leafs: der Agent in jedem Lauf ab 50 %
(`apps/agent/internal/enroll/renew.go:22`, `:101`), der Desktop nur bei der Anmeldung
(`apps/desktop/src-tauri/src/auth.rs:108`, `apps/desktop/src-tauri/src/enrollment.rs:834`). Nach
`rotate-intermediates` und nach jedem Schritt von `rotate-root` (R-1021) dauert es deshalb bis zu 45 Tage, online, bis
ein Gerät das neue Bündel trägt. Das Runbook empfiehlt 90 Tage Warten zwischen `stage`, `switch` und `finish`
(`docs/admin/betrieb.html`, Abschnitt `root-renewal`). Nach `rotate-intermediates --compromised` hält ein Gerät das
alte Zwischenzertifikat so lange als Anker. Ein Leaf, das mit dem geleakten Schlüssel signiert ist, kann es also bis
dahin täuschen. Den Wechsel schließt erst eine Erneuerung des Geräts.

Dazu kommt: Ein Desktop, der dauerhaft angemeldet bleibt, erneuert nie. Die Sitzung gleitet mit dem Refresh-Token
(`apps/server/app/core/config.py`, `REFRESH_TOKEN_EXPIRE_DAYS`), und der einzige Auslöser ist die Anmeldung.

## Ziel & Nicht-Ziele
Ziel (Entscheidungen Kevin 2026-11-09, siehe Ledger `## Entscheidungen`):
- **Vertrag `GET /ca/trust`** auf :443 hinter dem Gateway. Es gilt mTLS, der Scope kommt aus dem vorgelegten
  Client-Zertifikat, wie bei `/ca/renew`. Die Antwort ist `{"generation": "<64 hex>"}`.
- **Generation** = SHA-256 über die DER-Bytes der Zertifikate in `chain`, in ihrer Reihenfolge aneinandergehängt,
  kleingeschrieben hex. Sie gilt für den Scope des vorgelegten Zertifikats. DER grenzt sich selbst ab, deshalb ist die
  Verkettung eindeutig. PEM-Text, Zeilenenden und Leerzeilen zählen nicht. Die Generation ist ein reiner Inhalts-Hash:
  kein neuer Zustand, keine Migration. Sie ändert sich mit jedem Wechsel von `chain` (`rotate-intermediates`, `stage`,
  `switch`, `finish`, `abort`). Sie ist genau der Hash der `chain`, die ein `/ca/renew` in diesem Moment liefert.
- **Agent**: Ist die 50-%-Regel nicht fällig, fragt jeder Lauf (Timer 300 s, `apps/agent/systemd/*.timer`) die
  Generation ab. Er vergleicht sie mit dem Hash seines `ca.crt` (`CAPath`, schreibt `resp.Chain` wörtlich,
  `apps/agent/internal/enroll/enroll.go:213`). Weicht sie ab, erneuert er im selben Lauf über `/ca/renew`. Höchstens
  eine Erneuerung je Lauf.
- **Desktop**: Generation und 50-%-Regel prüft das Tauri-Backend bei der Anmeldung und stündlich, solange die Sitzung
  derselben Anmeldung offen ist. Verglichen wird mit dem Hash von `enroll|ca`
  (`apps/desktop/src-tauri/src/enrollment.rs:39`). Ein Hintergrund-Task je Anmeldung. Eine neue Anmeldung löst den
  alten ab; Abmeldung oder Ablauf der Sitzung beenden ihn.
- **Abwärtskompatibel**: Ein Client gegen einen alten Server bekommt 404 für `/ca/trust`. Das alte Gateway reicht den
  Pfad an die App, die kennt ihn nicht. Er übergeht das still und bleibt bei der 50-%-Regel. Ein alter Client fragt
  nicht und verhält sich wie heute.
- Komponenten: ca-issuer, Gateway, Agent, Desktop-Backend. Server und Web bleiben unverändert.

Nicht-Ziele (YAGNI):
- Kein Push und kein SSE-Kanal für Trust-Wechsel. Kein Feld im FRP-`config-hash` des Servers (Kevin: Route am
  ca-issuer statt Server).
- Kein Umbau der Laufzeiten, keine Änderung an `/ca/renew`, `/enroll` oder am Register.
- Browser-Zertifikate (`.p12`) erneuern sich nicht selbst. Sie bleiben beim Re-Export wie heute.
- Ob ein laufender frpc (Agent-Dienst, Desktop-Visitor) das erneuerte Zertifikat ohne Neustart übernimmt, ändert
  dieses Vorhaben nicht. Das Verhalten ist dasselbe wie nach einer 50-%-Erneuerung; der Desktop schreibt die
  Identitätsdateien beim nächsten Start des Visitors (`frpc.rs`, `load_identity`).
- Keine Server-Ampel und keine Web-Anzeige der Generation; `status` des ca-issuer bleibt das Kriterium der Abdeckung.

## Betroffene Komponenten & Dateien
- **ca-issuer**
  - `apps/ca-issuer/app/main.py:177` `/renew` ist die Vorlage für die neue Route `GET /trust`: Header
    `config.HEADER_VERIFY` (`config.py:165`) muss `SUCCESS` sein, sonst 401. Das Zertifikat kommt aus
    `config.HEADER_CERT` (`config.py:166`, URL-escaped). Fehler-Mapping wie dort: `IssuanceError` → 403.
  - `apps/ca-issuer/app/issuer.py`: neue Methode `trust_generation(verified_cert_pem)`. Sie liest die Identität
    (`pki.read_identity`, `pki.py:391`) und prüft das Zertifikat selbst gegen die Zwischenzertifikate seines Scopes
    (`_verify_ca_signed`, `issuer.py:57`). Dem Header allein vertraut sie nie (3.3). Sie gibt die Generation des
    Scopes zurück. Kein Register-Zugriff: Die Antwort trägt keine geheime Information, und die DB bekäme sonst alle
    fünf Minuten je Agent eine Anfrage.
  - `apps/ca-issuer/app/storage.py:84` `Intermediate`: neue Property `trust_generation`, berechnet aus den
    Zertifikaten, die `trust_bundle` (`:104`, `pki.chain_pem`, `pki.py:110`) enthält. So gibt es eine Quelle für
    `chain` und Generation. Der Wert wird je Scope beim Start einmal berechnet. Eine Rotation wirkt ohnehin erst nach
    einem Neustart des ca-issuer.
  - Tests: `apps/ca-issuer/tests/test_enroll_renew.py` (oder eine neue `tests/test_trust_generation.py`, SPDX),
    `tests/test_storage.py`, Schemathesis (`tests/test_schemathesis.py`, `schemathesis_exclude.toml`).
- **Gateway** `apps/gateway/nginx.conf`: neue Location `= /ca/trust` im :443-Block, neben `= /ca/renew` (`:110`).
  Sie bekommt `proxy_pass http://issuer/trust`, eine eigene Zone `limit_req_zone $binary_remote_addr zone=trust`
  (neben `zone=renew`, `:69`) und `client_max_body_size` klein (GET ohne Body). Die Identity-Header erbt sie wie
  `/ca/renew` vom Server-Block.
- **Agent**
  - `apps/agent/internal/enroll/renew.go`: `MaybeRenew` (`:101`) prüft nach `renewalDue` die Generation
    (`GET <base>/ca/trust` mit dem mTLS-Client aus `httpclient.NewMTLS`). Unter `LockIdentity` prüft er erneut gegen
    den dann gelesenen `ca.crt`. Eine Provisionierung, die die Sperre vorher hielt, kann das Bündel schon ersetzt haben.
    Neu ist eine Funktion für den Hash eines PEM-Bündels (nur `CERTIFICATE`-Blöcke, DER verkettet, SHA-256). Die
    Abfrage bekommt eine Naht wie `renewFunc` (`:134`).
  - `apps/agent/cmd/adminhelper-agent/run.go:200` `maybeRenewIdentity`: Log nennt den Grund der Erneuerung (halbe
    Laufzeit oder neue Trust-Generation). Das Budget der Phase (`renewBudget`, 60 s) bleibt.
  - Tests: `apps/agent/internal/enroll/renew_test.go`.
- **Desktop-Backend**
  - `apps/desktop/src-tauri/src/enrollment.rs`: `maybe_renew` (`:834`) prüft nach `needs_renewal` die Generation
    über `enrolled_client()` (`:1008`). Neu ist der Hash von `enroll|ca`. Eine prozessweite async-Sperre um
    `maybe_renew`, damit Anmeldung und Stunden-Task nicht gleichzeitig erneuern. `renew` (`:800`) und `store_identity`
    (`:298`, lädt Identität und HTTP-Client neu) bleiben.
  - Stunden-Task: gestartet nach erfolgreicher Anmeldung (`commands.rs:560` `login` bzw. `auth.rs:108`). Er ruft je
    Stunde `maybe_renew`, solange `SessionState::ensure_signed_in` (`session.rs:136`) dieselbe Anmeldung bestätigt
    und keine neuere Anmeldung ihn abgelöst hat (Epoche wie `notifications.rs` `StreamState`). Intervall und
    Erneuerung sind für Tests einsetzbar.
  - Kommentar in `auth.rs:100–107` („the only renew trigger“) wird wahr gemacht.
- **Stack-Test** `scripts/tests/integration_stack_test.sh`: im Ablauf `ca_rotation` (`:1454`) kommen hinzu: (a) vor
  der Rotation ist `/ca/trust` gleich dem Hash der `chain` aus `/ca/renew`; (b) nach `rotate-intermediates` und
  Neustart weicht sie ab; (c) nach der Erneuerung ist sie gleich dem Hash der neuen `chain`. Dazu ohne Zertifikat 401
  bzw. kein Durchlass (`MTLS_ENFORCE=true`).

## Datenmodell / API / Migrationen
- Keine Alembic-Migration, keine Tabelle, kein neuer Zustand auf Platte.
- Neu: `GET /trust` am ca-issuer (OpenAPI des ca-issuer), Antwort-Schema `TrustGeneration {generation: str}`
  (Muster `^[0-9a-f]{64}$`). Statuscodes: 200, 401 (kein verifiziertes Zertifikat), 403 (Zertifikat nicht von einem
  Zwischenzertifikat seines Scopes, abgelaufen, ohne Scope). Nach außen über das Gateway `GET /ca/trust`.
- Vertrags-Drift: Agent und Desktop rechnen die Generation selbst nach. Ein fester Testvektor (Kette aus zwei
  Zertifikaten und ihre Generation) steht wörtlich in den Tests von ca-issuer, Agent und Desktop. So rechnen alle drei
  dasselbe. Sonst droht eine Erneuerung in jedem Lauf.
- Server, Web, Tauri-IPC: unverändert.

## Externe Integrationen
- nginx `limit_req_zone`/`limit_req` (https://nginx.org/en/docs/http/ngx_http_limit_req_module.html): eine Zone je
  Zweck wie bei `enroll`/`renew`. Die Rate muss den Agent-Takt tragen: eine Anfrage je Agent alle 300 s. Viele Agents
  hinter einer NAT-Adresse teilen sich die Zone. 429 lässt der Agent wie jeden anderen Fehler fallen und versucht es im
  nächsten Lauf. Rate und Burst werden in der Task festgelegt und begründet.
- Kein FRP-, Tauri-IPC- oder VictoriaMetrics-Format berührt.

## Trade-offs & Alternativen
- **Route am ca-issuer (gewählt, Kevin 2026-11-09)** gegen **Feld im FRP-`config-hash` des Servers** und
  **nur Agent**:
  - Der Server müsste `chain` kennen. Heute liest er nur die Ausstellerliste (`ca-trust/<scope>.pem`, R-1009), nicht
    die Roots je Phase. Der config-hash existiert nur für Agents mit FRP-Tunnel, der Desktop hätte keinen Kanal.
  - Die Route am ca-issuer nimmt die Quelle von `chain` selbst. Die Generation kann also nie von dem abweichen, was
    `/ca/renew` liefert. Kosten: eine leichte Anfrage je Agent und Lauf (Zertifikat parsen, eine
    Signaturprüfung, keine DB).
- **Agent fragt nur ohne fällige 50-%-Regel**: spart die Anfrage, wenn ohnehin erneuert wird. Danach stimmt die
  Generation von selbst.
- **Desktop stündlich (gewählt) statt nur bei Anmeldung**: schließt zusätzlich die Lücke des Dauer-Desktops.
  Kosten: eine Anfrage je Stunde und Desktop.
- **Inhalts-Hash statt Zähler**: kein Zustand, der bei Restore, Backup oder einem halben Wechsel auseinanderlaufen
  kann. Ein Zähler bräuchte eine Migration im ca-issuer-Volume und Regeln für `abort`.

## Risiken & Rollback
- **Erneuerungs-Schleife**: Rechnen Client und ca-issuer die Generation verschieden, erneuert jeder Agent in jedem
  Lauf, und das Register wächst. Gegenmittel: der gemeinsame Testvektor, der Stack-Test (Generation nach der
  Erneuerung gleich), höchstens eine Erneuerung je Lauf. Ein Zertifikat, dessen Generation nach der Erneuerung
  weiter abweicht, protokolliert der Agent als Warnung.
- **Lastspitze nach einer Rotation**: Alle Agents erneuern im nächsten Lauf. Die Timer sind über die Startzeiten
  verteilt (`OnUnitActiveSec=300`), die `renew`-Zone (5 r/s je Adresse) bleibt. Was dort 429 bekommt, erneuert
  einen Lauf später.
- **Alter Server**: 404 wird still übergangen. Alle anderen Fehler loggt der Agent als Warnung, best-effort wie heute
  „Cert-Renew Fehler“. Der Lauf geht weiter.
- **Sicherheit**: Die Route verrät nur den Hash öffentlicher Zertifikate, die das Gateway ohnehin im Handshake zeigt.
  Der ca-issuer prüft das Zertifikat selbst. Ein Angreifer im Netz zwischen Gateway und ca-issuer (`pki`-Netz) könnte
  eine falsche Generation melden und so nur eine Erneuerung auslösen; die läuft über `/ca/renew` und bleibt so sicher
  wie heute.
- **Rollback**: Revert des Merge-Commits. Clients ohne Route fallen auf die 50-%-Regel zurück (404). Keine Daten
  zurückzunehmen.

## Doku-Impact
DE + EN: `docs/admin/betrieb.html` / `docs/en/admin/operations.html` (Zwischenzertifikate rotieren, Root erneuern:
Wartezeiten nach `stage`/`switch`, Agents im nächsten Lauf, Desktops bei Anmeldung oder stündlich, offline gebliebene
Geräte bleiben das Kriterium in `status`); `docs/admin/benutzer.html` / `docs/en/admin/users.html` (Erneuerung des
Geräte-Zertifikats); `docs/admin/troubleshooting.html` / `docs/en/admin/troubleshooting.html` (Agent erneuert auch
bei neuer Trust-Generation); `docs/admin/frp-tunnel.html:63`, `docs/admin/agent-deployment.html:182`,
`docs/developer/server.html:143`, `docs/developer/index.html` (Route `/trust` des ca-issuer), jeweils mit EN;
`docs/adr/0001-unified-pki-and-secure-deployment.md` §3.3 Nachtrag; `changelog.d/arch-ca-trust-generation.md`
(`### Added`, `### Changed`).

## Offene Fragen
Keine aus Kevins Bereich. Vertrag und Desktop-Auslöser hat Kevin am 2026-11-09 entschieden. Rate und Burst der
Gateway-Zone, Fehlerbehandlung und Testvektor entscheidet die Session in den Tasks und hält sie in
`## Entscheidungen` fest.
