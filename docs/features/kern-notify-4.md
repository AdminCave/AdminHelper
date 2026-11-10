# Benachrichtigungen: Zielprüfung, Sperrreihenfolge, Zusammenfassung (kern-notify-4)

Roadmap: R-1178, R-1179, R-1149, R-1188 (Kevin 2026-11-09 Triage, vor 0.47.0). R-1147, R-1180, R-1186 und R-1187
fahren nicht mit: Sie brauchen eine Entscheidung Kevins (sichtbares Verhalten, API, oder ob die Zeile schon erledigt
ist) und wandern nach `tasks/kern-notify-5.md`.

## Problem / Motivation
- **R-1178, R-1179:** Die Zielprüfung für ausgehende Anfragen (`apps/server/app/core/ssrf.py`, Kopie
  `apps/monitoring/app/core/ssrf.py`) wird um zwei Adressbereiche ergänzt.
- **R-1149:** Eine Erholung sperrt zuerst die aktiven Vorfälle ihrer Schlüssel (`_containing`, nach id) und danach in
  `_note_stale` behobene Vorfälle, die eine kleinere id haben können (`incidents.py:368-400`). `POST /incidents/ack`
  sperrt aufsteigend und hält auch die Zeilen, die es überspringt (`router.py:229-243`). Beide zusammen können sich
  gegenseitig blockieren; Postgres bricht dann eine Seite ab (500 oder verlorene Erholung). Für die Serialisierung
  über `_lock` (Advisory-Lock) fehlt ein Test mit zwei echten Verbindungen.
- **R-1188:** Die Zusammenfassungs-Mail (`digest.py:_send`) schreibt jede wartende Zeile in eine Mail, ohne Obergrenze.

## Ziel & Nicht-Ziele
Ziel: die vier Zeilen beheben, je mit Test. Nicht-Ziele: keine neue Einstellung, keine Änderung an Ping, Feed oder
Eskalation; die vier verschobenen Zeilen.

## Betroffene Komponenten & Dateien
- Server: `app/core/ssrf.py`, `app/modules/notifications/incidents.py`, `router.py`, `digest.py`, Tests daneben.
- Monitoring: `app/core/ssrf.py` (gleich zum Server, `test_ssrf_parity.py`), Tests.
- Doku: `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `docs/developer/server.html`,
  `docs/en/developer/server.html`.

## Datenmodell / API / Migrationen
Keine Migration, keine Änderung an Routen oder Schemas.

## Externe Integrationen
Python `ipaddress` (3.13), Klassifikation der Adressbereiche.

## Trade-offs & Alternativen
- **R-1178, R-1179:** je Bereich die vorhandene Einordnung (privat und freigebbar, oder immer gesperrt), gleich
  in beiden Kopien.
- **R-1149:** (a) Die Erholung sperrt alle Vorfälle, die sie anfassen kann (aktive und den letzten behobenen je
  Schlüssel), in einer Abfrage nach id, bevor sie etwas ändert; (b) `ack` prüft ohne Sperre vor und sperrt nur, was
  es bestätigen kann. Wahl: beides; (a) stellt die globale Reihenfolge her, (b) hält keine übersprungenen Zeilen.
- **R-1188:** Obergrenze von 200 Zeilen je Mail, dahinter eine Zeile „… and N more“; alle Einträge gelten als
  versandt (die Glocke zeigt sie). Alternative: mehrere Mails. Wahl: eine Mail, die Glocke bleibt die volle Liste.

## Risiken & Rollback
Jede Task ein Commit, einzeln zurücknehmbar. R-1149 ändert die Sperrfolge einer heißen Stelle: Die Tests fahren
zwei echte Verbindungen.

## Doku-Impact
Admin-Doku Benachrichtigungen (gesperrte Bereiche, Liste ergänzt) DE+EN, Entwicklerdoku Server (Erholung, Zusammenfassung) DE+EN,
`changelog.d/kern-notify-4.md` neutral.

## Offene Fragen
Keine für diese vier Zeilen; die Fragen zu R-1147, R-1180, R-1186 und R-1187 gehen gesammelt an Kevin.
