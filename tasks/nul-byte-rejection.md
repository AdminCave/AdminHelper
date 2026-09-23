<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# NUL-Byte am Rand ablehnen — Task-Ledger
Status: aktiv · Branch: feature/nul-byte-rejection · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/nul-byte-rejection.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — reine Eingangsprüfung, kein Datenfluss, kein Wire-Format, keine Migration. Am Abschluss am realen Diff gegenprüfen.
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

**Startbedingung:** `feature/input-boundary-validation` muss gemergt sein. Dieses Vorhaben setzt
`app/core/bounds.py` voraus und berührt dieselben Ausschlussdateien; vorher gebaut kollidiert es
mit jedem Task des Vorgängers. Erster Handgriff im Bau: `git merge origin/main`.

**Zwei Regeln für dieses Vorhaben.** Erstens: Ein Ausschluss wird vor dem Entfernen **an der
Route nachgestellt**, nicht anhand seiner dokumentierten Begründung geglaubt — genau dieser
Fehler ist beim Vorgänger passiert (dort T14/T15) und hat zwölf Einträge zu Unrecht fallen
lassen. Zweitens: Kein Test darf grün sein, wenn der Fix fehlt; je Task wird genannt, welche
Produktivzeile man zurücknehmen müsste, damit er rot wird.

**Defaults für die offenen Fragen — (a) und (b) aus der Spec, (c) aus dem Bau; gebaut nach
Empfehlung, von Kevin noch nicht bestätigt (bestätigen oder ändern):** (a) Ein NUL im Pfad oder Query-String antwortet mit
**422**, nicht 400 (T1). (b) `SafeText` wird aus den Feldern **entfernt**, an denen es nach der
Flächenregel nur noch „kein NUL" bedeutet; der Typ bleibt für Felder, die mehr prüfen (T3).
Folge von (b): `SafeText` prüft nur NUL, also fällt es überall weg und hat danach **keinen Nutzer**
mehr. Der Typ bleibt trotzdem stehen, weil die Spec das so sagt; entfernen wäre ein Folgeschritt.
(c) **Die Flächenregel ändert mehr als 500 → 422** (Befund aus dem T3-Review, nachgeprüft): auch
Felder, deren NUL nie eine Textspalte erreicht hat, antworten jetzt 422 statt 200/201/401 —
Passwörter (gehasht), Bootstrap-/Refresh-/Logout-Token (gehasht bzw. vorher am JWT gescheitert),
Connection-`tags` und -Extras (per `json.dumps` als `\u0000` gespeichert) und ein NUL in einem
unbekannten Feld oder Query-Namen. Die Aussage in T3, eine Antwort mit NUL könne es nicht geben,
stimmt für die JSON-Felder nicht: eine vorher gespeicherte Connection mit NUL in Tags ist lesbar,
aber per PUT/Import nicht mehr zurückschreibbar. Gebaut wie die Spec es als Ziel nennt („wer eines
schickt, bekommt 422"), nicht wie ihr Nicht-Ziel („keine Statuscode-Änderung außer 500 → 422") es
nahelegt; der CHANGELOG in T6 sagt es so.

### T1 — NUL im Pfad und im Query-String, vor dem Routing  [x]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/app/main.py, apps/server/tests/test_nul_middleware.py (neu, SPDX)
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @edd4b040 2026-09-23T10:15:29+02:00
Review: approve (sonnet)
Änderung: Eine Middleware, die den **rohen** Pfad und Query-String einer Anfrage auf `U+0000` prüft und mit 422 plus Feldbezug antwortet, bevor geroutet wird. Einreihung neben `IPFilterMiddleware` (`main.py:236` ist das Muster). Deckt in einem Schritt die rund zwanzig String-Pfadparameter und die String-Query-Parameter der beiden FRP-Router ab, die heute einzeln 500 liefern.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_nul_middleware.py
Doku: keine (T6)

### T2 — NUL in jedem String eines Request-Bodies  [x]
Komponente: server · Dateien: apps/server/app/core/bounds.py, apps/server/tests/test_nul_body.py (neu, SPDX)
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @c0fa3fe4 2026-09-23T10:38:13+02:00
Review: approve (sonnet)
Änderung: Eine gemeinsame Request-Basisklasse mit `model_validator(mode="before")`, die die Eingabe rekursiv durchgeht und jeden `str` mit `U+0000` ablehnt. `mode="before"` sieht rohe Werte, muss also Nicht-Dict-Eingaben unbeschadet weitergeben — sonst entsteht genau der 500er, den `_validate_tags` hatte; der Test von dort ist die Vorlage. In JSON steht ein NUL als `\u0000`, deshalb kann die Middleware aus T1 diesen Fall nicht sehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_nul_body.py
Doku: keine (T6)

### T3 — Die 28 Request-Schemas auf die Basisklasse umstellen  [x]
Komponente: server · Dateien: apps/server/app/modules/*/schemas.py, apps/server/app/modules/enrollment/router.py, apps/server/app/modules/audit/router.py, apps/server/tests/test_nul_schemas.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @64bcd685 2026-09-23T11:13:55+02:00
Review: approve (opus, 2. Runde)
Änderung: Jede Klasse, die einen **Request** beschreibt, erbt von der Basisklasse aus T2 statt direkt von `BaseModel`. Antwort-Schemas bleiben unberührt — die Regel gilt für Eingaben, und eine Antwort mit NUL kann es nicht geben, weil die Datenbank keinen speichert. Wo `SafeText` danach nur noch „kein NUL" bedeutet, wird es entfernt; wo es mehr prüft, bleibt es.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (T6)
Abhängt von: T2

### T4 — Dasselbe im Monitoring  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/middleware.py (neu, SPDX), apps/monitoring/app/core/bounds.py, apps/monitoring/app/main.py, apps/monitoring/app/schemas.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_nul.py (neu, SPDX)
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @c55a252b 2026-09-23T11:22:08+02:00
Review: approve (sonnet, 2. Runde)
Dateiliste im Bau präzisiert: statt des Verzeichnisses `apps/monitoring/app/` die konkreten Dateien (`task-close --stage` nimmt keine Verzeichnisse); `routers/agent.py`, weil der Agent-Report ein rohes `dict` als Body nimmt und damit an der Basisklasse vorbeigeht.
Änderung: Beide Mechanismen als eigene Kopie, dazu die 12 Request-Schemas. Die Dienste teilen bewusst keinen Code (CLAUDE.md §1); 40 doppelte Zeilen sind hier billiger als eine geteilte Bibliothek zwischen zwei eigenständigen Diensten.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (T6)
Abhängt von: T1, T2

### T5 — Die NUL-Ausschlüsse fallen weg  [x]
Komponente: server · Dateien: apps/server/tests/schemathesis_exclude.toml, apps/monitoring/tests/schemathesis_exclude.toml
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @ef74ac6d 2026-09-23T11:50:50+02:00
Review: approve (sonnet)
Änderung: Jeden Eintrag, dessen Begründung ein NUL-Byte nennt, **an der Route nachstellen** und erst dann entfernen. Stirbt die Route weiter an etwas anderem, bleibt der Eintrag mit **neuer** Begründung aus diesem Lauf stehen — kein Eintrag bleibt mit alter Begründung. Danach den dienstübergreifenden Fuzz-Lauf fahren und die Bilanz aus einer Auszählung gegen `git show main:` bilden, nicht aus dem Gedächtnis.
Verify: bash scripts/dev/verify.sh server --strict -- -m schemathesis
Doku: keine (T6)
Abhängt von: T1, T2, T3, T4

### T6 — CHANGELOG und die Köpfe der Ausschlussdateien  [ ]
Komponente: server · Dateien: CHANGELOG.md, apps/server/tests/schemathesis_exclude.toml, apps/monitoring/tests/schemathesis_exclude.toml
Änderung: Unter Unreleased: 422 statt 500, wenn eine Eingabe ein NUL-Byte enthält, gleich auf welchem Weg. Umlautfrei, Gedankenstrich „—". In den Dateiköpfen die Bilanz und der Hinweis, dass NUL jetzt flächig am Rand abgelehnt wird, ein Ausschluss dafür also nicht mehr nötig ist.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: CHANGELOG
Abhängt von: T5
