# kern-events-2 — verworfene Events sichtbar machen

Roadmap: R-1732 (REF). Quelle: security kern-events-1 2026-11-23, `apps/server/app/core/events.py:96`.

## Problem / Motivation
Ist die Event-Warteschlange voll (`MAX_PENDING` = 1000), verwirft `fire_event` jedes weitere Event mit je einer
Warnzeile (`events.py:103`). Bei einem Ansturm sind das tausende Zeilen, und kein Admin erfährt davon: mit dem Event
fallen die passenden Event-Hooks und die Benachrichtigungs-Brücke aus.

## Ziel & Nicht-Ziele
- **Ziel** (Kevin 2026-11-25, „Glocke + Sammel-Log“): je Ansturm eine Logzeile beim ersten verworfenen Event, danach
  eine Sammelzeile mit Anzahl und Event-Typen statt einer Zeile je Event; dazu eine Glocken-Notiz an alle Admins,
  höchstens eine je 15 Minuten, mit der Anzahl.
- Ein Ansturm ist das Fenster ab dem ersten verworfenen Event: 60 s lang zählt `fire_event` nur mit, dann schreibt ein
  Timer-Thread Sammelzeile und Notiz. Ein späteres Verwerfen öffnet ein neues Fenster.
- **Nicht-Ziele:** keine Migration, keine API-Änderung, kein Zähler in einer Statusseite, keine Änderung an
  `MAX_PENDING` oder am Verwerfen selbst.

## Betroffene Komponenten & Dateien
- `apps/server/app/core/events.py`: Zählung unter `_pending_lock`, Timer, Sammelzeile, Glocken-Notiz (wie
  `notify_hook_failure`, `apps/server/app/modules/hooks/script_runner.py:365`, über `notify_users`); `shutdown_events`
  schreibt eine offene Sammelzeile sofort (nur Log).
- `apps/server/tests/test_events_after_commit.py`: der Test zum Verwerfen erwartet künftig eine Zeile beim ersten
  Event statt einer je Event (gewollte Verhaltensänderung); neue Tests für Sammelzeile, Notiz und Entprellung.

## Datenmodell / API / Migrationen
Keine. Die Notiz ist eine Zeile der bestehenden Tabelle `notification`: `event_type` `server.events.dropped`,
Schwere `warning`, Kategorie `hooks` (wie die Hook-Glocke), Titel `Events dropped: event queue full`, Text mit
Anzahl und Typen. Die Entprellung liest die letzte Notiz dieses Typs aus der Datenbank, so gilt sie über Prozesse.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- Timer statt Zusammenfassung beim nächsten erfolgreichen Event: nach einem Ansturm kommt nicht zwingend ein Event.
- Die Notiz entsteht im Timer-Thread mit eigener Session, nie im Thread des Aufrufers (`after_commit` eines Requests).
- Zwei Prozesse können im selben Fenster je eine Notiz schreiben (die Entprellung liest, ohne zu sperren), hingenommen
  wie bei der Hook-Glocke.

## Risiken & Rollback
Gering; Revert des Task-Commits. Scheitert die Notiz (Datenbank weg), steht nur die Sammelzeile im Log.

## Doku-Impact
`docs/developer/hooks.html` (Absatz zur Warteschlange) und `docs/admin/betrieb.html` (Logger `app.core.events`),
jeweils DE + EN; `changelog.d/kern-events-2.md`.

## Offene Fragen
Keine.
