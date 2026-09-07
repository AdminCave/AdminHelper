# Code-Review-Fixes (Befunde vom 2026-08-12)

Arbeitet die vier Befunde ab, die das Review vom 2026-08-12 nach der
Angemessenheitsprüfung übrig gelassen hat. Sie waren bisher **nirgends
erfasst** — sie standen nur im Chatverlauf und wären damit genau die
„Merker-Halde" geworden, die `tasks/merker-cleanup.md` gerade beseitigt hat.

## Problem / Motivation

Das Review war bewusst hart priorisiert: aus dem gesamten Durchgang blieben vier
belegte Befunde, alles andere wurde als Rauschen gestrichen. Der schwerste
(B1) trifft die Kernfunktion des Produkts an der Stelle, an der man sich im
Incident darauf verlässt. Keiner der vier ist ein Sicherheitsloch — es geht um
stille Fehlschläge und um Zustand, der ohne Spur verschwindet.

| ID | Schwere | Kern |
|---|---|---|
| B1 | Hoch | „Jetzt ausführen" ist bei 6 von 11 Check-Typen ein stiller No-op mit HTTP 200 |
| B2 | Mittel | Semaphore-Leak sperrt die Hook-Ausführung dauerhaft |
| B3 | Niedrig | Statusübergänge aus Agent-Pushes werden nicht geloggt |
| B4 | Niedrig | Das Internal-Key-Gate existiert zweimal und ist auseinandergelaufen |
| B5 | Mittel | `run.sh` überspringt das Python-Lint-Gate stillschweigend (Nachtrag 03.09.) |

**B5 kam nicht aus dem Review**, sondern beim Nachprüfen des Gesamtstands am
2026-09-03 hinzu: `run.sh` sucht `ruff` im PATH, wo es nicht liegt, und meldet
den Lauf trotzdem als „10 passed, 0 failed, 1 skipped". Damit gehört es in
dieselbe Familie wie B1 — ein Fehlschlag, der wie Erfolg aussieht — und wird
hier mitgenommen statt erneut vertagt.

## Ziel & Nicht-Ziele

**Ziel:** Die Befunde beheben, jeder mit einem Test bzw. einer Gegenprobe, die
den alten Zustand rot färbt.

**Nicht-Ziele:** Die im Review ausdrücklich verworfenen Punkte bleiben liegen —
die `details`-Divergenz der beiden Dispatch-Pfade (latent, heute nicht
erreichbar), die zeitlich unbegrenzte Host-down-Inhibition (bewusste
Entwurfsentscheidung, Alertmanager-Muster), deutsche API-Fehlertexte (Stil),
der Brute-Force-Zähler bei Redis-Ausfall (verlangt aktive Störung) und eine
zweite Traversal-Schranke in `ansible/router.py` (Redundanz ohne Gewinn). Kein
Refactoring „bei der Gelegenheit".

## Betroffene Komponenten & Dateien

- **B1:** `apps/monitoring/app/routers/checks.py` (`run_check_now`, Z. 288–301),
  `apps/monitoring/app/check_engine.py` (Z. 117 `enabled`-Filter, Z. 129–130
  Push-Only-Return) · `apps/desktop/ui/src/components/monitoring/section/MonCheckLine.svelte`
  (Z. 84 Button), `apps/desktop/ui/src/components/infra/tabs/MonitoringTab.svelte`
  (Z. 78, zweite Aufrufstelle), `apps/desktop/ui/src/lib/i18n/dictionaries.ts` (DE+EN)
- **B2:** `apps/server/app/modules/hooks/script_runner.py` (Z. 127 acquire,
  Z. 138 `Popen`, Z. 168–169 Thread-Start, Z. 170/188–189 `try`/`finally`)
- **B3:** `apps/monitoring/app/routers/agent.py` (Z. 288–289) gegenüber
  `apps/monitoring/app/check_engine.py` (Z. 213–221)
- **B4:** `apps/server/app/modules/notifications/router.py` (Z. 161) gegenüber
  `apps/monitoring/app/core/auth.py` (Z. 14–19)
- **B5:** `scripts/tests/run.sh` (Z. 107–111 — `have ruff` scheitert, und der
  Aufruf deckt nur `apps/server apps/monitoring` ab, nicht `apps/ca-issuer`)

Das Web-Frontend ist **nicht** betroffen: `apps/web` ruft den `/run`-Endpunkt
nirgends auf (verifiziert).

## Datenmodell / API / Migrationen

Keine Migration. Eine **API-Verhaltensänderung** in B1: `POST
/api/monitoring/checks/{id}/run` antwortet für push-ausgewertete und für
deaktivierte Checks künftig mit `409 Conflict` statt mit `200` und
unverändertem State. Vertrags-Drift ist auf den Desktop-Client begrenzt (der
einzige Aufrufer) und wird in T2 mitgezogen.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- **B1 — wo korrigieren?** Drei Varianten: nur Backend ehrlich machen, nur den
  Button verstecken, oder beides. **Gewählt: beides.** Das Backend muss
  unabhängig vom Client die Wahrheit sagen (ein zweiter Client, ein Skript oder
  ein späterer Web-Port erbt sonst denselben stillen No-op), und die UI darf
  keine Aktion anbieten, die nie etwas tun kann. Der Fall „deaktivierter Check"
  wird gleich mitbehandelt: dort schlägt der `enabled`-Filter zu, mit demselben
  irreführenden 200.
  *Diese Wahl ist eine Entwurfsentscheidung und am Gate überstimmbar.*
- **B1 — welcher Status-Code?** `409 Conflict` (der Zustand der Ressource
  verbietet die Aktion) statt `400` (die Anfrage selbst ist wohlgeformt) oder
  `501`. Trägt eine verständliche `detail`-Botschaft.
- **B2 — Umfang des Schutzes:** Das Permit müsste nur bis zum bestehenden
  `try` gerettet werden. Alternative wäre ein Context-Manager; für eine
  einzelne Stelle ist das Overengineering (YAGNI).
- **B3 — wo loggen?** Die Log-Zeile gehört in den Push-Pfad, nicht in eine
  geteilte Hilfsfunktion: die beiden Pfade teilen bereits die *reinen*
  Funktionen (`next_fail_count`, `effective_status`, `is_suppressed`), aber die
  Orchestrierung bewusst nicht. Eine Zusammenlegung wäre ein größerer Umbau am
  Alert-Pfad — nicht Teil dieses Auftrags.
- **B4 — welche Seite gewinnt?** Die Monitoring-Fassung ist die gehärtete
  (Byte-Vergleich, `None`-tolerant, Docstring erklärt den Grund). Der Server
  zieht nach, nicht umgekehrt.

## Risiken & Rollback

- **B1 ist die einzige nach außen sichtbare Änderung.** Ein Nutzer, der den
  Button bisher gewohnheitsmäßig auf Push-Checks geklickt hat, bekommt jetzt
  eine Absage statt scheinbaren Erfolgs — das ist der Zweck, sollte aber in der
  Admin-Doku stehen, damit es nicht als Regression gelesen wird.
- B2 berührt den Hook-Ausführungspfad (Subprocess, Threads, Timeout). Der
  bestehende Test-Bestand um `run_hook_script` ist das Gate.
- B3/B4 sind risikoarm (eine Log-Zeile, eine Vergleichs-Härtung).
- **Rollback:** ein Commit je Befund → `git revert` trifft genau einen.

## Doku-Impact

Nur B1: ein Satz in `docs/admin/monitoring.html` **und** `docs/en/…`, dass
push-ausgewertete Checks (`agent_resources`, `service_process`,
`proxmox_backup`, `zfs_health`, `docker_health`, `smart_health`) ihre Daten
ausschließlich über den Agent-Push bekommen und deshalb nicht manuell
ausgelöst werden können. Dazu `CHANGELOG.md` (Fixed) für B1 und B2. B3 und B4
sind rein intern — keine Doku (CLAUDE.md: Bugfixes und internes Refactoring
brauchen keine).

## Offene Fragen

Eine, und sie ist am Gate zu bestätigen statt zu erraten: **Ist „Backend 409 +
UI blendet aus" die gewünschte Auflösung von B1**, oder soll der Button
sichtbar bleiben und die Absage als Fehlermeldung zeigen? Die Spec geht von der
ersten Variante aus.
