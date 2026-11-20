# klein-nachlese-16 — Nachlese kern-gateway-1 und kern-monitoring-51

Roadmap: R-1657, R-1661.

## Problem

- **R-1657:** Der Kommentar an `ensureAllSubscription` (`apps/desktop/e2e/test/lib/live.js`) sagt, die Funktion laufe "like injectEvent" über das Gateway (`-k`). `injectEvent` geht seit kern-gateway-1 per `compose exec` in den Server-Container; der Vergleich stimmt nicht mehr.
- **R-1661:** Drei Nits aus der Abschlussprüfung von kern-monitoring-51:
  - `docs/features/kern-monitoring-51.md` beschreibt für `agent_ping` noch die verworfene Kappung auf den Dienststart; umgesetzt ist der Abzug der Stillstandszeit.
  - `main.py` übergibt `stopped_at=max(MonitorState.last_check)` an `hydrate_agent_liveness`, ohne dass ein Test das prüft; `test_template_overrides` ersetzt die Hydration durch einen Stub, der den Wert verwirft.
  - `ServiceProcessChecker._resolve_alias` schlägt das Alias-Ziel ohne die Windows-Faltung nach, die `_evaluate_list` auf die Schlüssel des Inventars anwendet; ein Test für den Grund (`reason`) eines Dienstes, der über einen Alias als down gilt, fehlt.

## Ziel & Nicht-Ziele

Kommentar und Spec stimmen mit dem Code überein; die zwei Lücken sind getestet; `_resolve_alias` nimmt dieselbe Schlüsselbildung wie das Inventar. Kein sichtbares Verhalten außer dem Alias-Treffer unter Windows.

## Betroffene Komponenten & Dateien

`apps/desktop/e2e/test/lib/live.js`; `apps/monitoring/app/checkers/agent.py`, `apps/monitoring/tests/test_service_process_checker.py`, `apps/monitoring/tests/test_template_overrides.py`; `docs/features/kern-monitoring-51.md`.

## Datenmodell / API / Migrationen

Keine.

## Trade-offs & Alternativen

`_resolve_alias` bekommt die Schlüsselfunktion als Parameter statt den Host-Fakt neu zu lesen: eine Quelle für die Faltung.

## Risiken & Rollback

Je Task ein Commit, einzeln zurücknehmbar.

## Doku-Impact

Keine Produktdoku; die Feature-Spec von kern-monitoring-51 wird korrigiert.

## Offene Fragen

Keine.
