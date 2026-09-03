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

**Erreicht wurden drei von vier** (Lauf 33746834514): `pip-audit`, `cargo audit`
und `govulncheck` sind grün, `npm audit` bleibt rot — dort fällt ausschließlich
der Step „Audit e2e lockfile", weil `extract-zip` keine gepatchte Version hat
(GHSA-jmr9-qjv8-65gv). Das ist als `[?]` eskaliert (siehe Offene Fragen).

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
- `apps/desktop/e2e/package-lock.json` — **im Ergebnis unangetastet**, siehe
  Offene Fragen
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
- **cargo:** Vier gezielte `-p`-Bumps in `apps/desktop/src-tauri` lösen alle
  fünf Rust-Advisories, alles innerhalb semver (kein `--aggressive`):
  `plist 1.8.0 → 1.10.0` zieht `quick-xml 0.41.0` statt 0.37.5/0.38.4,
  `tauri-winrt-notification 0.7.2 → 0.7.3` streicht seine quick-xml-Abhängigkeit
  ganz, und `tauri-plugin-log 2.8.0 → 2.9.1` lässt den Teilbaum `byte-unit` →
  `rust_decimal` → `rkyv 0.7.46` **komplett aus dem Baum** fallen.
  *(Die frühere Fassung dieses Absatzes behauptete, ein volles `cargo update`
  bewege nur diese Kronen — das war aus einer gefilterten Dry-Run-Ausgabe
  geschlossen und ist widerlegt: der volle Lauf bewegt 246 Zeilen. Siehe
  Trade-offs.)*
- **npm:** `npm audit fix` ohne `--force` räumt `apps/web` und
  `apps/desktop/ui` vollständig ab (beide danach `found 0 vulnerabilities`,
  in der CI bestätigt). Für `apps/desktop/e2e` galt dieselbe Annahme — sie ist
  **widerlegt**: dort bleiben `deepmerge-ts <8.0.0` und vor allem `extract-zip`,
  für das es laut GitHub-Advisory keine gepatchte Version gibt.

## Trade-offs & Alternativen

- **`.in`-Untergrenze anheben statt nur `pip-compile --upgrade`:** Die `.in`
  sagt heute `cryptography>=48.0.0`; ein reines `--upgrade` würde zwar 50.0.1
  ziehen, aber nicht festhalten *warum*. Empfehlung: Untergrenze auf
  `>=50.0.0`, damit ein späterer Resolver nicht hinter die Sicherheitsschwelle
  zurückfällt. Kostet nichts, dokumentiert den Grund im Diff.
- **Gezielte `-p`-Bumps statt vollem `cargo update`** (korrigiert während der
  Umsetzung). Die ursprüngliche Annahme, der Gesamtlauf bewege „genau die
  betroffenen Kronen", stammte aus einer gefilterten Dry-Run-Ausgabe und ist
  **falsch**: real bewegt `cargo update` **246** Zeilen, darunter `tokio`,
  `hyper`, `rustls`, mehrere Tauri-Plugins und `rand` auf 0.10. Für eine
  ausgelieferte Desktop-App, deren Laufzeitverhalten hier nur von Unit-Tests
  abgedeckt ist, ist das zu viel Fläche vor einem Release (CLAUDE.md: „Nur
  anfassen, was nötig ist"). Gewählt:
  `cargo update -p plist -p tauri-winrt-notification -p byte-unit -p tauri-plugin-log`
  — bewegt **26** Pakete, davon vier echte Bumps; die übrigen 22 sind
  Entfernungen: 21 davon der wegfallende `byte-unit` → `rust_decimal` →
  `rkyv`-Teilbaum, dazu `value-bag`, weil `tauri-plugin-log` 2.9.1 statt des
  veralteten `kv_unstable` nur noch `kv` aktiviert — `value-bag` hängt allein
  am alten Alias.
  `tauri-plugin-log` muss mit, weil genau darüber `byte-unit` hereinkommt.
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

**Eine, und sie blockiert das Ziel:** Wie soll `apps/desktop/e2e` behandelt
werden? Die drei Wege — rot lassen, per `overrides` (`deepmerge-ts ^8.0.0`
plus `@puppeteer/browsers ^3.2.1`) mit anschließendem echten GUI-E2E-Lauf als
Gate erzwingen, oder den Lockfile aus `audit.yml` nehmen — stehen samt Kosten
im Ledger bei T2. Die Entscheidung gehört zum Menschen; bis dahin bleibt das
Vorhaben `blockiert`.

Nicht mehr offen: Die Zielversionen sind gegen PyPI bzw. die
crates.io-Auflösung verifiziert, und die Frage, ob `cryptography` 50 den
CA-Issuer-Code bricht, hat T1 beantwortet — sie tut es nicht (65 + 492 Tests
grün gegen 50.0.1).
