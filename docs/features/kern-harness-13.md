# kern-harness-13 — Harness: veraltete Verweise, Toolchain-Gleichlauf, Multi-Worker-Stack, Pflicht-Checks

Roadmap: R-0377, R-1419, R-1060, R-0843, R-1753 (R-1364 verschoben nach kern-harness-14, siehe Risiken).
Kevin 2026-11-25: alle Zeilen „Harness-Fund angenommen (Durchsicht)“; R-1753 zusätzlich „faellig, Harness-Pfad
freigegeben“.

## Problem je Zeile
- **R-0377:** Texte nennen gelöschte Teile.
  - `scripts/tests/run.sh` rät zu `scripts/dev/runner-setup.sh`, eine falsche Anleitung an den Nutzer; dazu zwei
    Kommentare.
  - `scripts/dev/ledger.sh` nennt `review.sh diff-scan`; den Leser gibt es heute in `task-close.sh`, und der liest
    alle Zeilen.
  - `scripts/vm/lib.sh` und `scripts/vm/vm.py` nennen `lane.sh`; heute schreibt `scripts/dev/worktree-setup.sh`
    `.vm/lane`.
  - `scripts/dev/tree-hash.sh` nimmt `.crabbox-out` aus.
  - Der Teil `.claude/rules/testing.md` („Stufe 12“) ist auf main schon behoben.
- **R-1419:** Die Box-Python (`PY_VERSION` in `scripts/vm/bootstrap_linux.sh`, `python3.14` in `run.sh`) folgt dem
  `FROM python:X.Y` der Dockerfiles nur per Hand. Beim nächsten Python-Sprung driftet sie still.
- **R-1060:** `bootstrap_linux.sh` installiert Go 1.27.2, `apps/agent/go.mod` verlangt `toolchain go1.27.4`. Frische
  Boxen laden die Toolchain per `GOTOOLCHAIN=auto` vom Proxy statt des SHA-gepinnten Tarballs; das hat einen
  multibox-Lauf rot gemacht.
- **R-0843:** Kein Lauf startet den Server mit `WEB_CONCURRENCY>1`. Ob bei leerem `ADMIN_PASSWORD` genau ein Worker
  den Setup-Token schreibt und das Banner zeigt (Datei-Lock in `apps/server/app/main.py`), prüft nur ein Unit-Test.
- **R-1753:** Seit 2026-11-24 ist jeder PR-Check Pflicht. Ein neuer Job in `ci.yml` ohne Ruleset-Eintrag hält
  Auto-Merge aber nicht auf, und nichts merkt das.

## Lösung
- **T1:** Die Texte nennen den heutigen Nachfolger. Der Test, der den alten Text greppt, zieht mit.
- **T2:** `toolchain-lockstep.sh` bekommt zwei Offline-Prüfungen:
  - (1d) `PY_VERSION` hat Major.Minor jedes `FROM python:X.Y` unter `apps/*/Dockerfile`.
  - (1e) Der Default von `GO_VERSION` ist genau die `toolchain`-Direktive von `apps/agent/go.mod`.

  `GO_VERSION` und SHA-256 gehen auf 1.27.4. Den SHA nennt das Release-JSON von go.dev:
  `7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840`.
- **T3:** Ein neuer letzter Abschnitt in `scripts/tests/integration_stack_test.sh`: den Stack nach `down -v` mit
  `WEB_CONCURRENCY=2` und leerem `ADMIN_PASSWORD` neu starten. Erwartet wird:
  - zwei Worker;
  - genau ein Banner im Log;
  - der Token aus `/data/.bootstrap_setup` legt per `POST /api/auth/bootstrap` den ersten Admin an;
  - ein zweiter Versuch mit demselben Token scheitert.
- **T4:** Die Pflicht-Checks des Rulesets stehen als Liste im Repo (`scripts/dev/required-checks.txt`, erzeugt aus
  `gh api …/rulesets/<id>`). `harness_consistency_test.sh` leitet aus `ci.yml` die Check-Namen jedes PR-Jobs ab,
  Matrix ausgeschrieben, ohne `Changed paths` und Shards. Fehlt einer in der Liste, ist der Test rot. Die Meldung
  sagt, dass Kevin den Ruleset-Eintrag setzt und die Liste nachzieht.
- **T5:** Doku `docs/developer/cicd.html` DE+EN.

## Doku-Impact
`docs/developer/cicd.html` DE+EN:
- Toolchain-Lockstep: Go-Patch gleich der go.mod-Toolchain, Box-Python gleich dem Dockerfile-Python.
- Stack-Test: Multi-Worker-Abschnitt.
- Ruleset: Liste der Pflicht-Checks und ihre Prüfung.

Kein CHANGELOG-Eintrag (Harness, nicht ausgeliefert).

## Risiken & Rollback
- **T3** verlängert den Stack-Job um einen weiteren Neustart (etwa 1–2 min). Rollback ist der Revert der Task.
- **T4:** Die Liste kann vom Ruleset abweichen, wenn Kevin das Ruleset ändert. Der Test prüft nur ci.yml ⊆ Liste,
  offline. Den Abgleich Liste ↔ Ruleset macht `gh api` beim Nachziehen (Kommentarkopf der Liste).
- **R-1364 verschoben:** OPNSENSE_CHECK soll laut Fund das sshd unter `/usr/local/sbin` fragen, „dessen `-T` schreibt
  CamelCase“. Das ist nicht verifiziert, und eine Probe-Box ließ sich am 2026-11-26 nicht klonen (Kapazität
  −1460 MiB). Die rc.conf-Bereinigung braucht ebenfalls einen echten Bake. Die Zeile wandert geschlossen in
  kern-harness-14.

## Offene Fragen
Keine aus Kevins Bereich.
