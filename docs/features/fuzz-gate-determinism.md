<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fuzz-Gate deterministisch (R-0063)

Roadmap R-0063 (REG). R-0058 ist abgelehnt (überholt); seine Ursache, der geschlossene Proxy-Client, wird
hier als T4 behoben. Geplant 2026-09-29/30 von der Aufsicht (adminhelper-ac), Entscheidungen Kevin 2026-09-30.

## Problem / Motivation

Der Schemathesis-Gate (Schritt `schemathesis` in `scripts/tests/run.sh`, CI-Job „Schema fuzzing“) läuft
`derandomize=True` (`apps/server/tests/test_schemathesis.py:255`, `apps/monitoring/tests/test_schemathesis.py:208`,
`apps/ca-issuer/tests/test_schemathesis.py:191`, Profil `gate` in `apps/server/tests/conftest.py:46–47` und
`apps/monitoring/tests/conftest.py:35–36`). Trotzdem ist er nicht reproduzierbar:

- Am 2026-09-22 fiel der erste CI-Lauf von PR #29 (Run 35725949370) auf `GET /alerts?offset=2**63` und
  `GET /status?offset=2**63` (`OverflowError`, `@reproduce_failure('6.168.0', …)`), während derselbe Baum lokal
  neunmal `111 passed` lief (kalter Cache, `CI=true`, `PYTHONHASHSEED` 0–8).
- Zwei identische Läufe auf derselben Maschine ziehen verschiedene Daten: Monitoring 3915 Fälle je Lauf,
  942 abweichende `curl`-Zeilen (Explorer der Aufsicht, 2026-09-30, Hypothesis 6.168.0, schemathesis 4.27.5).
- Nicht deterministisch ist allein die Phase `generate`. Die Phasen `examples` und `coverage`
  (`Phase.explicit`) sind bytegleich: Monitoring 3405 Fälle, Server 9192 Fälle, jeweils 0 abweichende Zeilen.
  Auf dem Server ist `generate` 1424 Fälle (13 %) und 51 s von 339 s.
- Hypothesis speist Literale der geladenen Quelldateien ein (`_get_local_constants`), und seit ca. 6.131 gibt
  es keinen Schalter dagegen; `--hypothesis-seed` wird unter `derandomize` ignoriert. Ein fester Seed oder ein
  anderes Profil hilft also nicht. Die übrige Ursache des Nichtdeterminismus ist nicht abschließend bestimmt.
- Zweite nicht-hermetische Eingabe: `hypothesis>=6.168` und `schemathesis>=4.27` stehen lose in
  `apps/server/requirements-dev.txt:22–23`, `apps/monitoring/requirements-dev.txt:18–19`,
  `apps/ca-issuer/requirements-dev.txt:20`; ein neues Release ändert die Fälle ohne Commit.

`DEVELOPMENT.md:110–116` behauptet „reproduzierbar bei gleichem Baum“ — das ist widerlegt.

## Ziel & Nicht-Ziele

Ziel: Ein roter Schemathesis-Schritt im PR-Gate (lokal `run.sh quick`, CI) liegt am Diff und ist lokal
nachstellbar. Die Suche nach neuen Fehlerklassen bleibt im Wochenlauf.

- Der PR-Gate fährt nur `Phase.explicit`. Knopf: `AH_SCHEMATHESIS_EXAMPLES=0` heißt „nur explicit“; `run.sh`
  und `ci.yml` setzen 0. `heavy.sh:76` (100) und `iter.sh` bleiben, der Wochenlauf behält alle Phasen.
- Ersatz für die Fundklasse, die `generate` bisher lieferte („Integer ohne Maximum“ → `2**63`): ein Lint je
  Dienst, dass jeder Integer-Eingang ein `maximum` hat; die Monitoring-Felder bekommen Schranken.
- `hypothesis` und `schemathesis` exakt gepinnt.
- Der Monitoring-Proxy des Servers bekommt im Test einen Stub-Client; die fünf `raises`-Ausschlüsse fallen.

Nicht-Ziele: kein neuer Wochenlauf-Schritt; keine Ursachenforschung im Hypothesis-Quelltext über das
Nötige hinaus; `negative_data_rejection` und die übrigen `checks`-Ausschlüsse bleiben unberührt; kein
Probe-Feld für Ausschlüsse (R-0058 abgelehnt).

## Betroffene Komponenten & Dateien

- `scripts/tests/run.sh:638, :652` (Harness-Pfad), `.github/workflows/ci.yml:318–320` (Harness-Pfad)
- `apps/server/tests/test_schemathesis.py:136–139, :242–263`, `apps/monitoring/tests/test_schemathesis.py:140,
  :205–210`, `apps/ca-issuer/tests/test_schemathesis.py:133, :188–193`
- `apps/*/requirements-dev.txt` (Pins)
- `apps/monitoring/app/schemas.py:27, :47, :56, :66, :78, :120, :183, :185` und
  `apps/monitoring/app/core/bounds.py` (existiert, `Offset` bei :28)
- `apps/server/tests/schemathesis_exclude.toml:178–211` (die fünf Proxy-Einträge);
  Stub-Ziel `apps/server/app/modules/monitoring_proxy/router.py:42` (`_client`), geschlossen in
  `apps/server/app/main.py:230`
- neu: `scripts/tests/schemathesis_determinism.sh` (+ Test), ein pytest-Plugin für das `curl`-Protokoll,
  `tests/test_openapi_integer_bounds.py` je Dienst
- Doku: `DEVELOPMENT.md:107–116`, `docs/developer/cicd.html:251`, `docs/en/developer/cicd.html:249`, CHANGELOG

## Datenmodell / API / Migrationen

Keine Migration. Die Monitoring-Schranken verengen das Request-Schema von bis zu acht Feldern
(`AlertRuleCreate/Update.cooldown_minutes`, `CheckCreate/Update.consecutive_fails`,
`MaintenanceInput.weekdays[]`, `MaintenanceInput.duration_minutes`, `TemplateAlertDef.cooldown_minutes`,
`TemplateCheckDef.consecutive_fails` — Zählung der Planung über `app.openapi()`, der Explorer zählte 12; die
endgültige Liste bestimmt der Lint aus T3). Regel: eine Domänengrenze, wo das Modell eine hat
(`weekdays` 0–6, heute nur im Validator `schemas.py:196–200`), sonst die int32-Obergrenze wie bei R-0052.
oasdiff: `request-property-max-set warn` (`scripts/dev/oasdiff-severity.levels:9`, dazu
`request-parameter-max-set warn` :1) — eine hinzugefügte Obergrenze ist WARN, nicht ERR;
`openapi-breaking.sh` bleibt grün (Exit ≠ 0 nur bei ERR, Kopf des Skripts :16–17).

## Externe Integrationen

Hypothesis/schemathesis: Aussagen zu `derandomize`, `@seed`, `--hypothesis-seed` und den lokalen Konstanten
stammen aus dem Quelltext 6.168.0 (`hypothesis/_settings.py:684–690`, `core.py:716–723`,
`internal/conjecture/providers.py:325–380`); ob künftige Versionen einen Schalter für die Konstanten
bekommen: nicht verifiziert. Ob `settings(max_examples=0)` gültig ist: nicht verifiziert — mit
`phases=[Phase.explicit]` ist die Zahl ohne Wirkung, der Bau setzt dann `max_examples=1`, falls 0 abgelehnt wird.

## Trade-offs & Alternativen

- **PR-Gate nur explicit (gewählt)** gegen „alle Phasen lassen“: ~13 % der Fälle und die Suche nach neuen
  Klassen wandern in den Wochenlauf; dafür ist jeder rote PR-Lauf am Diff und lokal nachstellbar. Der
  Integer-Lint ersetzt die bekannte Klasse deterministisch.
- **Seed ausgeben statt explicit**: geht unter `derandomize` nicht (Seed wird ignoriert). Verworfen.
- **Monitoring-Schranken (gewählt)** gegen Allowlist: gleiche Klasse wie R-0052 im Server, WARN bei oasdiff.
- **Pins exakt (gewählt)**: Bumps von Hand in der Dependency-Runde; dafür hängt der Gate nicht an PyPI.

## Risiken & Rollback

- Ein echter Fund, den nur `generate` zieht, kommt erst im Wochenlauf. Gegenmittel: der Lint (T3), der
  Wochenlauf mit 100 Beispielen.
- Die Monitoring-Schranken lehnen Werte ab, die heute angenommen werden (etwa `consecutive_fails` > 2³¹−1);
  kein realer Client sendet solche Werte (nicht verifiziert).
- Rollback je Task per `git revert`; T2 allein zurückzunehmen stellt den alten Gate wieder her.

## Doku-Impact

`DEVELOPMENT.md` „Generatoren“ (die Reproduzierbarkeits-Aussage), `docs/developer/cicd.html` DE+EN (Zeile
Schema-Fuzzing), CHANGELOG; Kommentare in `run.sh`, `ci.yml` und den drei `test_schemathesis.py`.

## Offene Fragen

Keine — Kevin hat am 2026-09-30 entschieden: PR nur explicit, Schranken statt Allowlist, Pins exakt,
R-0058 ablehnen und Proxy-Stub, ein Ledger mit fünf Tasks.
