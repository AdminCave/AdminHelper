<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Client-Zertifikat und angemeldeter Benutzer gehören zusammen — Task-Ledger
Status: aktiv · Branch: feature/cert-user-binding · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-10 (Kevin hat die Entscheidungen zu R-0223 am 2026-10-10 an die Aufsicht übergeben: „Entscheide du“; Richtung und sichtbares Verhalten wie dort entschieden, Bootstrap mit gebunden; Multibox-Lauf vor dem Merge)
Spec: Roadmap R-0223
Heavy: linux-full + scenario --enforce --desktop — Auth- und mTLS-Pfad des Servers: `run.sh integration` (Gateway mit `MTLS_ENFORCE`, Login mit Client-Zertifikat) und `run.sh e2e` (Desktop-Login, Registrieren, Tunnel) auf einer Pool-VM; dazu vor dem Merge ein Multibox-Lauf `--enforce --desktop`, weil die Prüfung nur mit echtem mTLS über das Gateway greift. Der Multibox-Lauf ist ask-first, die Aufsicht holt ihn.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, svelte-check, ESLint und Prettier sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Die Richtung ist entschieden (Kevin hat die
Designfragen am 2026-10-10 an die Aufsicht übergeben, sie hat wie empfohlen entschieden). Zeilenangaben origin/main@38990d6a.

**Die Funktion:** Unter mTLS gehört das Client-Zertifikat dem angemeldeten Benutzer. Login, API und Zertifikats-Ausgabe
prüfen das.
- **Die Regel:** Ist die Identität am Gateway verifiziert (`X-Client-Verify: SUCCESS`), muss ihr Scope `access` sein und ihr
  CN der Username des Benutzers, mit dem die Anfrage arbeitet. Sonst antwortet der Server mit 403 und dem Code
  `ERR_CERT_USER_MISMATCH`.
- **API-Key-Zugänge** sind an keinen Benutzer gebunden (`ApiKey` hat keinen) und bleiben, wie sie sind.
- **Ohne verifizierte Identität** (permissiver Modus ohne Zertifikat) gibt es nichts zu prüfen.
- **Folgen, die die Doku nennt:**
  - Jeder Benutzer nutzt sein eigenes Zertifikat. Eine `.p12` exportiert jeder für sich.
  - Ein Desktop ist einem Benutzer zugeordnet. Wer sich dort als ein anderer Benutzer anmelden will, setzt die
    Geräte-Identität zurück und registriert das Gerät neu.

### T1 — Server: Login, API und Zertifikats-Ausgabe verlangen ein Zertifikat des angemeldeten Benutzers (R-0223)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/core/auth.py, apps/server/app/modules/users/auth_router.py, apps/server/app/modules/notifications/stream.py, apps/server/tests/test_cert_user_binding.py, apps/server/tests/test_mtls_scope.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @ec77c47c 2026-10-10T17:04:12+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Ein Helfer in `identity.py` (neben `get_client_identity`, `:71-94`) prüft eine verifizierte Identität gegen einen
Username. Er gibt 403 mit `ERR_CERT_USER_MISMATCH: …` und einem lesbaren englischen Satz zurück. Er greift überall, wo ein
Benutzer aus einem JWT oder aus Zugangsdaten entsteht:
- `get_current_user` (`auth.py:212-229`). Darüber laufen alle JWT-Routen, auch die beiden Routen der Zertifikats-Ausgabe
  `POST /api/enrollment/token` und `/token/for` (`modules/enrollment/router.py:51-71`, `:79-114`; bei `/token/for` ist es
  das Zertifikat des Admins).
- Der Bearer-Zweig des kombinierten Zugangs (`auth.py:263-…`, Benutzer ab `:284`), nur wenn der Benutzer entscheidet,
  nicht der API-Key.
- Das Öffnen des SSE-Streams (`authenticate_stream_user`, `modules/notifications/stream.py:56-80`). Der Reauth
  (`_stream_reauth_ok`, `:36-53`) bleibt: Zertifikat und Token eines offenen Streams ändern sich nicht.
- Login (`modules/users/auth_router.py:117`): Geprüft wird der eingegebene Username, nach der Ratenbegrenzung und **vor**
  der Passwortprüfung, damit das Ergebnis nichts über das Passwort sagt. Ein Audit-Eintrag wie bei einem
  fehlgeschlagenen Login.
- Refresh (`:165`, Benutzer ab `:202`) und Bootstrap (`:266`, der neu anzulegende Username).

Tests in einer neuen Datei `tests/test_cert_user_binding.py` (SPDX-Header), mit `MTLS_ENFORCE=True` und den
Gateway-Headern wie in `test_mtls_scope.py` (`_gateway_headers`, `:59-60`). Sie decken ab:
- **Zugelassen:**
  - eigenes Zertifikat + JWT ⇒ 200;
  - API-Key + Zertifikat eines Benutzers ⇒ wie bisher;
  - permissiv ohne Zertifikat ⇒ wie bisher.
- **Abgelehnt mit 403 `ERR_CERT_USER_MISMATCH`:**
  - Zertifikat eines anderen Benutzers + JWT auf einer API-Route;
  - dasselbe an `POST /api/enrollment/token`;
  - ein Zertifikat mit Scope `tunnel` + JWT an `POST /api/enrollment/token`.
- **Login:**
  - Zertifikat eines anderen Benutzers ⇒ 403, mit richtigem und mit falschem Passwort gleich;
  - eigenes Zertifikat ⇒ 200.
- **Refresh, SSE-Öffnen und Bootstrap:** mit fremdem Zertifikat 403.
- **Rot vor dem Fix:** alle 403-Fälle.

In `test_mtls_scope.py` schickt `test_enforced_admin_route_passes_with_access_cert` (`:254-261`) ein Zertifikat mit dem
Default-CN `user-01` und ein JWT von `admin` und erwartet 200. Der Test bekommt ein Zertifikat mit dem CN des JWT-Benutzers.
Die Erwartung 200 bleibt. `test_bootstrap_route_stays_open_under_enforcement` (`:285-292`) schickt kein Zertifikat und
bleibt unverändert.

CHANGELOG unter `[Unreleased]` → `### Changed`, neutral: „Unter mTLS gehört das Client-Zertifikat dem angemeldeten
Benutzer; Login, API und Zertifikats-Ausgabe prüfen das. Jeder Benutzer nutzt sein eigenes Zertifikat.“
Assertion-Änderung: apps/server/tests/test_mtls_scope.py::test_enforced_admin_route_passes_with_access_cert — das Zertifikat trägt künftig den CN des JWT-Benutzers, die Erwartung 200 bleibt
Beweis: origin/main@38990d6a:
- CN und JWT-Benutzer werden heute nicht verglichen. `get_current_user` lädt den Benutzer aus dem JWT (`auth.py:212-229`,
  `_get_user_from_token` `:82`). `require_scope` prüft Verifizierung, Scope und Widerruf (`identity.py:129-131`).
- `grep -rn 'identity.cn' apps/server/app` findet den CN nur in `identity.py` und `modules/notifications/stream.py`.
- `test_mtls_scope.py:254-261` erwartet 200 für CN `user-01` mit JWT `admin`.
HEAD: 38990d6a
Semantik:
- `docs/admin/benutzer.html:90`: „Der spätere Zertifikats-CN ist genau dieser Username.“
- ADR 0001 D3 (`docs/adr/0001-unified-pki-and-secure-deployment.md:82`): „Geräte-Cert als zweiter Faktor neben
  Passwort/JWT“.

Dass der zweite Faktor zum Benutzer gehört, sagt keine Stelle ausdrücklich; die Entscheidung legt es fest, T3 schreibt es
in Doku und ADR.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cert_user_binding.py tests/test_mtls_scope.py tests/test_stream.py tests/test_enrollment_mint.py
Doku: CHANGELOG.md (Changed); Benutzer-Doku und ADR in T3

### T2 — Desktop: der Login erklärt `ERR_CERT_USER_MISMATCH` und bietet das Zurücksetzen der Geräte-Identität an (R-0223)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/lib/utils/errors.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/Login.binding.test.ts, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @d858a89b 2026-10-10T17:18:09+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Der Login liest Codes aus seinem eigenen Fehlertext (`Login.svelte:52-57`) und zeigt die Meldung ohne Code
(`displayError`, `:59`). Neu kommt `ERR_CERT_USER_MISMATCH` dazu:
- **Hinweis:** „Dieses Gerät ist für einen anderen Benutzer registriert. Melde dich als dieser Benutzer an, oder setze die
  Geräte-Identität zurück und registriere das Gerät für dich.“ DE und EN in `dictionaries.ts`.
- **Aktion:** das bestehende Zurücksetzen der Geräte-Identität, wie beim CA-Pin-Fall (`:52`, `:71`).
- **Code-Liste:** `withoutErrorCodes` (`lib/utils/errors.ts:13`) kennt den Code, damit ihn weder Login noch Statusleiste
  zeigen.
- **Desktop-Backend:** keine Änderung. Es reicht den Body des 403 unverändert durch; `redact_body` maskiert nur Tokens
  (`apps/desktop/src-tauri/src/diagnostics.rs:69-77`).

Neuer Komponententest `Login.binding.test.ts` (SPDX-Header) nach dem Muster von `Login.mtls.test.ts`:
- Ein Login, der mit `ERR_CERT_USER_MISMATCH: …` scheitert, zeigt den Hinweis und das Zurücksetzen.
- Er zeigt den Code nicht.
- Ein anderer Fehler zeigt den Hinweis nicht.
- Rot vor dem Fix.

Doku in `troubleshooting.html` DE+EN, neben dem Eintrag zum fehlenden Gerätezertifikat (DE `:74`, EN `:76`): was die Meldung
bedeutet und was zu tun ist.

Das Web-Panel zeigt den `detail`-Text des Servers wie bei jedem Login-Fehler (`apps/web/src/lib/api/client.ts:129-137`,
`apps/web/src/pages/Login.svelte:22-28`). Der Satz aus T1 ist lesbar. Ein eigener Hinweis im Web ist nicht im Umfang.
Beweis: origin/main@38990d6a `grep -n 'ERR_' apps/desktop/ui/src/components/Login.svelte` → nur die drei bisherigen Codes
(`:52-57`, `:137`); `ERROR_CODES` (`errors.ts:13`) kennt `ERR_CERT_USER_MISMATCH` nicht.
HEAD: 38990d6a
Semantik: `docs/admin/troubleshooting.html:74` beschreibt den Login-Hinweis zu `ERR_MTLS_CERT_REQUIRED` (R-0222). Der neue
Hinweis folgt demselben Muster.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/troubleshooting.html + docs/en/admin/troubleshooting.html
Abhängt von: T1

### T3 — Doku: ein Zertifikat je Benutzer, ein Desktop je Benutzer, ADR präzisiert (R-0223)  [ ]
Komponente: scripts · Dateien: docs/admin/benutzer.html, docs/en/admin/users.html, docs/adr/0001-unified-pki-and-secure-deployment.md, docs/adr/0002-phase-a-task-plan.md
Änderung: Die Benutzer-Doku und die ADRs sagen, was seit T1 gilt.
- `benutzer.html:84` („Verteile die `.p12` also an jeden, der das Panel im Browser nutzt.“), EN `users.html:78`: Jeder
  Benutzer exportiert seine eigene `.p12` aus seinem Desktop.
- `benutzer.html:90`, EN `users.html:84`: Unter mTLS gehört das Zertifikat diesem Benutzer. Ein Desktop ist einem Benutzer
  zugeordnet; wer sich dort als ein anderer anmelden will, setzt die Geräte-Identität zurück und registriert neu.
- ADR 0001, Zeile D3 (`:82`): ein Nachtrag, dass der zweite Faktor zum angemeldeten Benutzer gehört (CN = Username des JWT
  bei verifizierter Identität). API-Key-Zugänge bleiben ungebunden.
- ADR 0002, Absatz A3 (`:133-151`):
  - „orthogonal zu JWT/API-Key“ wird präzisiert: getrennte Module, aber gebunden.
  - „Bewusst offen gelassen … `auth_router` (Login/Bootstrap)“ (`:149-151`) nennt die Bindung an Login und Bootstrap.
  - Aus R-0281 nur, was in diesem Absatz steht: „`MTLS_ENFORCE` (Default `false` …)“ (`:141`), der Default ist seit 0.29.0
    `true` (`apps/server/app/core/config.py:135`).
  - Die übrigen Punkte von R-0281 (ADR 0001 `:26-29`, ADR 0002 `:216`, `:228`) stehen in anderen Absätzen und bleiben
    draußen.
Beweis: origin/main@38990d6a `sed -n 84p docs/admin/benutzer.html` → „Verteile die `.p12` also an jeden, der das Panel im
Browser nutzt.“; `sed -n 141p docs/adr/0002-phase-a-task-plan.md` → „`MTLS_ENFORCE` (Default `false`, `core/config.py`)“;
`grep -n 'MTLS_ENFORCE' apps/server/app/core/config.py` → Default `true` (`:135`).
HEAD: 38990d6a
Semantik: die Entscheidung zu R-0223 (Bindung); der Rest beschreibt, was T1 und T2 tun.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/benutzer.html + docs/en/admin/users.html · docs/adr/0001 und 0002 (die Task ist die Doku)
Abhängt von: T1
