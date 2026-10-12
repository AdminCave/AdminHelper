<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Kleinpaket 4: der InMemoryTokenStore legt bei einem abgelehnten Erneuern nichts an — Task-Ledger
Status: freigegeben · Branch: feature/loop-kleinpaket-4 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0295, Loop-Futter aus Kevins Triage 2026-10-11; R-0294 bleibt draussen, solange der Builder-Klon kein frpc-Sidecar hat; in den Loop erst nach dem Merge von identity-followups-2; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0295 (Kurz-Ledger ohne Spec)
Heavy: none — der `InMemoryTokenStore` dient nur Tests und Dev; der Stack nutzt den `DbTokenStore`, an dem sich nichts ändert.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-11 als
Loop-Futter triagiert hat. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der
Aufsicht. Zeilenangaben origin/main@dba03852; liegt `identity-followups-2` beim Bau schon auf main, verschieben sich die
Zeilen in `tokens.py` um wenige, die Stelle findet sich über das Symbol.

R-0294 (desktop-rs, ein Test-Backend für `keyring_store`) gehört nicht in dieses Paket: Im Clone des Builder-Loops fehlt
das frpc-Sidecar, also fehlt es auch in jeder Lane, und der Fundament-Lauf von `desktop-rs` wäre rot. Die Zeile bleibt
für eine Bau-Session außerhalb des Loops oder bis der Clone das Sidecar hat.

### T1 — ca-issuer: der InMemoryTokenStore übernimmt ein Zertifikat erst, wenn das Erneuern gelingt (R-0295)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/tokens.py, apps/ca-issuer/tests/test_enroll_renew.py
Änderung: `InMemoryTokenStore.renew` (`apps/ca-issuer/app/tokens.py:247-277`) legt für ein nie erfasstes Zertifikat
heute schon vor dem Signieren eine Legacy-Linie an und trägt das Zertifikat darauf ein:

```python
            if line_id is None:
                if not legacy_admitted(current.not_before, self.installed_at, _now_naive()):
                    raise RenewalRefused("certificate is not in the register")
                line_id = str(uuid.uuid4())
                self._lines[line_id] = _Line(subject_id, scope, legacy_kind, legacy=True)
                self._certs[current.fingerprint] = line_id
```

Scheitert danach `sign()` (eine Ausnahme) oder die zweite Prüfung nach dem Signieren (`raise RenewalRefused("identity
is deprovisioned")`, `:274-275`), bleiben Linie und Eintrag stehen. Der `DbTokenStore` macht in beiden Fällen nichts:
Er läuft in einer Transaktion, die zurückrollt (`apps/ca-issuer/app/db.py:263`). Künftig merkt sich der
`InMemoryTokenStore` die neue Linie zunächst nur und trägt sie samt `current` erst im zweiten `with self._lock:`-Block
ein, nach der zweiten Prüfung und zusammen mit dem Nachfolger. Eine schon erfasste Linie und ihre Prüfung (gesperrt,
Subjekt oder Scope anders) bleiben, wie sie sind.
- Tests in `apps/ca-issuer/tests/test_enroll_renew.py`, am Dateiende, direkt am Store (`InMemoryTokenStore(installed_at=
  <jetzt + 1 Tag>)`, ein selbst signiertes Leaf wie `_self_signed` in `tests/test_db_token_store.py`):
  - `sign()` wirft: `store.line_of(<Fingerprint von current>)` ist danach `None`.
  - `sign()` widerruft die Identität (`store.deprovision(...)`), bevor es den Nachfolger zurückgibt: `RenewalRefused`,
    danach weder `current` noch der Nachfolger erfasst.
  - Ein gelungenes Erneuern übernimmt weiter: `current` und Nachfolger stehen auf derselben Legacy-Linie (`legacy`).
Verify: bash scripts/dev/verify.sh ca-issuer --strict
Doku: keine (intern; nur der Test- und Dev-Store)
Beweis: origin/main@dba03852, Probe mit beiden Fällen am `InMemoryTokenStore` (nicht committet): `AssertionError: a
failed take-over leaves a legacy line behind` und `AssertionError: a refused take-over leaves a legacy line behind`,
`2 failed`, dreimal identisch.
Orakel: mutation-sample — die Linie wieder vor dem Signieren eintragen: die zwei neuen Fehlerfälle rot.
Dedup-Key: ref:ca-issuer:tokens.py:inmemory-legacy-line
HEAD: dba03852
Semantik: keine Stelle in docs/ — gesucht in `docs/developer/` nach dem Test-Store. Im Code: das Protokoll
`TokenStore.renew` (`tokens.py:130-142`) beschreibt die Übernahme als Teil eines gelungenen Erneuerns („a taken-over
certificate opens a legacy line“), und der `DbTokenStore` hält es so (`db.py:263`, eine Transaktion).
