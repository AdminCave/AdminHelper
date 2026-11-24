# kern-ca-13: Nachlese kern-config-1 (R-1747)

## Problem / Motivation

Zwei Nits aus der security-Prüfung von kern-config-1 (T2, T4), ohne Leck:

- `apps/ca-issuer/app/main.py` `_log_level`: Die Prüfung über `logging.getLevelName` lässt jeden registrierten
  Level-Namen durch. Unter uvicorn ist `TRACE` registriert und geht daher durch, obwohl die Meldung fünf Namen nennt.
  `docs/admin/betrieb.html:133` sagt: „ein anderer Wert bricht den Start ab“.
- `scripts/tests/sse_push_e2e.sh` wartet mit `curl -so /dev/null …/api/auth/me` auf die beiden Server. Ohne `-f`
  zählt auch ein 5xx als bereit, der Test startet dann gegen einen kaputten Server. Ein bloßes `-f` hilft nicht,
  weil die Route ohne Login 401 liefert und dann nie „bereit“ hieße.

## Ziel & Nicht-Ziele

- `_log_level` nimmt genau DEBUG, INFO, WARNING, ERROR und CRITICAL (Groß/klein egal). Alles andere bricht den Start ab.
- Die Warteschleife gilt als bereit bei einem HTTP-Status 1xx bis 4xx. Weder 5xx noch „keine Verbindung“ zählen.
- Nicht-Ziel: Server und Monitoring (eigene Level-Prüfung), andere Testskripte.

## Betroffene Komponenten & Dateien

`apps/ca-issuer/app/main.py`, `apps/ca-issuer/tests/test_logging.py`, `scripts/tests/sse_push_e2e.sh`.

## Datenmodell / API / Migrationen

Keine.

## Trade-offs & Alternativen

Eine feste Namensliste statt `getLevelName`, weil jedes Paket per `addLevelName` Namen registrieren kann. Für die
Warteschleife den Statuscode per `-w '%{http_code}'` lesen, statt eine Route ohne Auth zu suchen.

## Risiken & Rollback

Gering. Ein Start mit `LOG_LEVEL=TRACE` bricht künftig ab, so wie die Doku es beschreibt. Die Stack-Probe läuft in
der PR-CI (integration-stack) und im Sammellauf. Heavy linux-full wegen `apps/ca-issuer`.

## Doku-Impact

Keine: Die Doku beschreibt schon das Zielverhalten. Changelog: ein Fixed-Eintrag zum CA-Issuer.

## Offene Fragen

Keine.
