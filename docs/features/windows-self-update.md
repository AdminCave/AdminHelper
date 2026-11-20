
# Windows-Agent: signiertes Self-Update über die Repo-Ebene :8445 (R-1581)

## Problem / Motivation
Linux- und FreeBSD-Agents aktualisiert der Paketmanager aus der Repo-Ebene :8445 (apt, dnf, pkg). Unter Windows gibt
es so einen Paketmanager nicht: Jedes Update ist heute ein Aufruf von `service install` oder `agent-install.ps1` von
Hand auf jedem Host (seit R-1577 idempotent). Die Flotte veraltet still. Kevin 2026-11-17/18: Windows viel einfacher
machen. Kevin 2026-11-20: täglich automatisch, abschaltbar; ein PR samt `release.yml`, den Kevin merged.

## Ziel & Nicht-Ziele
Ziel:
- Der Windows-Dienst prüft einmal am Tag, mit zufälligem Versatz, ob die Repo-Ebene seines Servers unter
  `/windows/` ein neueres Release anbietet.
- Er nimmt nur Dateien, deren Liste die Release-Signatur (minisign, derselbe Schlüssel wie `install.sh`/`update.sh`)
  trägt und deren SHA-256 passt.
- Er tauscht `adminhelper-agent.exe` und `frpc.exe` mit dem Ablauf von `service install` und startet neu.
- Kommt der neue Dienst nicht binnen 15 Minuten durch einen vollständigen Zyklus, stellt er die alten Dateien wieder
  her (`.old`) und probiert diese Version nicht noch einmal.
- Abschaltbar per Schlüssel `AUTO_UPDATE=0` in der Agent-Konfiguration.

Nicht-Ziele (YAGNI):
- kein Update-Knopf in UI oder Server-API;
- kein Downgrade, kein Kanalwechsel: der Agent folgt dem Release seines Servers;
- kein Self-Update unter Linux oder FreeBSD (dort der Paketmanager);
- keine Authenticode-Signatur (R-1582, Kevin vorerst nein);
- keine Änderung an `agent-install.ps1`.

## Betroffene Komponenten & Dateien
- **Agent (Go):**
  - Neues Paket `apps/agent/internal/selfupdate/`, plattformunabhängig, enthält:
    - minisign-Prüfung: Format `ED`, Ed25519 über BLAKE2b-512, dazu die globale Signatur über Signatur und Trusted Comment;
    - Parser für `SHA256SUMS` und `VERSION`;
    - Versionsvergleich;
    - Download über HTTPS mit der gepinnten Gateway-CA;
    - Staging.
  - Windows-Teil: Tausch, Health-Check, Rollback, Tagesplan im Dienst. Er nutzt `apps/agent/internal/service/`
    (`install_plan.go`, `service_windows.go`), `apps/agent/cmd/adminhelper-agent/run_windows.go` und `run.go`.
  - Neue Abhängigkeit `golang.org/x/crypto` (nur `blake2b`, BSD-3-Clause); `THIRD_PARTY_LICENSES.md`.
- **Gateway:** `apps/gateway/nginx.conf:242` gibt `/windows/` frei. Test: `apps/server/tests/test_gateway_container.py`.
- **Release:**
  - Neues Skript `apps/agent/build-windows-update.sh` legt `windows/` mit `VERSION`, `adminhelper-agent.exe`,
    `frpc.exe`, `SHA256SUMS` und `SHA256SUMS.minisig` an.
  - `.github/workflows/release.yml`: ein Schritt vor „Build signed agent repo“ (:480) signiert die Liste mit
    `MINISIGN_SECRET_KEY` und prüft sie gegen den Schlüssel in `scripts/update.sh:48`. Der Repo-Schritt kopiert
    `windows/` neben `freebsd/` (:511).
  - `install.sh`/`update.sh` entpacken das Repo-Asset ohnehin vollständig nach `./repo` und bleiben unverändert.
- **Doku:**
  - `docs/admin/agent-deployment.html` und `docs/en/…` (#windows);
  - `docs/developer/cicd.html` DE+EN (Release-Schritt);
  - `changelog.d/windows-self-update.md`.

## Datenmodell / API / Migrationen
Keine DB, keine Server-API, keine Migration. Das neue Wire-Format ist der Ordner `/windows/` auf :8445:
- `VERSION`: eine Zeile, das Release ohne `v`;
- `SHA256SUMS`: Format von `sha256sum` über `VERSION`, `adminhelper-agent.exe` und `frpc.exe`;
- `SHA256SUMS.minisig`.

Den Trusted Comment schreibt das Release mit Tag und Datei-Rolle. `VERSION` steht in der signierten Liste, so lässt
sich keine ältere signierte Version als neuere ausgeben. Ein Rückspielen eines älteren Satzes scheitert am
Versionsvergleich (nur echt größer wird genommen).

## Externe Integrationen
minisign, Signaturformat laut https://jedisct1.github.io/minisign/:
- `.minisig` = untrusted comment, `base64("ED" || key_id || ed25519(BLAKE2b-512(datei)))`, `trusted comment: …`,
  `base64(ed25519(signatur || trusted_comment))`;
- Public Key = `base64("Ed" || key_id || pk)`.

Nicht verifiziert ist nur, ob die globale Signatur den Text nach `trusted comment: ` oder die ganze Zeile deckt. T1
legt das mit einer Fixture fest, die das echte `minisign` 0.12 erzeugt hat (Signatur, Fälschung, falscher Schlüssel,
Legacy `Ed` abgelehnt).

## Trade-offs & Alternativen
- **Eigene minisign-Prüfung (~80 Zeilen, `crypto/ed25519` + `x/crypto/blake2b`) statt Fremdbibliothek** (etwa
  go-minisign). Empfehlung: eigene; das Format ist klein und fest, die Fixture beweist die Kompatibilität, eine
  Abhängigkeit weniger mit Zugriff auf den Update-Pfad.
- **Tausch durch einen abgelösten Helfer statt im Dienst.** Der laufende Dienst kann sich nicht selbst stoppen und
  dann weiterarbeiten. Er startet die geprüfte neue Binary aus dem Staging-Ordner als abgelösten Prozess
  (`DETACHED_PROCESS`, eigener Prozessgruppe, ohne Job-Bindung) mit einem versteckten Unterbefehl. Der Helfer:
  1. stoppt den Dienst;
  2. sichert `adminhelper-agent.exe` und `frpc.exe` als `.old`;
  3. legt die neuen Dateien ab und startet;
  4. wartet auf die Gesund-Marke, die der neue Dienst nach seinem ersten vollständigen Zyklus schreibt, oder stellt
     `.old` wieder her.

  Empfehlung so. Die Alternative „Dienst beendet sich mit Fehler, die SCM-Recovery startet neu“ hätte keinen
  Rollback.
- **Täglich mit Versatz statt jedem Zyklus:** schont Gateway und Hosts. Das Monitoring darf nie Dienst-Leistung
  kosten, und der Download geschieht nur bei neuer Version.

## Risiken & Rollback
- Ein kaputtes Release legt die Windows-Flotte lahm. Abhilfe: Health-Check mit Rollback, gemerkte Fehlversion, und
  `AUTO_UPDATE=0` hält einzelne Hosts an.
- Gefälschte Dateien auf :8445 (certless): Die Signatur deckt `VERSION` und die Hashes; der Schlüssel ist in die
  Binary gepinnt, Gleichlauf mit `scripts/update.sh` per Test.
- Rotiert der minisign-Schlüssel, braucht die Flotte erst ein Update von Hand. Das gilt heute schon für `update.sh`.
- Rollback des Vorhabens: Revert des PR. Agents ohne das Feature ignorieren `/windows/`.
- Schwere Prüfung: Windows (CI-Jobs auf `windows-latest`, `go test` mit Build-Tag windows). Den Gateway-Teil prüft
  der integration-stack-Job der PR-CI.

## Doku-Impact
Die Seite „Agent-Deployment“, Abschnitt Windows (DE+EN), bekommt einen Absatz „Automatisches Update“: Rhythmus,
Signatur, Rollback und `AUTO_UPDATE=0`. Außerdem beschreibt `cicd.html` (DE+EN) den neuen Release-Schritt.

## Offene Fragen
Keine. Kevin 2026-11-20: täglich automatisch, abschaltbar; ein PR, Kevin merged (`release.yml`).
