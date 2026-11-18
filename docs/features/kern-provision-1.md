# kern-provision-1 — Provisionieren je Plattform

Roadmap: R-1594, R-1595, R-1596, R-1597 (FEAT, Kevin 2026-11-18 diktiert: „Provisionieren je Plattform viel
einfacher“). R-1596 ersetzt R-1579.

## Problem / Motivation
- **R-1594:** `servers.os_type` ist Freitext (`apps/server/app/modules/servers/models.py:22`, Eingabe im Desktop
  `ServerModal.svelte`). Desktop-Code rät daraus per `includes('windows')` (`ServerDetail.svelte:35`,
  `ModuleCard.svelte:57`); für das Provisionieren taugt das nicht.
- **R-1595:** Der Provisionierungs-Tab (`apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte`) kennt nur
  Linux und baut die Befehle fest im Desktop. Eine neue Plattform braucht heute ein Desktop-Release, und der Tab zeigt
  auch, was die Installation gar nicht ausliefert.
- **R-1596:** Für Windows, FreeBSD und OPNsense gibt es keinen Befehl im Desktop, nur die Doku. Aktualisieren, neu
  registrieren und entfernen fehlen ganz.
- **R-1597:** Nach dem Kopieren des Befehls sieht der Admin nicht, ob die Registrierung durchlief. Die Daten dafür
  gibt es schon: Token `usedAt`, ausgestellte Zertifikate, Liveness im Monitoring, frps-Proxy-Status.

## Ziel
1. **Plattform als Auswahl** (R-1594): `os_type` nimmt nur `linux`, `windows`, `freebsd`, `opnsense`, `other` oder
   `null`. Eine Alembic-Migration ordnet die Freitexte zu: Linux-Distributionsnamen → `linux`, `win…` → `windows`,
   `freebsd` → `freebsd`, `opnsense` → `opnsense`, sonst `other`; leer bleibt `null`. Die API lehnt andere Werte mit
   422 ab. Der Desktop zeigt ein Auswahlfeld. Weicht die vom Agent gemeldete Plattform ab (Host-Fakten nach dem
   ersten Bericht), zeigen die Server-Ansicht und das Provisionieren-Fenster einen Hinweis. FreeBSD und OPNsense
   melden beide `freebsd` und gelten untereinander nicht als Abweichung.
2. **Katalog** (R-1595): `GET /api/provisioning/platforms` (Admin, Scope access). Je Plattform:
   - `available` und `versions` aus dem Paket-Repo, das der Server lesend eingebunden bekommt (`./repo` → `REPO_DIR`,
     Vorgabe `/app/repo`, wie das Gateway es auf :8445 ausliefert):
     - apt: `apt/dists/stable/InRelease` und die `Version:` aus `Packages`
     - rpm: `rpm/repodata/repomd.xml`
     - FreeBSD und OPNsense: die ABIs unter `freebsd/<ABI>/meta.conf` mit `adminhelper-agent-*.pkg` bzw.
       `os-adminhelper-*.pkg`
     - Windows liegt nicht im Repo, sondern am GitHub-Release.
   - `arch`, `prerequisites`: unterstützte Versionen und die ausgehenden Ports 443, 8444, 8445, bei Tunnel 7000.
   - `commands` je Aktion (`install`, `update`, `reregister`, `remove`), jeweils `shell` (`bash`, `sh`,
     `powershell`), ein fester Befehlskopf (`base`) und benannte Argumente
     (`{"flag": "--server", "value": "serverUrl"}`, optional bzw. nur „für Automatisierung“).
   - `doc`: Seite und Anker je Sprache.

   Der Server liefert nie fertig zitierten Text. Werte setzt der Desktop ein und zitiert je Shell; eine unbekannte
   Wert-Art oder Shell ergibt keinen Befehl.
3. **Provisionieren-Fenster** (R-1596) ersetzt den Tab:
   - Plattform wählen, vorgewählt aus `osType`.
   - Voraussetzungen anzeigen.
   - Ein Befehl mit URL, Server-ID und CA-Fingerabdruck. Der Token wird immer verdeckt abgefragt.
   - Umschalter „Für Automatisierung“: Token als Parameter, mit Warnung.
   - Reiter Installieren, Aktualisieren, Neu registrieren, Entfernen.
   - Link auf den Doku-Abschnitt.
   - Die Doku `agent-deployment` wird je Plattform neu gegliedert (DE+EN).
4. **Live-Fortschritt** (R-1597): `GET /api/servers/{id}/provision/progress` liefert:
   - Token: neuester, `usedAt`/`expiresAt`
   - Zertifikat: neuestes der Agent-Identität
   - erster Bericht: Liveness und Host-Fakten über eine neue interne Monitoring-Route
     `GET /agent/{server_id}/state`; bei Ausfall `null`, nie ein Fehler
   - Tunnel: frps-Proxy-Status, nur wenn der Server einen Tunnel hat
   - `reportedPlatform` und `platformMismatch`

   Das Fenster fragt während eines offenen Vorgangs alle 5 s ab. Hinweise bei Hängern: Token abgelaufen; kein Bericht
   nach 5 min → Ports, Uhrzeit, Proxy. Am Ende „Monitoring-Vorschläge ansehen“.

## Nicht-Ziele
- Windows-Installationsbefehl: kommt mit R-1578 (ops-10). Bis dahin trägt Windows im Katalog nur „Neu registrieren“,
  „Entfernen“ und den Doku-Anker.
- Kein Server-Push (SSE) für den Fortschritt; kein neuer Agent-Befehl; keine Desinstallation durch den Server.
- Web-Frontend: es nutzt `osType` nicht (geprüft), nichts zu tun.

## Betroffene Komponenten & Dateien
- **Server:**
  - `app/modules/servers/{models,schemas,router}.py`
  - neue Migration unter `alembic/versions/` (Kopf heute `b7c9d1e3f5a7`; #569/kern-notify-6 bringt zwei weitere,
    daher nach dessen Merge)
  - `app/modules/provisioning/` (neu `catalog.py`, `router.py`, `schemas.py`)
  - `app/core/config.py` (`REPO_DIR`), `app/main.py` (Router)
  - `tests/openapi.snapshot.json`
- **Monitoring:** `app/routers/agent.py`. Bewusst nicht `checks.py`, das `feature/kern-monitoring-45` ändert.
- **Compose:** `docker-compose.yml`, Dienst `server`: `./repo:/app/repo:ro`. Ändert auch `feature/kern-deps-5`, daher
  nach dessen Merge oder mit `origin/main` zusammengeführt.
- **Desktop-UI:**
  - `components/infra/{ServerModal,ServerDetail}.svelte`
  - `tabs/ProvisioningTab.svelte` → neu `ProvisioningDialog.svelte` plus Teile
  - `lib/api/{provisioning,types}.ts`, `lib/models/infra.ts`
  - neu `lib/utils/powershell.ts`
  - `lib/i18n/dictionaries.ts`
  - Tests
  - E2E `apps/desktop/e2e/test/specs/provisioning.live.js`
- **Doku:** `docs/admin/agent-deployment.html` + EN, `developer/api-reference.html`, `changelog.d/kern-provision-1.md`.

## Datenmodell / API / Migrationen
- **Migration** `os_type` Freitext → Plattformwert (Kevin: Auswahlfeld mit Migration entschieden, Unbekanntes →
  Sonstiges). Downgrade lässt die Werte stehen, der Freitext ist verloren.
- **API-Vertrag:**
  - `osType` wird ein Enum.
  - neu `GET /api/provisioning/platforms` und `GET /api/servers/{id}/provision/progress`
  - intern `GET /agent/{id}/state` am Monitoring
  - Desktop-Typen ziehen nach; der Web-Client nutzt beides nicht.

## Externe Integrationen
Keine neue. PowerShell-Zitierung nach der Sprachreferenz (`about_Quoting_Rules`: einfaches Anführungszeichen, `'`
verdoppelt), vor T6 per WebFetch nachlesen.

## Trade-offs & Alternativen
- **Repo-Inhalt lesen statt konfigurieren** (gewählt): Der Server bindet `./repo` nur lesend ein und sieht, was
  `update.sh` wirklich ausgerollt hat. Die Alternative, eine Env-Liste der Plattformen, veraltet still.
- **Strukturierte Befehle statt Textvorlagen** (gewählt): Der Desktop zitiert jeden Wert je Shell. Eine Vorlage mit
  Platzhaltern würde das Zitieren in den Server-Text ziehen (verboten laut R-1595).
- **Fortschritt per Abfrage alle 5 s** statt SSE: Das Fenster ist kurz offen, und die Daten liegen verteilt
  (Server-DB, Monitoring, frps).

## Risiken & Rollback
- Die Migration ist verlustbehaftet für Freitext: Rollback per Downgrade stellt den Text nicht her. Ein Backup vor dem
  Update deckt das ab (`update.sh` sichert die DB).
- Ein fehlendes `./repo` (Release ohne Repo-Asset) ergibt `available: false` überall außer Windows: das Fenster zeigt
  dann den Hinweis statt eines Befehls.
- Ein Code-Rollback per Revert ist möglich, solange der Revert die Migration mitnimmt.

## Doku-Impact
`docs/admin/agent-deployment.html` DE+EN neu je Plattform gegliedert (Installieren, Aktualisieren, Neu registrieren,
Entfernen). Provisionieren-Fenster und Plattformfeld in der Desktop-Doku, `docs/developer/api-reference.html` DE+EN (zwei Routen),
`changelog.d/kern-provision-1.md`. `agent-deployment.html` ändern ops-8, kern-windows-1 und ops-9: die Doku-Task baut
erst nach deren Merge auf frischem `origin/main`.

## Offene Fragen
- **Doku-Link im Fenster** (sichtbares Verhalten): Die Doku liegt nur als HTML im Repo, eine gehostete Fassung ist
  nicht belegt. Empfehlung: Link auf `https://github.com/AdminCave/AdminHelper/blob/main/docs/…#anker`. GitHub zeigt
  dort den Quelltext; besser wäre eine gehostete Doku, falls admincave.com sie trägt. → T9 `[?]`; T7 baut das Fenster
  ohne Link.
