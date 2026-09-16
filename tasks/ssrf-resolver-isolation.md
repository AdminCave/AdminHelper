<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Guard: DNS-Auflösung ohne geteilten Pool — Task-Ledger (Kurz)
Status: aktiv · Branch: fix/ssrf-resolver-isolation · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: tasks/harness-stufe-8a.md (Gesamt-Review, Befund „geteilter ThreadPoolExecutor") — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine; Hook-Pfad und Monitoring-Checks laufen im `all`-Layer des nächsten Wochenlaufs
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0042 (SEC) · Hängt ab von: R-0004 (gemergt, PR #18)
Befund: `_DNS_RESOLVER = ThreadPoolExecutor(max_workers=4)` in `apps/server/app/core/ssrf.py` und `apps/monitoring/app/core/ssrf.py` (seit 8a T5 identisch). Vier gleichzeitige Auflösungen gegen einen hängenden Nameserver belegen alle Worker bis zum OS-Default (~30 s je Aufruf, Futures werden nicht gecancelt); jede weitere `is_private_url` läuft in ihren 5-s-Timeout und meldet fail-closed „privat". **Reichweite korrigiert (Review T1):** dienstweit trifft das nur das Monitoring — dort teilen sich Scheduler-Pool (30) und `_alert_pool` (5) den einen DNS-Pool, jeder Check meldet dann „privat". Im Server läuft jeder Hook in einem eigenen Subprozess (`script_runner.py` → `Popen(script_worker.py)`), der Pool war also pro Hook-Aufruf; dort zählt die Nicht-Daemon-Eigenschaft: eine hängende Auflösung hält den Worker-Prozess beim Exit offen. Nicht-Daemon-Threads werden beim Interpreter-Exit gejoint, SIGTERM hängt.
Beabsichtigte Semantik: unverändert fail-closed bei Timeout und Fehler, unverändert 5 s Deadline pro Aufruf; neu: eine hängende Auflösung blockiert keine andere, und der Prozess kann trotz hängender Auflösungen beenden. `test_ssrf_parity.py` (8a T5) verlangt, dass beide Dateien identisch bleiben — beide Tasks tragen denselben Diff.

### T1 — Server: Auflösung pro Aufruf in Daemon-Thread mit In-Flight-Deckel  [x]
Komponente: apps/server · Dateien: apps/server/app/core/ssrf.py, apps/server/tests/test_ssrf.py
Änderung: `ThreadPoolExecutor` ersetzen durch eine Hilfsfunktion `_resolve(hostname, timeout)`: ein `threading.Thread(daemon=True)` je Aufruf, Ergebnis über ein Ein-Element-Objekt, `thread.join(timeout)`; kein Rückgabewert innerhalb der Deadline ⇒ `None` (fail-closed). Ein `threading.BoundedSemaphore(_DNS_MAX_INFLIGHT = 64)` mit `acquire(blocking=False)` deckelt gleichzeitig hängende Auflösungen; ist der Deckel erreicht ⇒ sofort fail-closed und ein `logger.warning` (einmal je Minute, nicht je Aufruf). Der Thread gibt den Semaphore beim Ende zurück, auch wenn die Deadline längst vorbei ist. Kommentar mit dem Warum (Befund oben). Tests in `test_ssrf.py`: (a) Stub-Resolver blockiert 2 s, Timeout 0,1 s ⇒ fail-closed unter 1 s (bestehend, anpassen); (b) **Isolation:** vier Stub-Auflösungen, die dauerhaft blockieren, werden gestartet, danach eine schnelle Auflösung ⇒ liefert innerhalb 0,5 s das echte Ergebnis (das ist der DoS-Fall); (c) Deckel: `_DNS_MAX_INFLIGHT` auf 2 gepatcht, drei blockierende Aufrufe ⇒ der dritte kehrt sofort fail-closed zurück; (d) der gestartete Thread ist `daemon=True`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py
Doku: keine (intern; Verhalten nach außen unverändert)
Ergebnis: `_DNS_RESOLVER` raus, `_resolve()` mit Daemon-Thread je Aufruf + `BoundedSemaphore(64)` + gedrosselter Cap-Warnung. **Abweichung (Schnitt):** der Guard-Diff liegt in *beiden* `ssrf.py` in diesem Commit — `test_ssrf_parity.py` macht jeden Commit rot, der nur eine Datei ändert; T2 trägt die Monitoring-Tests und den CHANGELOG. **Abweichung (Test c):** der Deckel wird über `_DNS_INFLIGHT` gepatcht (zusätzlich zu `_DNS_MAX_INFLIGHT`), weil die Semaphore beim Import entsteht. Review-Runde 1 behoben: Permit-Leck bei fehlgeschlagenem `Thread.start()` (Release + fail-closed, Test dazu), leere Adressliste jetzt fail-closed, Server-Kommentar auf die tatsächliche Reichweite korrigiert. Runde 2: `approve`; zwei Nits mitgenommen (Cap-Test fordert seine Permits zurück, stale Zeilenzahl im Paritätstest-Kommentar), einer bewusst offen gelassen (`except RuntimeError` statt `BaseException` — `MemoryError` in `Thread()` liegt ohnehin außerhalb des `try`; ein zweiter Zweig ohne testbaren Fall wäre YAGNI). Revert-Probe im eigenen Worktree: gegen die alte Pool-Version ist der Isolationstest rot (`is_private_url("http://healthy.example")` → `True`).

### T2 — Monitoring: derselbe Diff  [ ]
Komponente: apps/monitoring · Dateien: apps/monitoring/app/core/ssrf.py, apps/monitoring/tests/test_ssrf.py (Tests wie T1, an die Monitoring-Testkonventionen angepasst)
Änderung: Der Guard-Diff selbst liegt bereits in T1 (Parität, s. dort); T2 trägt die Monitoring-Tests und den CHANGELOG. `bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_parity.py` muss danach grün sein.
Verify: bash scripts/dev/verify.sh monitoring --strict   und   bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_parity.py
Doku: CHANGELOG Unreleased/Security ein Satz (beide Dienste)
Abhängt von: T1
