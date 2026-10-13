<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Kleinpaket 5: ADR 0001 und ADR 0002 sagen, was heute gilt — Task-Ledger
Status: geplant · Branch: feature/loop-kleinpaket-5 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0281 (Kurz-Ledger ohne Spec)
Heavy: none — zwei Markdown-Dateien unter `docs/adr/`; kein Code, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Doku-Smoke sauber; `docs-pairs` betrifft nur `docs/*.html`, ADRs gibt es nur deutsch).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac), als Futter für den Builder-Loop. Die Zeile hat
die Aufsicht auf Kevins Wort am 2026-10-10 angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der
Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@75ed3e09. Jede Task ist für eine Bau-Session allein
geschnitten: eine Komponente, alle Fakten in der Task, nur Doku.

Frisch geprüft, was nach Phase A/B noch gilt:
- ADR 0002 `:141` ist schon richtig („Default damals `false`, seit 0.29.0 `true`“) und nicht Teil des Pakets.
- So korrigieren die ADRs sich schon heute: an der Stelle, mit „damals … seit …“. Beide Tasks halten diese Form.

### T1 — ADR 0001: der Umsetzungsstand nennt den Default von heute (R-0281)  [ ]
Komponente: scripts · Dateien: docs/adr/0001-unified-pki-and-secure-deployment.md
Änderung: Abschnitt „0. Umsetzungsstand (Phase A)“, der erste Absatz (`:26-29`), lautet heute:
> Der **Kern** dieses Entwurfs ist umgesetzt und läuft per Default **permissiv** (nutzbar, ohne dass schon ein Client
> ausgesperrt wird). Das Scharfschalten auf `CERT_REQUIRED` ist der `MTLS_ENFORCE`-Schalter (A8) — umgesetzt und
> end-to-end verifiziert (§7), aber bewusst per Default aus; der Flip ist eine Operator-Entscheidung.

Das widerspricht dem Status derselben Datei (`:9-10`: „Default bis 0.28 permissiv; **ab 0.29.0 enforced per Default**
(`MTLS_ENFORCE=true`), da `scripts/install.sh` dem Erst-Admin sein Cert out-of-band besorgt“) und der Zeile D3 der
Tabelle (`:35`: „✅ **enforced** per Default (ab 0.29.0, Code + Compose); Permissiv-Rollout per `MTLS_ENFORCE=false`“).
Künftig sagt der Absatz, in der Form von ADR 0002 `:141`:
- Der Kern ist umgesetzt.
- Bis 0.28 lief er per Default permissiv.
- Seit 0.29.0 ist der `MTLS_ENFORCE`-Schalter (A8, umgesetzt und end-to-end verifiziert, §7) per Default an (Code und
  Compose).
- Ein permissiver Rollout geht per `MTLS_ENFORCE=false`.

Der Rest des Abschnitts und die Tabelle bleiben.
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --paths --env --strict
Doku: docs/adr/0001-unified-pki-and-secure-deployment.md (die Task ist die Doku)
Beweis: origin/main@75ed3e09:
- `grep -n 'bewusst per Default aus' docs/adr/0001-unified-pki-and-secure-deployment.md` → `:28`.
- Dieselbe Datei `:9-10` und `:35`: enforced per Default seit 0.29.0.
Metrik: Aussagen „per Default permissiv / aus“ über den heutigen Stand in ADR 0001: 1 → 0.
Dedup-Key: ref:docs:adr:stale-statements
HEAD: 75ed3e09
Semantik: `docs/adr/0001-unified-pki-and-secure-deployment.md:9-10` (der Status derselben Datei, oben zitiert) und
`docs/admin/installation.html:162` („unter dem enforced-Default“).

### T2 — ADR 0002: Logout und Erneuern so, wie der Desktop es heute tut (R-0281)  [ ]
Komponente: scripts · Dateien: docs/adr/0002-phase-a-task-plan.md
Änderung: Zwei Sätze im Abschnitt A5 beschreiben ein Verhalten, das der Desktop nicht mehr hat. Beide werden in der
Form von `:141` richtiggestellt („damals …, heute …“); der Rest des Abschnitts bleibt.
- **`:221`, „Logout räumt die (user-spezifische) Identität.“**
  - Heute behält Logout das Geräte-Zertifikat (`apps/desktop/src-tauri/src/auth.rs:217-221`): „Keep the enrolled
    mTLS cert: it is a DEVICE credential, not a session artifact, and under enforced mTLS it is required to even
    reach the login endpoint … resetting the device identity is a separate, explicit action
    (`enrollment::clear_identity`).“
  - Zurückgesetzt wird über „Geräte-Identität zurücksetzen“, das das Gerät zuerst am Server widerruft
    (`docs/admin/benutzer.html:108`).
- **`:233`, „Verdrahtet **best-effort in `check_session`** (Auto-Trigger beim App-Start …)“.**
  - Heute stößt der Login das Erneuern an (`auth.rs:96-106`): „login is the ONLY renew trigger“, weil der Start keine
    gespeicherte Session mehr wiederherstellt.
  - `check_session` gibt es nicht mehr (`git grep -n 'fn check_session' -- apps/desktop` → kein Treffer).
  - `docs/developer/desktop.html:141`: „Aus Sicherheitsgründen stellt der Client beim Start keine gespeicherte
    Session mehr wieder her“.
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --paths --env --strict
Doku: docs/adr/0002-phase-a-task-plan.md (die Task ist die Doku)
Beweis: origin/main@75ed3e09:
- `grep -n 'Logout räumt\|check_session' docs/adr/0002-phase-a-task-plan.md` → `:221`, `:233`.
- `auth.rs:96-106` (Renew nur beim Login) und `:217-221` (Logout behält das Zertifikat).
- `git grep -n 'fn check_session' -- apps/desktop` → kein Treffer.
Metrik: Sätze in ADR 0002, die dem Code des Desktops widersprechen (Logout räumt, Renew in `check_session`): 2 → 0.
Dedup-Key: ref:docs:adr:stale-statements
HEAD: 75ed3e09
Semantik: `apps/desktop/src-tauri/src/auth.rs:217-221` und `:96-106` (oben zitiert), `docs/developer/desktop.html:141`,
`docs/admin/benutzer.html:108`: „„Geräte-Identität zurücksetzen“ (Desktop) widerruft das Gerät zuerst am Server und
löscht dann sein Zertifikat auf dem Gerät.“
