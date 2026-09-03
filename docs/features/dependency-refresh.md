# Dependency-Refresh (Audit wieder grün)

Arbeitet die überfällige Update-Runde ab, die der wöchentliche
`Dependency Audit` seit dem 2026-07-06 anmahnt — **neun rote Läufe in Folge**
(06.07. bis 31.08.). Alle Versionsangaben unten sind gegen die Registry
verifiziert, nicht geschätzt.

## Problem / Motivation

`.github/workflows/audit.yml` ist laut eigenem Kopfkommentar der Ersatz für
Dependabot: „a red run is the signal to start an update round". Diese Runde hat
nie jemand gestartet. Seit dem letzten Blick (2026-08-12) hat sich der Befund
**verschlechtert**: `pip-audit` war damals grün und ist es nicht mehr.

Stand des jüngsten Laufs (2026-08-31), drei von vier Jobs rot:

| Job | Fund | Ziel |
|---|---|---|
| pip-audit | `cryptography==48.0.1` — PYSEC-2026-3552 / -3553 / -3554 | ≥ 50.0.0 |
| cargo audit | `quick-xml` (RUSTSEC-2026-0194/-0195, zwei Pfade), `rkyv` (RUSTSEC-2026-0235) | s. u. |
| npm audit | brace-expansion ×2, PostCSS, fast-xml-parser, js-yaml | `npm audit fix` |
| govulncheck | — | bleibt grün |

Das Gewicht liegt auf `cryptography`: anders als die npm-Funde (reines
Build-/Test-Werkzeug — `npm audit --omit=dev` meldet für Web und Desktop-UI
null) steckt es **ausgeliefert in der eigenen PKI** — `apps/ca-issuer/app/pki.py`,
`issuer.py`, `storage.py` und `apps/server/app/core/identity.py`, also im
mTLS-Enrollment-Pfad. Was die drei PYSEC-Einträge konkret erlauben, ist **nicht
verifiziert** (sie liegen jenseits des Wissensstands des Autors); die
Dringlichkeit leitet sich aus dem Einsatzort ab, nicht aus einem gelesenen
Advisory-Text.

## Ziel & Nicht-Ziele

**Ziel:** Alle vier Audit-Jobs grün — durch echte Updates, nachgewiesen über
einen `workflow_dispatch`-Lauf auf dem Feature-Branch.

**Nicht-Ziele:**

- **Keine Ignore-/Allowlist-Einträge.** Ein stummgeschalteter Audit ist
  schlimmer als ein roter: er sieht grün aus. Wenn ein Fund nicht lösbar ist,
  wird er als `[?]` eskaliert, nicht unterdrückt.
- Keine Major-Upgrades über das Nötige hinaus (kein FastAPI-/Tauri-Sprung
  „bei der Gelegenheit").
- Kein Wechsel des Lock-Verfahrens, kein Dependabot.
- Die 22 `cargo audit`-Warnungen über unmaintained GTK3-Bindings (`atk`, `gdk`,
  …) bleiben Warnungen — sie brechen den Job nicht und hängen am
  Tauri-v1-GTK-Stack, nicht an uns.

## Betroffene Komponenten & Dateien

- `apps/server/requirements.in` + `requirements.txt`
- `apps/ca-issuer/requirements.in` + `requirements.txt`
- `apps/web/package-lock.json`
- `apps/desktop/ui/package-lock.json`
- `apps/desktop/e2e/package-lock.json`
- `apps/desktop/src-tauri/Cargo.lock`
- `CHANGELOG.md`

`apps/monitoring` zieht `cryptography` nicht (weder direkt in der `.in` noch
transitiv in der Lockfile) und bleibt unberührt.

## Datenmodell / API / Migrationen

Keine. Kein Schema, kein Endpunkt, kein Vertrags-Drift zwischen Server ↔ Web ↔
Desktop ↔ Agent. Reine Abhängigkeits-Pins.

## Externe Integrationen

Keine Wire-Protokolle berührt. Verifizierte Fakten für die Umsetzung:

- **PyPI:** `cryptography` steht bei **50.0.1**, `requires_python
  ">=3.9,!=3.9.0,!=3.9.1"` — kompatibel mit dem `python:3.12-slim` der
  Dockerfiles. 50.0.x deckt alle drei PYSEC-Einträge (der schärfste verlangt
  50.0.0).
- **cargo:** `cargo update --dry-run` in `apps/desktop/src-tauri` löst **alle
  fünf** Rust-Advisories ohne Handarbeit:
  `plist 1.8.0 → 1.10.0` und `tauri-winrt-notification 0.7.2 → 0.7.3` ziehen
  `quick-xml 0.41.0` statt 0.37.5/0.38.4; `rust_decimal` (über `byte-unit`)
  und mit ihm `rkyv 0.7.46` fallen **ganz aus dem Baum**. Alles innerhalb
  semver — kein `--aggressive`, kein Major-Bump nötig.
- **npm:** `npm audit fix --dry-run --package-lock-only` in `apps/web` meldet
  „To address all issues, run: npm audit fix" (6 Funde, ohne `--force`). Für
  `apps/desktop/ui` und `apps/desktop/e2e` sagt das CI-Log dasselbe („fix
  available via `npm audit fix`"), **einzeln nachgeprüft wurde nur `apps/web`**.

## Trade-offs & Alternativen

- **`.in`-Untergrenze anheben statt nur `pip-compile --upgrade`:** Die `.in`
  sagt heute `cryptography>=48.0.0`; ein reines `--upgrade` würde zwar 50.0.1
  ziehen, aber nicht festhalten *warum*. Empfehlung: Untergrenze auf
  `>=50.0.0`, damit ein späterer Resolver nicht hinter die Sicherheitsschwelle
  zurückfällt. Kostet nichts, dokumentiert den Grund im Diff.
- **`cargo update` (semver) statt gezielter `-p`-Bumps:** Der Dry-Run zeigt,
  dass der Gesamtlauf genau die betroffenen Kronen bewegt und nebenbei
  `thiserror 2.0.18 → 2.0.20` mitnimmt. Ein chirurgischer Einzel-Bump wäre
  mehr Aufwand bei gleichem Ergebnis; die volle Testsuite ist ohnehin das Gate.
- **Zwei Vorhaben statt einem?** Ursprünglich als „Python/npm mechanisch, Rust
  braucht Tiefenanalyse" geplant. Der Dry-Run hat das widerlegt — auch Rust ist
  mechanisch. Ein Vorhaben mit vier Tasks ist die schlankere Form (YAGNI).
- **Werkzeuglage (verifiziert):** Nach `source .devenv.sh` sind `node` 22.23.1,
  `npm` 10.9.8 (via nvm), `cargo` und `docker` lokal verfügbar; `bash
  scripts/tests/run.sh quick` läuft mit 10 Schritten grün durch. Nur
  `pip-compile` fehlt — dafür ist der Container-Weg ohnehin das in
  DEVELOPMENT.md dokumentierte Verfahren (definierte Python-Version wie im
  Dockerfile). Alles andere läuft nativ; crabbox braucht es erst für die
  schwere Abschluss-Suite. (Die CLAUDE.md-Notiz „Die Dev-Box hat kein Docker"
  ist überholt — Korrektur gehört aber nicht in dieses Vorhaben.)

## Risiken & Rollback

- **Der scharfe Punkt: `cryptography` 48 → 50 sind zwei Major-Versionen.**
  Deprecated APIs können in 49 oder 50 entfernt worden sein, und der
  CA-Issuer nutzt die Bibliothek intensiv (CSR-Parsing, Signieren,
  Serialisierung). Genau deshalb ist die ca-issuer-Suite (9 Testdateien) das
  Gate von T1 und nicht nur `pip-audit`. Bricht eine API weg, ist das ein
  echter Code-Fix, keine reine Pin-Änderung — dann `[?]` statt raten.
- `cargo update` kann einen Build brechen (Tauri-Baum) → `cargo clippy -D
  warnings` + `cargo test` sind Teil des Verify.
- `npm audit fix` kann Dev-Werkzeug (Vite/PostCSS) anfassen → `npm run build`
  bzw. die Unit-Suiten müssen grün bleiben.
- **Rollback:** je ein Commit pro Ökosystem → `git revert <commit>` nimmt genau
  eine Lockfile-Änderung zurück, ohne die anderen zu berühren.

## Doku-Impact

Gering. `CHANGELOG.md` bekommt pro Task eine Zeile unter **Security** (das ist
die nach außen sichtbare Wirkung). Kein `docs/`-Impact: Es ändert sich kein
Verhalten, kein Flag, kein Port, keine Bedienung. Die veraltete CLAUDE.md-Aussage
„Die Dev-Box hat kein Docker" wird **nicht** hier korrigiert — das gehört nicht
in den Auftrag (in T4 nur als Notiz vermerkt).

## Offene Fragen

Keine. Die Zielversionen sind gegen PyPI bzw. die crates.io-Auflösung
verifiziert; die einzige echte Unbekannte (bricht `cryptography` 50 den
CA-Issuer-Code?) ist keine Design-Frage, sondern fällt beim Verify von T1 auf.
