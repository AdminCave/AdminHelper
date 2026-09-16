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
Befund: `_DNS_RESOLVER = ThreadPoolExecutor(max_workers=4)` in `apps/server/app/core/ssrf.py` und `apps/monitoring/app/core/ssrf.py` (seit 8a T5 identisch). Vier gleichzeitige Auflösungen gegen einen hängenden Nameserver belegen alle Worker bis zum OS-Default (~30 s je Aufruf, Futures werden nicht gecancelt); jede weitere `is_private_url` läuft in ihren 5-s-Timeout und meldet fail-closed „privat". **Reichweite korrigiert (Review T1):** dienstweit trifft das nur das Monitoring — dort teilen sich Scheduler-Pool (30) und `_alert_pool` (5) den einen DNS-Pool, jeder HTTP-Check und jeder Alert-Webhook meldet dann „privat" (ping/tcp/Agent-Checks laufen nicht durch den Guard). Im Server läuft jeder Hook in einem eigenen Subprozess (`script_runner.py` → `Popen(script_worker.py)`), der Pool war also pro Hook-Aufruf; dort zählt die Nicht-Daemon-Eigenschaft: eine hängende Auflösung hält den Worker-Prozess beim Exit offen. Nicht-Daemon-Threads werden beim Interpreter-Exit gejoint, SIGTERM hängt.
Beabsichtigte Semantik: unverändert fail-closed bei Timeout und Fehler, unverändert 5 s Deadline pro Aufruf; neu: eine hängende Auflösung blockiert keine andere, und der Prozess kann trotz hängender Auflösungen beenden. `test_ssrf_parity.py` (8a T5) verlangt, dass beide Dateien identisch bleiben — beide Tasks tragen denselben Diff.

### T1 — Server: Auflösung pro Aufruf in Daemon-Thread mit In-Flight-Deckel  [x]
Komponente: apps/server · Dateien: apps/server/app/core/ssrf.py, apps/server/tests/test_ssrf.py
Änderung: `ThreadPoolExecutor` ersetzen durch eine Hilfsfunktion `_resolve(hostname, timeout)`: ein `threading.Thread(daemon=True)` je Aufruf, Ergebnis über ein Ein-Element-Objekt, `thread.join(timeout)`; kein Rückgabewert innerhalb der Deadline ⇒ `None` (fail-closed). Ein `threading.BoundedSemaphore(_DNS_MAX_INFLIGHT = 64)` mit `acquire(blocking=False)` deckelt gleichzeitig hängende Auflösungen; ist der Deckel erreicht ⇒ sofort fail-closed und ein `logger.warning` (einmal je Minute, nicht je Aufruf). Der Thread gibt den Semaphore beim Ende zurück, auch wenn die Deadline längst vorbei ist. Kommentar mit dem Warum (Befund oben). Tests in `test_ssrf.py`: (a) Stub-Resolver blockiert 2 s, Timeout 0,1 s ⇒ fail-closed unter 1 s (bestehend, anpassen); (b) **Isolation:** vier Stub-Auflösungen, die dauerhaft blockieren, werden gestartet, danach eine schnelle Auflösung ⇒ liefert innerhalb 0,5 s das echte Ergebnis (das ist der DoS-Fall); (c) Deckel: `_DNS_MAX_INFLIGHT` auf 2 gepatcht, drei blockierende Aufrufe ⇒ der dritte kehrt sofort fail-closed zurück; (d) der gestartete Thread ist `daemon=True`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py
Doku: keine (intern; Verhalten nach außen unverändert)
Ergebnis: `_DNS_RESOLVER` raus, `_resolve()` mit Daemon-Thread je Aufruf + `BoundedSemaphore(64)` + gedrosselter Cap-Warnung. **Abweichung (Schnitt):** der Guard-Diff liegt in *beiden* `ssrf.py` in diesem Commit — `test_ssrf_parity.py` macht jeden Commit rot, der nur eine Datei ändert; T2 trägt die Monitoring-Tests und den CHANGELOG. **Abweichung (Test c):** der Deckel wird über `_DNS_INFLIGHT` gepatcht (zusätzlich zu `_DNS_MAX_INFLIGHT`), weil die Semaphore beim Import entsteht. Review-Runde 1 behoben: Permit-Leck bei fehlgeschlagenem `Thread.start()` (Release + fail-closed, Test dazu), leere Adressliste jetzt fail-closed, Server-Kommentar auf die tatsächliche Reichweite korrigiert. Runde 2: `approve`; zwei Nits mitgenommen (Cap-Test fordert seine Permits zurück, stale Zeilenzahl im Paritätstest-Kommentar), einer bewusst offen gelassen (`except RuntimeError` statt `BaseException` — `MemoryError` in `Thread()` liegt ohnehin außerhalb des `try`; ein zweiter Zweig ohne testbaren Fall wäre YAGNI). Revert-Probe im eigenen Worktree: gegen die alte Pool-Version ist der Isolationstest rot (`is_private_url("http://healthy.example")` → `True`).

### T2 — Monitoring: derselbe Diff  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/app/core/ssrf.py, apps/monitoring/tests/test_ssrf.py (Tests wie T1, an die Monitoring-Testkonventionen angepasst)
Änderung: Der Guard-Diff selbst liegt bereits in T1 (Parität, s. dort); T2 trägt die Monitoring-Tests und den CHANGELOG. `bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_parity.py` muss danach grün sein.
Verify: bash scripts/dev/verify.sh monitoring --strict   und   bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_parity.py
Doku: CHANGELOG Unreleased/Security ein Satz (beide Dienste)
Abhängt von: T1
Ergebnis: Monitoring-Testdatei um dieselben fünf Fälle ergänzt (Isolation, Deckel + gedrosselte Warnung, Daemon-Thread, Permit-Rückgabe bei fehlgeschlagenem `Thread.start()`, leere Adressliste); die lokalen Imports des bestehenden Timeout-Tests nach oben gezogen, weil die neuen Tests sie ohnehin auf Modulebene brauchen. CHANGELOG Unreleased/Security mit einem Absatz für beide Dienste (Doku-Feld sagt „ein Satz" — ein Absatz, weil Befund und neue Semantik sonst nicht beide hineinpassen). Review: Reichweite auf HTTP-Checks + Alert-Webhooks präzisiert; Zeitschranke und Docstring-Halbsatz nachgezogen. Bewusst offen: der `time.sleep(2)`-Stub des bestehenden Timeout-Tests hält sein Permit ~2 s über das Testende hinaus (harmlos, solange die Datei in ~0,2 s durchläuft, aber latent bei Umsortierung) — betrifft beide Testdateien gleichermaßen und gehört nicht in diesen Commit; die beiden Mechanismus-Testdateien sind Zweitkopien, die `test_ssrf_parity.py` nicht pinnt.

### T3 — Branch-`/code-review`: echte Befunde abarbeiten  [x]
Komponente: apps/server + apps/monitoring · Dateien: beide `app/core/ssrf.py`, beide `tests/test_ssrf.py`
Angenommen und umgesetzt (Code, in beiden Dateien identisch — Parität geprüft):
- **Semaphore-Objekt statt Modul-Global freigeben:** `sem = _DNS_INFLIGHT` beim acquire binden, `sem.release()`
  im Thread. Vorher las der Thread das Global beim *Ende* — wird es zwischendurch neu gebunden, ging das Permit
  am alten Objekt verloren und schlug am neuen als `ValueError` auf. Realer Bug, nicht nur Test-Artefakt.
- **`Thread(...)`-Konstruktion mit in den `try`** plus `except BaseException: sem.release(); raise` neben dem
  `except RuntimeError`-Zweig: `Thread.__init__` kann werfen (Daemon-Threads im Subinterpreter), und ein
  `MemoryError` im Fenster zwischen acquire und start hätte das Permit ebenso verbrannt. So macht es
  `script_runner.py:180`, auf das sich der Kommentar beruft.
- **Drossel der Cap-Warnung unter `threading.Lock`:** Read-Modify-Write ohne Lock heißt, dass genau im
  Cap-Fall (viele Threads gleichzeitig im Guard) alle zusammen durch die Drossel rutschen — bis zu 35 Zeilen
  statt einer. Der Lock kostet nichts: die Funktion läuft nur bei erschöpftem Deckel.
- **Logger-Name kommentiert:** `getLogger(__name__)` ergibt `app.core.ssrf`, nicht das `monitor.*` der 13
  anderen Monitoring-Module. Der Paritätstest verbietet einen fest verdrahteten Namen — steht jetzt als
  Kommentar in der Monitoring-Datei, damit es nicht als Versehen gelesen wird.
Angenommen und umgesetzt (Tests, in beiden Suiten):
- Der Timeout-Test hing an `time.sleep(2)` und ließ einen Daemon-Thread ~1,9 s über das Testende hinaus ein
  Permit halten; jetzt Event-gebunden und im `finally` freigegeben.
- Neu: `test_a_resolution_error_hands_the_permit_back` — NXDOMAIN/SERVFAIL ist der Alltagsfall, und die
  Permit-Rückgabe auf diesem Pfad war von keinem Test gedeckt.
Geprüft und begründet **nicht** umgesetzt:
- Permit-Rückgabe im Isolationstest: auf der echten 64er-Semaphore beweist ein `acquire` nichts (es gelingt
  immer). Der Cap-Test prüft die Bilanz des Hänge-Pfads bereits auf einer gepatchten 2er-Semaphore.
- `_DNS_MAX_INFLIGHT` vs. Semaphore als getrennter Zustand: die Semaphore entsteht beim Import, die Konstante
  speist danach nur die Logzeile. Der genannte Fehlerfall verlangt einen Config-Knopf, den es nicht gibt (YAGNI).
- Test-Naht `_thread_factory` statt `monkeypatch` auf `threading`: eine Indirektion in Produktionscode allein
  für den Test — genau die prophylaktische Abstraktion, die CLAUDE.md ausschließt.
- CHANGELOG liegt im T2-Commit, der Guard-Diff im T1-Commit („Doku im selben Commit"). Bewusst so gelassen:
  der Ledger weist den CHANGELOG T2 zu, der Branch geht als eine PR-Einheit raus, und ein sauberer Umbau
  verlangte, den Zwischenstand des Ledgers zu rekonstruieren. **Kevins Entscheidung, ob umgehängt wird.**
Review-Runde 1 zu T3 behoben: `test_a_thread_constructor_failure_hands_the_permit_back` in beiden Suiten (der `except BaseException`-Zweig war mutations-unempfindlich — ohne ihn blieb alles grün); Kommentar „a signal" gestrichen, weil ein Signal auf `start()` nach Thread-Start doppelt freigibt (die `BoundedSemaphore` macht daraus ein `ValueError` statt eines Lecks, das Fenster ist eine Instruktion breit — kein zweiter `try`-Block dafür); Kopplung Konstante ↔ Semaphore als Kommentar benannt; die Zeilenzahl im Paritätstest-Kommentar durch eine Formulierung ersetzt, die nicht wieder veraltet.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py   und   bash scripts/dev/verify.sh monitoring --strict
Doku: keine (interne Korrekturen; Außenverhalten wie in T2 beschrieben)

### T4 — Deckel-Erschöpfung: globales Budget oder pro Host?  [?]
**Frage an Kevin.** Der Deckel ist ein globales Budget. Hält ein Nameserver Auflösungen bis ~30 s am Leben
(glibc-Default, dieselbe Zahl wie im Befund) und starten die 30 Scheduler-Worker plus 5 Alert-Worker alle 5 s neue, können mehr als 64
gleichzeitig offen sein — dann lehnt der Guard *jedes* Ziel ab, auch gesunde. Das ist der alte Befund bei
höherer Schwelle (64 statt 4), also kein Rückschritt, aber auch nicht beseitigt. Saubere Lösung wäre pro Host
(kurzer Negativ-Cache für den hängenden Namen) statt eines gemeinsamen Budgets. Das ist ein eigener Schnitt,
kein Nachtrag zu R-0042 — soll er als eigene Roadmap-Zeile aufgemacht werden?

### T5 — Guard-Rückgabewert: `bool` oder Grund?  [?]
**Frage an Kevin.** `is_private_url` fasst „zeigt auf privat", „Auflösung überschritt die Frist" und neu
„Deckel erschöpft" zu einem `True` zusammen. Der Betreiber liest bei totem Nameserver an drei Stellen
(`checkers/http.py`, `alerter.py`, `script_worker.py`) „Ziel ist privat/reserviert" über ein öffentliches,
korrekt konfiguriertes Ziel. Ein kleiner Grund-Enum (allowed / private / unresolved) würde das diagnostizierbar
machen, ändert aber die Signatur, drei Aufrufer und nach außen sichtbare Meldungen — nicht im Auftrag von R-0042. Dazu gehört: der `RuntimeError`-Pfad (Thread-Erschöpfung, Subinterpreter) lehnt heute jedes Ziel ohne eine einzige Logzeile ab. Die vorhandene Drossel taugt dafür nicht — sie trägt die Deckel-Meldung —, also gehört auch das in diese Entscheidung.
