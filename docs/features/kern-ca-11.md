# CA-Issuer: Register der kompromittierten Zwischenzertifikate, Gleichstand im finish (kern-ca-11)

Roadmap: R-1113, R-1116 (Kevin 2026-11-09 Triage, vor 0.47.0).

## Problem / Motivation
- **R-1113:** `rotate-intermediates --compromised` leert `<scope>-retired.pem` des Scopes, führt die verworfenen
  Zwischenzertifikate aber nirgends dauerhaft (während einer Root-Erneuerung nur den Scope in
  `Switch.compromised`). Start (`storage.ensure_hierarchy`), Rotation und `status` sollen ein verworfenes
  Zwischenzertifikat bis zu seinem Ablauf erkennen.
- **R-1116:** `_query_register` (`apps/ca-issuer/app/cli.py:483`, Vergleich `:497`) wählt je Gerätelinie das
  neueste Zertifikat über `not_before`; bei zwei Zertifikaten derselben Sekunde entscheidet die Zeilenreihenfolge
  der Datenbank. `rotate-root finish` kann ein Gerät dann als ausstehend zählen (nur konservativ: finish wird
  zurückgehalten).

## Ziel & Nicht-Ziele
Ziel: ein mit `--compromised` verworfenes Zwischenzertifikat bleibt verworfen, bis es abläuft; der Gleichstand im
Register ist deterministisch. Nicht-Ziele: keine neue Option, keine Änderung an Trust-Bundles, Routen oder
Datenbank, kein Ersatz für `Switch.compromised`.

## Betroffene Komponenten & Dateien
- `apps/ca-issuer/app/rotation.py`: `_plan_scope` (`:392`) liefert bei `compromised` die verworfenen Zertifikate
  (das ersetzte und die Einträge des Retired-Files), `_write_scope` (`:429`) schreibt sie vor dem Retired-File in
  `<scope>-compromised.pem` (bisherige Einträge plus neue, abgelaufene fallen heraus, je Schlüssel einmal);
  `_retired_after` (`:535`) und `_retired_under` (`:572`) behalten keinen Eintrag mit einem Schlüssel aus dem
  Register.
- `apps/ca-issuer/app/storage.py`: `ensure_hierarchy` (`:132`) liest das Register; ein `<scope>.crt` mit einem
  Schlüssel daraus stoppt den Start (Hinweis: erneut `rotate-intermediates --compromised <scope>`);
  `_load_retired` (`:364`) überspringt solche Einträge mit WARNING wie andere ungültige.
- `apps/ca-issuer/app/cli.py`: `_show_retired` (`:205`) markiert sie `SKIPPED (compromised)`, `_show_current`
  markiert ein `<scope>.crt` aus dem Register; `_query_register` (`:483`) entscheidet den Gleichstand über
  `created_at`.
- Tests: `apps/ca-issuer/tests/test_rotation.py`, `test_storage.py`, `test_cli.py`.
- Doku: `docs/admin/betrieb.html`, `docs/en/admin/operations.html` (Abschnitt Zwischenzertifikate rotieren),
  `changelog.d/kern-ca-11.md`.

## Datenmodell / API / Migrationen
Neue optionale Datei `<scope>-compromised.pem` im Volume `ca-pki` (PEM-Zertifikate ohne Schlüssel). Fehlt sie,
gilt das Register als leer (Altbestand). Keine Datenbank-, API- oder Vertragsänderung.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **Abgleich über den öffentlichen Schlüssel** (SubjectPublicKeyInfo), nicht über das Zertifikat: verworfen ist
  der Schlüssel; ein neu ausgestelltes Zertifikat desselben Schlüssels gilt ebenso nicht.
- **Rotation verwirft einen Register-Eintrag im Retired-File still**, statt wie bei fremden Einträgen abzubrechen:
  hier ist die Entscheidung schon gefallen (`--compromised`), ein Abbruch hätte keinen anderen Ausgang.
- **Alternative** Scope-Marker wie `Switch.compromised` ohne Erneuerung: verworfen, ein Marker je Scope sperrte
  auch spätere, gültige Zwischenzertifikate oder bräuchte doch die Zertifikate.
- **R-1116:** Ordnung `(not_before, created_at)`; die Alternative `id` hängt an der Vergabe der Primärschlüssel.

## Risiken & Rollback
Ein Register-Eintrag wirkt nur auf Zertifikate desselben Schlüssels. Ein falsch gefülltes Register stoppt
höchstens den Start mit Meldung und Ausweg. Rollback: Revert des PR; die Datei bleibt liegen und wird dann
nicht mehr gelesen.

## Doku-Impact
`betrieb.html`/`operations.html`: `--compromised` führt die verworfenen Zwischenzertifikate in
`<scope>-compromised.pem`; Start, Rotation und `status` behandeln sie wie oben. CHANGELOG über
`changelog.d/kern-ca-11.md`.

## Offene Fragen
Keine.
