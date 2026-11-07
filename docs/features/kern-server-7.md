# kern-server-7 — Servernamen ohne ':' und ohne Windows-Gerätenamen

Roadmap: R-1056 (Zug `tasks/kern-server-7.md`).

## Problem / Motivation

`_validate_server_name` (`apps/server/app/modules/servers/schemas.py:14`) lässt heute zwei Arten von Namen zu, die
unter Windows Probleme machen:
- Namen mit `:`.
- Reservierte Gerätenamen wie `aux`, `con` oder `nul`.

Der Name wird im FRP-Bulk-ZIP zu einem Pfadteil, nämlich `clients/<name>/frpc.toml`
(`apps/server/app/modules/frp/generate_router.py:244`). Ein Windows-Entpacker liest einen solchen Pfadteil anders.
Gesetzt werden kann der Name nur über die Admin-Routen.

Kevin hat am 2026-11-06 entschieden:
- Neue und umbenannte Servernamen mit `:` oder einem reservierten Windows-Namen werden mit `422` abgelehnt.
- Bestehende Namen bleiben gültig und werden im FRP-Bulk-ZIP weiter ausgeliefert.

## Ziel & Nicht-Ziele

**Ziele**

`POST /api/servers` lehnt einen solchen Namen mit `422` ab, ebenso `PUT /api/servers/{id}` mit einem neuen `name`. Abgelehnt wird ein Name, der
- `:` enthält, oder
- einen reservierten Windows-Namen trägt, laut Microsoft
  ([Naming Files, Paths, and Namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)):
  - `CON`, `PRN`, `AUX`, `NUL`
  - `COM1`–`COM9` und `COM¹`, `COM²`, `COM³`
  - `LPT1`–`LPT9` und `LPT¹`, `LPT²`, `LPT³`
  - Groß- und Kleinschreibung zählt nicht.
  - Der Name zählt auch mit Endung direkt dahinter. Microsoft: „NUL.txt and NUL.tar.gz are both equivalent to NUL“.

**Nicht-Ziele**

- **Bestand:** Ein `PUT`, der den gespeicherten Namen unverändert mitschickt, bleibt erlaubt. Die Web-Oberfläche
  schickt beim Bearbeiten den ganzen Server mit, und ein Altname soll das Bearbeiten nicht sperren.
- **Bulk-ZIP und Generatoren:** `_path_refused` und `name_refused` in `apps/server/app/modules/frp/` bleiben
  unverändert. Kevin hat entschieden: Bestand wird weiter ausgeliefert.
- **Weitere Windows-Regeln:** Keine weiteren Zeichen (`< > | ? *`), kein Punkt oder Leerzeichen am Ende. Kevins
  Entscheidung nennt nur `:` und die reservierten Namen.
- **Migration:** keine.

## Betroffene Komponenten & Dateien

- **`apps/server/app/modules/servers/schemas.py`:** neue Funktion `reject_windows_unsafe_server_name`.
- **`apps/server/app/modules/servers/router.py`:** Aufruf an zwei Stellen.
  - `create_server`
  - `update_server`, aber nur, wenn `name` gesendet wurde und sich vom gespeicherten unterscheidet.
- **Tests:**
  - `apps/server/tests/test_servers_schemas.py` für die reine Funktion.
  - Neue Datei `apps/server/tests/test_servers_name_windows.py` für die Routen.
- **`apps/server/app/modules/frp/generate_router.py`:**
  - Nur der Docstring von `_path_refused` ändert sich.
  - Er sagt dann, dass die Windows-Regel bewusst nicht hier greift.

## Datenmodell / API / Migrationen

**API-Vertrag:** Zusätzliche `422`-Fälle in `POST /api/servers` und `PUT /api/servers/{id}`. Kevin hat das freigegeben.

**Wo die Prüfung sitzt:** Sie liegt im Router, nicht im Pydantic-Schema. Nur der Router kennt den gespeicherten Namen.

**Form der Antwort:** `HTTPException(422, detail=<englischer Text>)`.
- Das ist dieselbe Form wie andere fachliche `422` im Server, etwa in `ansible/router.py:61`.
- Die Pydantic-`422` liefert dagegen eine Liste.
- Der Web-Client zeigt ein `detail` als Text direkt an, etwa in `apps/web/src/lib/api/frp.ts:28`.

**Kein Vertrags-Drift:** Agent und Desktop legen keine Server an.

## Externe Integrationen

Microsoft Learn, „Naming Files, Paths, and Namespaces“, abgerufen am 2026-11-06. Daraus stammen die Liste der
reservierten Namen, die Regel zur Endung und der Doppelpunkt als reserviertes Zeichen.

## Trade-offs & Alternativen

**Prüfung im Schema statt im Router**
- Vorteil: einfacher.
- Nachteil: Jeder `PUT` eines Altnamens würde mit `422` scheitern, auch wenn sich nur der Hostname ändert. Das
  widerspricht „Bestand bleibt gültig“.
- Deshalb: Router.

**Nur exakte Gerätenamen, ohne Endung**
- Dann käme `nul.example` durch.
- Den legt Windows aber auf das Gerät `NUL` (Microsoft-Zitat oben).
- Empfohlen und geplant: mit Endung.

## Risiken & Rollback

**Risiko:** Ein Admin, der heute einen Namen wie `aux.lab` neu anlegen will, bekommt `422`. Das ist gewollt.

**Rollback:** Revert des Merges. Es gibt keine Datenänderung.

## Doku-Impact

- **`docs/developer/api-reference.html` und `docs/en/developer/api-reference.html`, Eintrag `POST /api/servers`:**
  - der neue `422`-Fall
  - die Bestandsregel beim `PUT`
- **`changelog.d/kern-server-7.md`.**

## Offene Fragen

Keine. Kevin hat am 2026-11-06 entschieden (Notiz an R-1056).
