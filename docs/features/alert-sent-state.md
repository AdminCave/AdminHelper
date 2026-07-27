# Sent-State-Tracking für den Monitoring-Alerter

Folge-Vorhaben aus `tasks/monitoring-overhaul.md` T47 (Review-Findings F1/F2/F7
des Abschluss-Reviews von `feature/monitoring-overhaul`, PR #4).

## Problem / Motivation

Der Alerter ist rein **transitionsbasiert**: `process_alert` feuert nur, wenn
`old_status != new_status`, und es gibt kein Gedächtnis, ob für einen Zustand je
eine Benachrichtigung real versendet wurde. Die im Overhaul eingeführten
Suppression-Ebenen (unknown-Policy, Maintenance collect-but-mute,
Host-down-Inhibition) sind dadurch **edge-triggered** — mit drei bestätigten
Fehlerbildern:

- **F1 (Host-down):** Geht ein Check *während* eines Host-Ausfalls auf
  `critical` und **bleibt** es nach der Agent-Recovery, entsteht nie wieder eine
  Transition → der Vorfall wird **nie** gemeldet. Erholt er sich später, geht
  eine RECOVERY für einen nie gemeldeten Alert raus.
- **F2 (Maintenance):** Eine `critical → ok`-Recovery *im* Fenster für einen
  *vor* dem Fenster gesendeten Alert wird verschluckt — Ticket-/On-Call-Systeme
  halten den Incident ewig offen. Ein Problem, das das Fensterende überdauert,
  wird ebenfalls nicht nachgemeldet.
- **F7 (unknown-Flapping):** `ok → unknown → ok` erzeugt bei jedem Zyklus eine
  RECOVERY-Meldung für einen Incident, der nie gemeldet wurde (Transitionen
  *nach* unknown sind stumm, `unknown → ok` dispatcht als Recovery).

## Ziel & Nicht-Ziele

**Ziel:** Alertmanager-artige **Level-Semantik**: Der Alerter vergleicht bei
jeder Evaluation den Ist-Status mit dem **zuletzt real gemeldeten** Status
(`notified_status`) und meldet Diskrepanzen, sobald keine Suppression mehr
greift. Konkret:

1. Nach Host-down-Release meldet der nächste Evaluationszyklus jeden Check
   nach, dessen Ist-Status vom gemeldeten abweicht (≤ Check-Intervall bzw.
   ≤ Push-Takt Latenz — Gate-Entscheidung: kein Sofort-Sweep).
2. Nach Maintenance-Fensterende werden überdauernde Problem-Zustände **und**
   im Fenster passierte Recoveries (für vorher gemeldete Alerts) nachgemeldet.
   Transitionen, die vollständig im Fenster liegen (`ok → critical → ok`),
   bleiben stumm (Diskrepanz = 0) — die alte Gate-Aussage bleibt wahr.
3. Eine Recovery wird **nur** gemeldet, wenn zuvor real ein Problem
   (`warning`/`critical`) gemeldet wurde. `ok → unknown → ok` ist damit still;
   `critical → unknown → ok` liefert die bisher verlorene Entwarnung nach.

**Nicht-Ziele (YAGNI):**
- Kein per-Kanal- oder per-Rule-Sent-Tracking; `notified_status` ist ein Feld
  pro Check (Gate-Entscheidung: „Melde-Zweig durchlaufen" zählt als gemeldet;
  Kanal-Fehler trackt weiterhin das Alert-Log).
- Kein Sofort-Re-Emit bei Release (kein Sweep beim agent_ping-Recovery, kein
  Fensterende-Job) — der Evaluationszyklus reicht (Gate-Entscheidung).
- Kein Alertmanager-Grouping/-Silencing, kein Kanal-Retry-Umbau, keine
  UI-Änderung (Desktop zeigt weiterhin den Ist-Status).
- Wall-clock-Staleness (F4) bleibt außen vor (bewusster T6-Trade-off).

## Betroffene Komponenten & Dateien

Nur `apps/monitoring/` (Server-Contract unverändert — das `new_status`-Feld im
Hub-Payload existiert seit T36):

- `app/models.py` — `MonitorState.notified_status` (String, nullable).
- `alembic/versions/<neu>_notified_status.py` — Migration nach Head
  `b7d9f1a3c5e7`, **Backfill `notified_status = status`** (Bestandszustände
  gelten als gemeldet → kein Nachmelde-Sturm beim Deploy).
- `app/alerter.py` — Kern-Umbau von `process_alert` (siehe unten) + reine
  Entscheidungsfunktion.
- `app/check_engine.py` — Dispatch-Bedingung im Scheduler-Pfad
  (`execute_check`, Zeile ~234: `old_status != eff_status` →
  `eff_status != state.notified_status`).
- `app/routers/agent.py` — dieselbe Bedingung im Push-Pfad
  (`pending_alerts`-Sammlung).
- Tests: `tests/test_alerter*.py`, `tests/test_check_engine.py`,
  `tests/test_agent_report.py`, neu `tests/test_alerter_sent_state.py`.

## Datenmodell / API / Migrationen

- **Neue Spalte** `monitor_state.notified_status VARCHAR NULL` — der Status,
  für den zuletzt der Melde-Zweig durchlaufen wurde. `NULL`/`pending` = noch
  nie gemeldet.
- **Alembic:** eine Revision (down: Spalte droppen), Parity-Smoke
  (`compare_server_default=True`) muss grün bleiben.
- **Kein API-/Wire-Drift:** `to_dict()` kann `notifiedStatus` mit ausgeben
  (Debug-Wert, additiv, optional); Hub-Payload und Server-Ingest unverändert.

### Kern-Semantik (`process_alert`, Ziel-Zustand)

Aufruf bei **jeder** Evaluation (Callsites filtern billig vor:
`eff_status != state.notified_status` → Dispatch; sonst nichts zu tun). Ablauf:

1. `new == notified` → return (nichts Neues; ersetzt den `old == new`-Guard).
2. `new == "unknown"` → return, `notified_status` **unverändert** (unknown
   meldet nie; die Diskrepanz bleibt für später bestehen).
3. `new == "ok"` und `notified` ∉ {`warning`, `critical`} → **still**
   `notified_status = "ok"` setzen, keine Meldung (kein Recovery-Spam;
   deckt Erst-Evaluation `pending/NULL → ok` und `unknown`-Flapping ab).
4. Aktives Maintenance-Fenster → return, `notified_status` unverändert
   (collect-but-mute; Nachmeldung nach Fensterende via Diskrepanz).
5. Host-down (agent_ping des Servers critical, Check ≠ agent_ping) → return,
   `notified_status` unverändert.
6. **Melden:** Message/Hub-Emit mit `old = notified_status` (aus
   Empfängersicht die letzte gemeldete Lage — eine Nachmeldung nach Host-down
   liest sich als `ok → critical`, eine Maintenance-Recovery als
   `critical → ok`), Severity bleibt worse-of-both, Recovery bypasst weiterhin
   den Cooldown, Alert-Log-Rows wie bisher. Danach
   `notified_status = new_status` — unabhängig vom Kanal-Erfolg
   (Gate-Entscheidung).

Der bestehende `old_status`-Parameter bleibt für Log/Message-Kontext erhalten,
verliert aber seine Guard-Funktion.

## Externe Integrationen

Keine. (Alertmanager dient nur als Semantik-Referenz — Inhibition/Silence sind
dort level-triggered mit Re-Fire; kein Wire-Kontakt.)

## Trade-offs & Alternativen

- **Level-triggered im Zyklus vs. Sofort-Re-Emit:** Gewählt: Zyklus
  (Gate-Entscheidung). Latenz der Nachmeldung ≤ Intervall (typ. 5 min) ist für
  Alerting akzeptabel; dafür kein neuer Scheduler-Job, keine
  Release-Verkabelung, keine neuen Fehlerpfade.
- **Ein Feld vs. per-Rule-Tracking:** Ein Feld pro Check ist bewusst grob —
  Rules mit engen `match_severity`-Filtern können eine Nachmeldung „verpassen",
  wenn sich nur die Severity-Stufe ändert; das nimmt der Cooldown heute schon
  in Kauf. Per-Rule-State wäre eine neue Tabelle für einen Randfall (YAGNI).
- **Backfill = status vs. NULL:** `status` verhindert einen Meldesturm beim
  Deploy (jeder bestehende warning/critical würde sonst „nachgemeldet"). Der
  Preis: ein zum Deploy-Zeitpunkt real nie gemeldeter Altzustand wird auch
  künftig nicht nachgemeldet — einmalig und akzeptabel.

## Risiken & Rollback

- **Doppel-Dispatch-Race:** Scheduler- und Push-Pfad bearbeiten disjunkte
  Check-Typen (PUSH_ONLY_TYPES-Guard); der Push-Pfad hält den Row-Lock. Das
  BG-Dispatch-Fenster (`_dispatch_alert_bg` liest neu) wird im Umbau darauf
  geprüft, dass `notified_status` im selben Commit wie der Dispatch-Entscheid
  gesetzt wird.
- **Meldeverhalten ändert sich sichtbar** (Nachmeldungen, entfallener
  unknown→ok-Spam) — per Doku kommuniziert; kein Env-Schalter (YAGNI, das alte
  Verhalten ist ein Bug).
- **Rollback:** Code-Revert genügt (Spalte bleibt harmlos stehen);
  Migration-Downgrade droppt sie.

## Doku-Impact

`docs/admin/monitoring.html` + `docs/en/admin/monitoring.html` (Abschnitt
„Alert-Verhalten": Nachmeldung nach Host-down/Fensterende, neue unknown→ok-
Regel), `docs/developer/monitoring.html` DE+EN (Guard-Reihenfolge +
`notified_status`), `CHANGELOG.md` (Changed). Kein README-Impact (kein Env/CLI).

## Offene Fragen

Keine — die vier Gate-Fragen (Branch-Basis stacked auf
`feature/monitoring-overhaul`, Nachmeldung im Evaluationszyklus,
Sent-Kriterium „Melde-Zweig durchlaufen", beide Semantik-Änderungen) wurden am
2026-07-26 entschieden.
