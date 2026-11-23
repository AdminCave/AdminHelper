# kern-events-1 — Server-Events erst nach dem Commit, einmal beim Start, begrenzte Warteschlange

Roadmap: R-0689 (REF, Code-Audit 2026-10-21, SRV-7).

## Problem / Motivation
- Rund 20 Handler in `apps/server/app/modules/*/router.py` feuern ihr Event von Hand nach `db.commit()`
  (`fire_event`, `app/core/events.py:70`). Die Regel „erst nach erfolgreichem Commit“ steht nur als Kommentar
  (`servers/router.py:299`, `frp/tunnel_router.py:420`, `frp/config_router.py:212`) und ist schon gebrochen:
  `users/router.py:199` feuert `user.deleted` vor `revoke_identity` und vor dem Commit. Scheitert einer der beiden,
  melden Hooks und Benachrichtigungen eine Löschung, die nie stattfand.
- `server.startup` feuert im Lifespan jedes Web-Workers (`app/main.py:439`), bei `WEB_CONCURRENCY=N` also N-mal; so
  steht es auch in `docs/developer/server.html:179`.
- Der Executor (`events.py:19`) hat eine unbegrenzte Warteschlange und wird beim Herunterfahren nicht beendet.

## Ziel & Nicht-Ziele
- **Outbox je Session:** `queue_event(db, type, data)` legt das Event in `db.info` ab. Ein Listener auf der Klasse
  `sqlalchemy.orm.Session` gibt es bei `after_commit` der Wurzel-Transaktion an den Executor; endet die
  Wurzel-Transaktion ohne Commit (Rollback, `close()`), verfällt es (`after_transaction_end`). Ein SAVEPOINT-Commit
  feuert nicht. Ein Fehler beim Abgeben wird geloggt, nie an `commit()` weitergereicht.
- Die Router rufen nur noch `queue_event`, und zwar vor dem Commit. Die Daten entstehen vorher, wo nötig nach
  `db.flush()` (`autoflush=False`, `app/core/database.py:40`); die Payloads bleiben gleich.
  `fire_event` bleibt für Quellen ohne Transaktion (`alert.triggered`, `server.startup`). `cli.py` nutzt
  ebenfalls `queue_event`.
- **`server.startup` einmal** (Kevin 2026-11-23): Es feuert der Scheduler-Prozess (`app/scheduler_main.py`) nach
  `scheduler.start()`, der genau einmal läuft. Die Web-Worker feuern es nicht mehr.
- **Begrenzte Warteschlange** (Kevin 2026-11-23): höchstens 1000 wartende Events; jedes weitere wird verworfen und
  als Warnung geloggt (Typ des Events, keine Daten). Beim Herunterfahren (Lifespan-Ende, Scheduler-Stopp) wartet der
  Prozess bis zu 10 s auf laufende Hooks, der Rest verfällt mit Warnung.
- **Nicht-Ziele:**
  - `audit.record` bleibt explizit nach dem Commit (best-effort, eigener Commit, Aufrufer ohne Event).
  - Keine neuen Events, keine geänderten Payloads, keine API- oder Migrationsänderung.

## Betroffene Komponenten & Dateien
Nur `apps/server`:
- `app/core/events.py`, `app/core/database.py` (Registrierung der Listener beim Import), `app/main.py` (Lifespan),
  `app/scheduler_main.py`, `app/cli.py`.
- Router: `modules/users/router.py`, `modules/connections/router.py`, `modules/servers/router.py`,
  `modules/ansible/router.py`, `modules/frp/tunnel_router.py`, `modules/frp/config_router.py`.
- Tests: neu `tests/test_events_after_commit.py`; `tests/test_event_whitelist.py` (Regex auf beide Namen plus eine
  Allowlist der Dateien, die `fire_event` noch rufen dürfen); bestehende Event-Tests (`test_users_promotion_event.py`
  u. a.) nach Bedarf.

## Datenmodell / API / Migrationen
Keine. Die Event-Payloads und die Audit-Zeilen bleiben gleich.

## Externe Integrationen
SQLAlchemy-Session-Events `after_commit` und `after_transaction_end`
(https://docs.sqlalchemy.org/en/21/orm/events.html#session-events). Laut Quelltext 2.1.9 feuert `after_commit` auch für
einen SAVEPOINT und `close()` nur `after_transaction_end`; nach `after_commit` ist kein SQL erlaubt (Probe des
`advisor`, sqlite). Vor T1 in der offiziellen Doku nachlesen.

## Trade-offs & Alternativen
- **Wächter statt Outbox** (ein Helfer nach dem Commit prüft, dass nichts Uncommittetes offen ist): fängt
  `delete_user` nicht (dort lief nur ein SELECT) und prüft nur Pfade, die ein Test trifft. Abgelehnt.
- **Audit in den Listener:** nach dem Commit ist kein SQL erlaubt, eine eigene Session fiele aus dem Test-Rollback.
  Abgelehnt.
- **`server.startup` per Redis-Lock:** Redis ist optional. Abgelehnt (Kevin 2026-11-23).
- **Reihenfolge:** Der Dispatch rückt vor die Nebenwirkungen nach dem Commit (`write_frps_config`,
  `remove_frps_config` in `frp/config_router.py`, `sync_policy` bei `user.created` und den Tunnel-Events). Ein Hook
  kann laufen, bevor `frps.toml` oder die Policy geschrieben ist. Hooks laufen schon heute asynchron, und
  `docs/developer/hooks.html` sagt nichts über die Reihenfolge.

## Risiken & Rollback
- **Verlorenes Event:** Wird ein Event nach dem Fach-Commit eingereiht, hängt es an der nächsten Transaktion und
  verfällt mit ihr. Ein Test je Aufrufstelle zeigt, dass Erfolg genau ein Event ergibt; die Allowlist hält
  `fire_event` aus den Routern.
- **Listener auf der Klasse `Session`:** Er trifft auch die Sessions des Schedulers und der Tests (`conftest.py`).
  Gewollt; ein Mechanismus-Test fährt das conftest-Muster (äußere Transaktion + SAVEPOINT).
- Rollback: jede Task ist ein Commit.

## Doku-Impact
`docs/developer/hooks.html` (DE+EN: `queue_event` statt `fire_event`, Zeitpunkt nach dem Commit, Deckel 1000,
Shutdown), `docs/developer/server.html:179` (DE+EN: `server.startup` einmal, vom Scheduler).
`changelog.d/kern-events-1.md` (Event-Hooks: `server.startup` einmal je Start; Events verworfener Transaktionen
feuern nicht mehr).

## Offene Fragen
- Die Reihenfolge-Verschiebung (Trade-offs): hinnehmen und im PR nennen? Empfehlung: ja.
