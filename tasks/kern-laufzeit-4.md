# Laufzeit: Refresh-Cookie hinter dem Gateway — Task-Ledger
Status: geplant · Branch: feature/kern-laufzeit-4 · Review: am Ende
Spec: docs/features/kern-laufzeit-4.md (Roadmap R-1274)
Heavy: linux-full — Server-Auth-Route; der Sammellauf fährt die Web-Anmeldung über das Gateway
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1274: Refresh-Cookie Secure hinter dem Gateway  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/tests/test_auth.py, changelog.d/kern-laufzeit-4.md
Änderung: `_set_refresh_cookie` setzt `Secure` auch dann, wenn der direkte Peer das Gateway ist (`_from_gateway`) und `X-Forwarded-Proto` `https` lautet; den Peer fragt es nur, wenn der Header da ist. Tests in `TestRefreshCookie` (erst rot): Gateway-Peer mit `https` → Secure; ohne Header → nicht; fremder Peer mit Header (`identity_source`) → nicht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_auth.py
Doku: changelog.d/kern-laufzeit-4.md (die Entwickler-Doku beschreibt Secure schon)

## Entscheidungen
