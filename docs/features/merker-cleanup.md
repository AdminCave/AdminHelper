# Merker-Aufräumer (Monitoring-Overhaul + Sent-State)

Sammelt die noch offenen, bewusst vertagten Punkte aus
`tasks/monitoring-overhaul.md` und `tasks/alert-sent-state.md` — nach einer
Triage gegen den echten Code (2026-08-03), nicht nach Erinnerung.

## Problem / Motivation

Beide Ledger tragen „Merker: … bei Gelegenheit fixen". Zwei solcher Merker
haben sich beim v0.44.0-Release als **echte Defekte** entpuppt
(`restore.sh`-Disaster-Recovery, SSRF-Guard auf privaten Ping-Zielen) — sie
lagen dokumentiert herum, statt gefixt zu sein. Der Rest gehört einmal
sauber abgearbeitet oder begründet geschlossen, damit die Ledger keine
Dauer-Halde werden.

## Triage: Ist-Stand aller acht Merker

**Bereits erledigt — nur noch Ledger-Hygiene (keine Code-Arbeit):**

| Merker | Erledigt durch |
|---|---|
| Web-`HOOK_EVENTS`-Picker driftet gegen `VALID_EVENTS` | PR #6 (`alert.triggered` + `playbook.*` + Sync-Guard-Test) |
| Backend-Backstop `Field(ge=0)` für `cooldown_minutes` | T44 (3 Stellen in `schemas.py`) |
| `restore.sh` nicht idempotent auf Warm-Boxen | Commit 56d7cbf (Wipe+Extract als Container-Root) |
| Proxy-Allowlist-/SSRF-Hinweis in der Developer-Doku | T35 (`CHECK_TYPE_METRICS`-Absatz, DE+EN) |

**Begründet geschlossen (kein Fix nötig):**

- **Web-Modal-Escape-Port:** Der Merker galt unter der Bedingung „falls Web je
  `confirmDialog` aus einem offenen Modal ruft". Verifiziert: `apps/web` ruft
  `confirmDialog` ausschließlich aus Listen-Aktionen (`removeHook`,
  `rotateToken` in `pages/Hooks.svelte`, analog `Users`/`ApiKeys`) — nie aus
  einem offenen Modal. Der `modalStack` wäre eine Lösung ohne Problem (YAGNI).
- **No-op-Task-Churn bei langer Suppression:** Nach dem Claim-then-dispatch-Umbau
  (T8) enden unterdrückte Dispatches in Millisekunden. Ein Dedup über zwei
  Task-Mechanismen (ThreadPool + FastAPI BackgroundTasks) wäre fehleranfällige
  Komplexität.
- **`_build_message`-Re-SELECT:** Nach T8 korrekt so — der State ist nach dem
  Claim-Commit expired, ein durchgereichtes Objekt wäre stale.
- **`old_status`-Parameter von `process_alert`:** Gate-Entscheidung 2026-08-03 —
  bleibt. Der Alert-Pfad wurde gerade stabilisiert; die Signatur-Änderung
  berührt beide BG-Dispatcher plus die Fake-DB-Tests, Nutzen gering.

**Offen, wird hier umgesetzt:** NTP-Slew-Guard, `MonSparkline`-untrack,
Smoke-Test-Gerüst-Dedup (siehe Ziel).

## Ziel & Nicht-Ziele

**Ziel:**

1. **NTP-Slew-Guard für `agent_ping`** (Gate-Entscheidung: ja). Seit der
   Liveness-Persistenz misst die Staleness mit **Wanduhr** (monoton ist nicht
   persistierbar). Ein NTP-Vorwärtssprung > `stale_minutes` lässt **alle**
   Server gleichzeitig als „Agent weg" gelten — und schaltet über die
   Host-down-Inhibition zugleich alle anderen Alerts dieser Server stumm.
   Lösung: den Push-Zeitpunkt zusätzlich monoton merken und beim Vergleich
   prüfen, ob Wanduhr- und Monoton-Differenz auseinanderlaufen; tun sie das
   deutlich, gilt die Uhr als gesprungen → Baseline neu setzen statt alarmieren.
   Nach einem Prozess-Neustart existiert kein Monoton-Wert (Hydrierung aus der
   DB) — dann bleibt es beim reinen Wanduhr-Vergleich wie heute.
2. **`MonSparkline`: `untrack` im Fallback-Pfad.** `MonHeartbeatBar` hat diesen
   Fix in T22 bekommen (sonst `effect_update_depth_exceeded`); `MonSparkline`
   ruft im `IntersectionObserver`-Fallback weiterhin `void load()` direkt im
   `$effect`. In Produktion unerreichbar (jeder Browser hat den Observer), aber
   eine Falle für den nächsten Bearbeiter.
3. **Smoke-Test-Gerüst deduplizieren.** `tests/test_migrations_smoke.py` trägt
   das Scratch-DB-Gerüst (CREATE DATABASE, `monkeypatch` auf
   `app_config.DATABASE_URL`, Config-Setup, `finally`-DROP) **dreimal**; eine
   Änderung am Teardown müsste an drei Stellen synchron nachgezogen werden.

**Nicht-Ziele:** die vier bereits erledigten und die vier begründet
geschlossenen Punkte (siehe Triage). Keine weiteren Refactorings „bei der
Gelegenheit".

## Betroffene Komponenten & Dateien

- `apps/monitoring/app/checkers/agent.py` — `_last_report`, `record_agent_report`,
  `hydrate_agent_liveness`, `AgentPingChecker.run`
- `apps/monitoring/tests/test_agent_checker.py` (bzw. die bestehende
  agent-Checker-Testdatei) — Slew-Szenarien
- `apps/monitoring/tests/test_migrations_smoke.py` — Gerüst-Dedup
- `apps/desktop/ui/src/components/monitoring/MonSparkline.svelte`
- `tasks/monitoring-overhaul.md`, `tasks/alert-sent-state.md` — Merker-Hygiene

## Datenmodell / API / Migrationen

Keine. Der Monoton-Wert lebt ausschließlich prozess-lokal neben `_last_report`;
`monitor_agent_liveness` bleibt unverändert (Wanduhr, wie bisher). Kein
Vertrags-Drift zu Server/Desktop/Agent.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- **Slew-Guard vs. rein monoton:** Rein monoton wäre sauberer, ist aber nicht
  persistierbar — nach jedem Neustart wäre jeder Check bis zum nächsten Push
  `unknown`. Genau deshalb wurde in T6 auf Wanduhr umgestellt. Der Guard
  behält die Persistenz und fängt nur den Sprung ab.
- **Schwellwert:** Die Divergenz zwischen Wanduhr- und Monoton-Delta muss
  großzügig toleriert werden (Scheduler-Jitter, Suspend). Vorschlag: als
  „Sprung" gilt eine Divergenz > 60 s; darunter zählt weiter die Wanduhr.
  Suspend/Resume der VM sieht wie ein Sprung aus — der Guard setzt dann die
  Baseline neu, was dem gewünschten Verhalten entspricht (kein Sturm).
- **Dedup-Form beim Smoke-Test:** Ein Contextmanager (`with scratch_db() as
  (cfg, engine):`) statt Fixture-Parametrisierung, weil zwei der drei Kopien
  mitten im Test auf einen Zwischenstand migrieren.

## Risiken & Rollback

- Der Slew-Guard sitzt im Alert-kritischen Pfad: Ein zu scharfer Schwellwert
  könnte einen **echten** Ausfall als Uhr-Sprung fehldeuten und Alarme
  unterdrücken. Gegenmaßnahme: Der Guard setzt nur die Baseline neu, wenn die
  Divergenz die Toleranz überschreitet; die reine Wanduhr-Logik bleibt sonst
  unverändert, und der Fall wird geloggt.
- Alles andere ist Test- bzw. UI-Kleinkram. Rollback je Commit per `git revert`.

## Doku-Impact

Gering. Admin-Doku DE+EN: ein Satz im Abschnitt „Alert-Verhalten", dass ein
Zeitsprung der Server-Uhr keinen Heartbeat-Sturm auslöst. Developer-Doku DE+EN:
ein Halbsatz beim Liveness-Absatz. CHANGELOG: Fixed. Kein README-Impact.

## Offene Fragen

Keine — die zwei Gate-Fragen (Slew-Guard ja, `old_status` bleibt) sind am
2026-08-03 entschieden.
