# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Changed

- **Einheitliches, lesbares Logging in Server und Monitoring.** Beide Dienste
  konfigurieren das Logging jetzt zentral mit Zeitstempel, Level und Logger-Name
  (`2026-06-15 11:25:53 INFO     adminhelper.auth …`) auf stdout — sichtbar via
  `docker compose logs`. Der Server hatte zuvor **gar keine** Logging-Konfiguration:
  alle `INFO`-Meldungen wurden verworfen, Warnungen/Fehler kamen ohne Zeitstempel.
  uvicorn-Zugriffs-/Fehlerlogs laufen über dasselbe Format. Die Ausführlichkeit ist
  über die Env-Variable `LOG_LEVEL` steuerbar (Default `INFO`).
- **Begrenzte Container-Logs (Log-Rotation).** `docker-compose.yml` cappt jeden Service
  über den Docker-`json-file`-Treiber (`max-size: 10m`, `max-file: 5` → max. 50 MB/Service)
  via `x-logging`-Anker — verhindert, dass `docker compose logs` ungebremst die Platte
  füllt. `LOG_LEVEL` ist als `.env`-Knopf in der Compose dokumentiert (Default `INFO`).
- **Agent: strukturiertes Logging mit rotierender Logdatei.** Der Go-Agent nutzt jetzt
  `log/slog` (Level via `LOG_LEVEL`-Env oder `--log-level`) und schreibt zusätzlich zu
  stdout/journal in eine größenrotierte Datei (`/var/log/adminhelper/agent.log` bzw.
  `%ProgramData%\AdminHelper\logs\agent.log`, 10 MB × 5, komprimiert) — eine durchgehende
  Spur für Fehler-Reports. Die zuvor **doppelte** `logMsg`-Implementierung (frpc + monitor)
  entfällt; Logzeilen tragen jetzt Level + Komponente. Neue Abhängigkeit:
  `gopkg.in/natefinch/lumberjack.v2`.

### Added

- **Audit-Trail (wer hat wann was getan).** Neue **append-only** `audit_log`-Tabelle
  protokolliert sicherheits- und änderungsrelevante Aktionen mit Actor (User *oder* API-Key),
  Quell-IP und Zeitstempel: Connections (anlegen/ändern/löschen **und Nutzung** über das
  `/touch`, das der Desktop beim Verbinden aufruft), Server, Benutzer, API-Keys,
  FRP-Configs/Tunnel und Ansible-Playbooks sowie Login (Erfolg/Fehlschlag), Logout und
  Erst-Admin-Bootstrap. Einsehbar über die neue admin-only Web-Ansicht **„Audit-Log"**
  (filterbar nach Actor/Objekt/Aktion) bzw. `GET /api/audit` (paginiert). Das Schreiben ist
  best-effort und kann die auditierte Aktion nie brechen; der Actor wird über `request.state`
  gebunden (nicht contextvars, die in synchronen Endpoints verloren gehen). Ein täglicher
  System-Job löscht Einträge älter als `AUDIT_RETENTION_DAYS` (Default 365, `0` = unbegrenzt) —
  der einzige Löschpfad der append-only Tabelle.

## [0.34.0] - 2026-06-15

### Changed

- **Release-gebundener Update-Mechanismus (`scripts/update.sh`).** Jedes Release legt
  jetzt ein **verifiziertes Runtime-Bundle** bei (`adminhelper-runtime-vX.Y.Z.tar.gz`:
  `docker-compose.yml`, alle Ops-Skripte, `MANIFEST.sha256`, `VERSION`). `update.sh`
  löst die Zielversion auf, lädt **genau dieses eine Asset**, prüft es gegen die
  `SHA256SUMS` des Release und tauscht die Laufzeit-Dateien **atomar** — so landet jede
  Datei-Änderung eines Release (neue/geänderte/entfernte Skripte, neue Compose)
  zuverlässig auf dem Host; „welche Dateien zu Release X gehören" steht im Release, nicht
  im Skript. Ein nacktes `./scripts/update.sh` geht auf das **neueste veröffentlichte
  Release** (Prereleases ausgenommen) und verweigert einen stillen Downgrade; `--ref
  vX.Y.Z` pinnt gezielt, `--redeploy` zieht nur die gepinnten Images neu, `--check` ist
  ein Trockenlauf. Vor dem Tausch wird gesichert (Daten **und** ein Laufzeit-Snapshot);
  schlägt der Healthcheck fehl, rollt das Skript Laufzeit-Dateien **und** Image-Pins
  automatisch zurück (`--no-rollback` zum Debuggen). Der Updater **aktualisiert sich
  selbst** (Re-exec in die neue `update.sh` aus dem Release). Behebt, dass neu
  hinzukommende Ops-Dateien Alt-Installs früher nie erreichten.
- **`scripts/install.sh` nutzt dasselbe Bundle** und installiert per Default das neueste
  Release (vorher `--ref main`-Default). Release-Tags ohne Bundle (≤ 0.33.0) und
  Branch-Refs fallen auf den Einzeldatei-Download (raw) zurück.

### Added

- **Runtime-Bundle als Release-Asset** samt `MANIFEST.sha256`/`VERSION`; `release.yml`
  baut und hängt es an. Neuer CI-Job `ops-scripts` (shellcheck + hermetischer
  `update.sh`-Sandbox-Test, `scripts/tests/update_test.sh`) und ein Release-Guard, der
  die Desktop-Version in `tauri.conf.json` gegen den Tag prüft.

### Migration

- **Installs vor 0.34.0:** deren altes `update.sh` kennt das Bundle noch nicht. Einmalig
  über den Install-Einzeiler neu holen **oder** ein `./scripts/update.sh --ref v0.34.0`
  fahren — danach ist der Updater self-updating.

## [0.33.0] - 2026-06-14

### Added

- **Deinstallations-Skript `scripts/uninstall.sh`.** Entfernt eine Server-Installation
  restlos: alle Container des Compose-Projekts, das Netzwerk und **alle** Named Volumes
  (inkl. `ca-pki` mit der Root-CA, `postgres-data`, `victoria-data`), dazu die
  Host-Bind-Mounts `./data`/`./certs` und die Secrets-Datei `.env`. Da `./data`/`./certs`
  dem Container-User (`uid 10001`) gehören, löscht das Skript sie als root in einem
  Wegwerf-Container — ohne `sudo` vorauszusetzen. Standardmässig **interaktiv**: das Skript
  fragt für jede Kategorie (Stack, Volumes, `./data`/`./certs`, `.env`, Backups, Images)
  einzeln nach und löscht erst, nachdem alle Fragen beantwortet sind. `./backups/` und die
  Docker-Images bleiben per Default erhalten (`--purge-backups` / `--rmi` entfernen auch sie
  bzw. belegen die jeweilige Frage mit JA vor); `--yes` fährt nicht-interaktiv mit den
  Defaults. Das Skript wird von `install.sh`/`update.sh` mit ausgeliefert, liegt also nach
  der Installation lokal im Install-Verzeichnis.
- **Desktop: lokaler Modus direkt vom Login erreichbar.** Der Login-Screen hat einen
  Knopf „Ohne Server fortfahren (nur lokale Verbindungen)", der in den lokalen Modus
  wechselt (reine Verbindungs-Verwaltung, keine Anmeldung). Bisher war der Login-Screen
  eine Sackgasse, sobald der Client im Server-Modus war — der Modus-Umschalter lebte nur
  in den Einstellungen innerhalb der App, die ohne Anmeldung nicht erreichbar ist.
- **Desktop: Server-URL und Benutzername werden auf dem Login-Screen vorausgewählt.** Nach
  einer erfolgreichen Server-Anmeldung merkt sich der Client die Server-URL und den
  Benutzernamen (neues Feld `lastUsername`; das Passwort wird **nie** gespeichert) und füllt
  beide beim nächsten Start vor — es muss dann nur noch das Passwort eingegeben werden.

### Changed

- **Desktop verlangt jetzt bei jedem Öffnen ein Passwort (Server-Modus).** Der Client stellt
  beim Start keine gespeicherte Session mehr still aus dem Keyring wieder her. So kann an einem
  entsperrten Rechner niemand ohne Passwort Verbindungen aufbauen oder Einstellungen ändern.
  Die laufende Session erneuert ihre Tokens weiterhin automatisch; nur das Wiederherstellen
  über einen Neustart entfällt. Die mTLS-Geräte-Identität bleibt erhalten.

### Fixed

- **Lokale Verbindungen wurden vom Server-/Sync-Abruf überschrieben.** Alle drei Modi teilten
  sich die Datei `connections.json`; ein Server-Login oder ein Sync überschrieb sie mit den
  abgerufenen Daten, sodass lokale Verbindungen bei einem Wechsel Lokal → Server → Lokal verloren
  gingen. Der lokale Modus hat jetzt einen eigenen Speicher (`connections.local.json`), getrennt
  vom Server-/Sync-Cache (`connections.json`); ein Abruf überschreibt ihn nie. Bestehende lokale
  Daten werden beim ersten Start nach dem Update einmalig migriert.
- **Desktop-Logout überschrieb lokale Verbindungen.** Beim Abmelden leerte der Client den
  Verbindungs-Cache via `saveConnections([])` und überschrieb damit die `connections.json` —
  obwohl diese Datei der Speicher des lokalen Modus ist (Server-Verbindungen liegen nur im
  Speicher). Wer lokale Verbindungen angelegt, sich dann an einem Server an- und wieder
  abgemeldet hatte, verlor sie. Logout leert jetzt nur noch den Speicher.
- **Desktop-Modus-Wechsel ließ eine veraltete Session zurück.** Der Wechsel auf den lokalen
  oder Sync-Modus verwarf die aktive Server-Session nicht. Ein späterer Wechsel zurück auf
  einen (geänderten) Server konnte dadurch Daten vom alten Server laden statt eine frische
  Anmeldung zu erzwingen. Beim Verlassen des Server-Modus wird die Session jetzt verworfen;
  zudem nullt der „Abmelden"-Knopf im Einstellungs-Dialog jetzt auch die In-Memory-Session.

## [0.32.1] - 2026-06-13

### Fixed

- **Logout sperrte unter enforced mTLS aus.** Der Desktop-Client löschte beim Logout die
  enrollte mTLS-Identität (Key+Cert+CA). Da das Cert unter erzwungenem mTLS nötig ist, um den
  Login-Endpoint auf `:443` überhaupt zu erreichen, konnte man sich danach nicht mehr anmelden
  (Gateway: „no required SSL certificate was sent") — bis ein Admin ein neues Enrollment-Token
  mintete. Logout verwirft jetzt nur die Session-Tokens; das Geräte-Cert bleibt erhalten.

## [0.32.0] - 2026-06-13

### Added

- **Desktop-Client wird zum Verwaltungs-Cockpit (Infrastruktur-Hub).** Der Desktop ist nicht mehr
  nur Verbindungs-Launcher: Im neuen server-zentrischen „Infrastruktur"-Bereich (nur im
  Server-Modus) verwaltet der Admin sein Server-Inventar und pro Server in Tabs dessen
  Verbindungen, FRP-Tunnel, Monitoring und Provisionierung.
  - **Server-Inventar:** Server anlegen/bearbeiten/löschen.
  - **Provisionierung:** Einmal-Token erzeugen + Agent-`provision`-Befehl pro Server anzeigen.
  - **Verbindungen:** server-seitiges CRUD pro Server (ssh/rdp/vnc/web/custom). Auch der
    Verbindungs-Launcher schreibt im Server-Modus jetzt server-seitig statt nur lokal.
  - **FRP-Tunnel:** Tunnel pro Server anlegen/bearbeiten/löschen (STCP/HTTPS); die
    FRP-Server-Konfiguration wird als Auswahl referenziert (bleibt Web-Admin-Sache).
  - **Monitoring vollständig bearbeitbar:** Checks pro Server (alle Check-Typen mit Konfiguration)
    sowie Alert-Regeln und Templates fleet-weit auf der Monitoring-Seite.
  - **Ansible:** Playbooks im Desktop anlegen/bearbeiten/löschen (zusätzlich zum bestehenden
    Ausführen).

### Changed

- **Web-Admin-Panel ist jetzt reine Instanz-Verwaltung.** Es behält Benutzer-, API-Key-,
  Hook-Verwaltung und die FRP-**Server-Konfiguration**; die operative Fleet-Arbeit ist in den
  Desktop-Client umgezogen. Die Standard-Seite nach dem Login ist jetzt „Benutzer". Die
  User↔Server-Zuweisung bleibt im Web (im Benutzer-Dialog, gespeist aus einer reinen
  Lese-Server-Liste).

### Removed

- **Operative Funktionen aus dem Web-Frontend entfernt** (in den Desktop-Client umgezogen):
  Server-Inventar, Verbindungs-Verwaltung, FRP-**Tunnel**-Verwaltung, Monitoring-Bearbeitung
  (Checks/Alerts/Templates) und Ansible-Playbook-Verwaltung. **Breaking** für reine
  Web-Nutzer: diese Aufgaben erfolgen nun im Desktop-Client.

## [0.31.0] - 2026-06-13

### Added

- **Browser-`.p12`-Export mit Speicherort-Auswahl.** Beim Export des Browser-Zertifikats
  (Desktop → Einstellungen) öffnet der Client jetzt einen nativen Speichern-Dialog
  (`tauri-plugin-dialog`) — der Nutzer wählt, wohin die `.p12` geschrieben wird (Default-Name
  `adminhelper-browser.p12`), statt sie in einem versteckten App-Daten-Verzeichnis suchen zu
  müssen. Abbruch des Dialogs bricht ohne Enrollment ab. (Das `.p12`-Format bleibt unverändert
  — Legacy, aber von allen aktuellen Browsern akzeptiert.)

## [0.30.4] - 2026-06-13

### Fixed

- **Re-Install über ein altes Postgres-Volume scheiterte unverständlich.** Ein
  `postgres-data`-Volume aus einem abgebrochenen Versuch ist mit einem anderen
  `POSTGRES_PASSWORD` initialisiert als eine frisch generierte `.env` (Postgres setzt das
  Passwort nur beim ersten Init) — die DB-Auth scheiterte dauerhaft und die Readiness-Schleife
  lief in einen kryptischen 240-s-Timeout. `install.sh` erkennt jetzt das
  `password authentication failed` und bricht mit klarer Anleitung ab; neues `--reset`-Flag
  räumt vorab `docker compose down -v` weg.

## [0.30.3] - 2026-06-13

### Changed

- **Installs pinnen die Image-Version fest.** `install.sh` schreibt die `*_IMAGE`-Tags in
  `.env` auf die Version, von der installiert wurde (`--ref vX.Y.Z` → `:X.Y.Z`, `main` →
  `:main`), statt am floatenden `:latest` zu bleiben — ein Install ist reproduzierbar und
  springt nie unbemerkt auf eine neue Version bei `docker compose pull`. `update.sh --ref`
  re-pinnt auf die Zielversion; ein nacktes `update.sh` zieht die gepinnte Version neu
  (Upgrade = bewusstes `--ref vNEU`). `:latest` bleibt nur der Compose-Fallback ohne `.env`.

## [0.30.2] - 2026-06-13

### Fixed

- **Einzeiler brach unter `curl | bash` an der ersten Rückfrage ab.** Die interaktiven
  `read`-Prompts (Domain/Passwort/Bestätigung) lasen `stdin` — unter `curl | bash` ist das
  die Script-Pipe, nicht das Terminal, also kam sofort „Abgebrochen" ohne Eingabemöglichkeit.
  Die Prompts kommen jetzt aus `/dev/tty`; ohne Terminal bricht `install.sh` mit einer klaren
  Meldung ab (Hinweis auf `--admin-password … --yes`).

## [0.30.1] - 2026-06-13

### Changed

- **Update-Ablauf dokumentiert.** Die Installations-Doku (DE+EN) beschreibt jetzt den
  `scripts/update.sh`-Ablauf mit seinen zwei Modi — nur Images frischen
  (`./scripts/update.sh`) gegenüber einem Versions-Upgrade mit `--ref` (das die Compose +
  Ops-Skripte für die Zielversion mitzieht) — samt `.env`-Image-Pinning und der
  Selbst-Update-Falle (`update.sh` überschreibt sich nicht selbst).

## [0.30.0] - 2026-06-12

### Added

- **Ein-Befehl-Installer (`curl … install.sh | bash`).** `scripts/install.sh` kennt jetzt einen
  Bootstrap-Modus: per `curl | bash` ohne lokalen Checkout lädt es nur die **Laufzeit-Dateien**
  (die `docker-compose.yml` + ein paar Ops-Skripte, **nicht** den Quellbaum) für einen gepinnten
  Ref herunter und macht dann das Setup. Da mTLS per Default erzwungen ist, gibt es keinen
  Scharfschalt- oder permissiven Schritt — Erst-Admin + Token entstehen über die Container-CLI.
  README + Installations-Doku (DE+EN) führen mit dem Einzeiler.

### Changed

- **`docker-compose.yml` ist jetzt selbstgenügsam** — keine Repo-Datei-Bind-Mounts mehr. Die
  Monitoring-DB (`adminhelper_monitor`) legt der Monitoring-Service in seinem Entrypoint selbst an
  (statt eines gemounteten `postgres-init.sh`). Damit ist die Compose eine **einzelne, eigenständig
  verteilbare Datei** (Images aus ghcr); ein Operator braucht den Quellbaum nicht mehr zum Betrieb.
- **`scripts/update.sh`** kann mit `--ref` die Laufzeit-Dateien (Compose + Skripte) für eine
  Zielversion frischen, bevor es Images zieht + neu startet (Backup-first bleibt).

### Fixed

- **Einzeiler-Robustheit (`curl … | bash`).** `install.sh` zieht die Images jetzt explizit
  (`docker compose pull`), bevor es startet — ein veraltetes lokal gecachtes `:latest` würde sonst
  stillschweigend weiterlaufen. Zusätzlich bekommt jeder `docker compose`-Aufruf `</dev/null`: unter
  `curl | bash` liest bash das Script aus der Pipe, und ein Subprozess, der dieselbe stdin erbt,
  verschluckte sonst den Rest des Scripts (der Stack kam hoch, aber ohne Erst-Admin).

## [0.29.0] - 2026-06-12

### Added

- **One-Shot-Installer `scripts/install.sh`.** Bringt den Stack hoch, legt den Erst-Admin samt
  einmaligem Enrollment-Token **out-of-band** an (über eine neue interne Management-CLI
  `python -m app.cli` mit `create-admin` + `mint-enroll-token`) und schaltet am Ende mTLS scharf.
  Das löst die Henne-Ei-Lage des Erst-Admins unter erzwungenem mTLS: ein brandneuer certloser
  Client kommt nicht durch den `:443`-Handshake zum Login, also mintet das Script (mit internem
  Netz-Zugriff) das erste Token direkt. Der Admin löst es im Desktop unter „Mit Token enrollen" ein
  (Cert entsteht on-device), dann normaler Login.
- **Update-Script `scripts/update.sh`** — Backup-first (inkl. CA-Kronjuwel) → gepinnter
  `docker compose pull` → Recreate → Healthcheck. Version pinnen über die `*_IMAGE`-Tags in `.env`.

### Changed

- **mTLS ist jetzt per Default erzwungen** (`MTLS_ENFORCE=true` in `docker-compose.yml` +
  `.env.example`). **BREAKING:** die Datenebene `:443` verlangt ab Werk ein Client-Cert. Ein
  frischer Install ist via `install.sh` sofort enforced nutzbar; ein manueller Bootstrap ohne Script
  braucht einmalig `MTLS_ENFORCE=false`. Die Token-Mint-Logik wurde in
  `enrollment/service.mint_enrollment_token` extrahiert (von HTTP-API + CLI geteilt).

## [0.28.0] - 2026-06-12

### Added

- **Internes TLS/mTLS-Gateway (`apps/gateway/`, nginx) als einzige öffentliche TLS-Kante**
  auf `:443` (Web/API) und `:8444` (Enrollment, certless + token-gated). Es terminiert TLS und
  reicht die verifizierte Client-Identität als `X-Client-*`-Header an die internen Dienste weiter
  (in dieser Phase **permissiv** — `ssl_verify_client optional`; die mTLS-Pflicht folgt später).
  Ein externer Reverse-Proxy ist nicht mehr nötig (ADR 0001 D11).
- **`ca-issuer`-Dienst in die Produktiv-Compose verdrahtet** (+ ghcr-Publish). Er erzeugt beim
  ersten Start die interne PKI (Root + `tunnel`/`access`/`internal`-Intermediates) und stellt dem
  Gateway dabei dessen TLS-Leaf bereit — **access-signiert**, kettet zur gepinnten Root, sodass
  native Clients es akzeptieren (das Gateway hält keinen Signier-Schlüssel, ADR 0001 D6). Neue
  Volumes `ca-pki` (issuer-privat) und `gateway-certs`.
- **`CA_ROOT_PASSPHRASE`** in `.env.example` + `scripts/init-secrets.sh` — verschlüsselt den
  kalten PKI-Root-Key at-rest (ADR 0001 D7); **getrennt sichern, nicht ins Backup legen**.
- **Full-Stack-Backup/Restore inkl. CA-Kronjuwel** (`scripts/backup.sh` / `scripts/restore.sh`,
  ADR 0001 §5). `backup.sh` bündelt `ca-pki` (Root + Intermediates), `pg_dump` beider DBs,
  `monitoring-data`, optional `victoria-data` und die `.env` **ohne `CA_ROOT_PASSPHRASE`** in ein
  Tarball; `restore.sh` stellt Volumes + DBs wieder her. Die restaurierte Root ist identisch —
  bereits enrollte Clients bleiben vertraut. `gateway-certs`/`frps-certs` werden nicht gesichert
  (der `ca-issuer` regeneriert sie aus `ca-pki`).
- **Server: Per-Route-mTLS-Scope-Schicht** (`app/core/identity.py`, ADR 0001 D8) — der Server
  liest die vom Gateway weitergereichte, verifizierte Client-Identität und prüft pro Route den
  Cert-Scope (`access` = Mensch, `tunnel` = Agent). **In dieser Phase permissiv** (`MTLS_ENFORCE`
  default `false`): ein Mismatch wird nur geloggt, der Request läuft durch — das System bleibt
  nutzbar, bis alle Clients Certs haben. Das Scharfschalten auf `CERT_REQUIRED` folgt später.
- **Desktop: automatisches mTLS-Enrollment (A5a).** Nach dem Login mintet der Desktop ein
  access-scoped Enrollment-Token (`POST /api/enrollment/token`, JWT-gated), erzeugt on-device
  einen ECDSA-Key + CSR (`rcgen`), holt sein Client-Zertifikat vom `ca-issuer` über die
  Enroll-Plane des Gateways und legt Key/Cert/CA in drei Keyring-Einträgen ab. Danach präsentiert
  `build_client` das Cert per mTLS und verifiziert den Server gegen die **gepinnte CA-Kette**
  (CA-Pinning statt Leaf-TOFU — überlebt Gateway-Leaf-Rotation, D2; Hostname bewusst nicht
  erzwungen, damit Enrollment keinen funktionierenden Zugriff bricht). Logout räumt die Identität.
  **Auto-Renew (A5b):** beim App-Start erneuert der Desktop sein Cert automatisch, sobald es ~50 %
  seiner Laufzeit erreicht (über `/ca/renew` mit dem aktuellen Cert als Nachweis).
  **Browser-P12-Export (A5c):** der Desktop kann ein langlebiges Browser-Zertifikat enrollen und
  als passwortgeschützte **PKCS12-Datei** exportieren (zum Import in den Browser-Zertifikatsspeicher).
- **Agent: automatisches mTLS-Enrollment + Auto-Renew.** Beim Provisioning erzeugt der Agent
  on-device einen ECDSA-Key, holt über die Enroll-Plane des Gateways (Port `8444`) ein
  `tunnel`-scoped Client-Zertifikat vom `ca-issuer`, legt es unter `/etc/adminhelper/identity/`
  (Key `0600`) ab und pinnt die interne Root-CA. Danach weist er sich bei allen Server-Pushes
  (Monitor-Report, FRPC-Sync) mit diesem Cert aus (custom-root-only, ADR 0001 D2) und erneuert es
  automatisch bei ~50&nbsp;% Laufzeit via `/ca/renew`. **Best-effort:** ohne erfolgreiches
  Enrollment läuft der Agent vorerst mit dem API-Key weiter. `provision/activate` liefert dafür
  einen einmaligen Enrollment-Token mit.
- **Desktop: Browser-Zertifikat-Export im UI (A6).** Die Einstellungen (Server-Modus, angemeldet)
  haben jetzt einen Knopf **„Browser-Zertifikat exportieren"**: Der Desktop enrollt ein langlebiges
  `access`-Zertifikat, verpackt es als passwortgeschützte `.p12` (auf `0600` gehärtet, im
  App-Datenverzeichnis) und zeigt den Speicherpfad an. Damit lässt sich ein Browser für den späteren
  mTLS-Zwang vorbereiten — Import-Anleitung (Chrome/Edge + Firefox) DE+EN unter „Benutzer &amp;
  Zugriff → Browser-Zugriff". Das Backend-Command bestand seit dem Desktop-Enrollment, war aber nie
  ins UI verdrahtet; die Datei schreibt — mangels FS-/Dialog-Plugin — der Rust-Layer.
- **mTLS-Enforcement-Schalter `MTLS_ENFORCE` (A8).** Eine einzige Variable schaltet die Datenebene
  von permissiv auf erzwungen: das Gateway generiert beim Start sein `ssl_verify_client`-Snippet
  (`optional` per Default, `on` = `CERT_REQUIRED` bei `MTLS_ENFORCE=true`), der Server (seit A3)
  weist geschützte Routen ohne gültigen Cert-Scope mit `403` ab. In `docker-compose.yml` an Gateway
  **und** Server verdrahtet, `.env.example` dokumentiert. **Default `false`** (permissiv) — nichts
  ändert sich, bis ein Operator umlegt; Rollback ist ein Flag zurück + Gateway-Neustart. Beide
  nginx-Modi mit `nginx -t` **und end-to-end am laufenden Stack** verifiziert (permissiv → certlos
  `GET /` = 200; enforced → certlos = 400 „No required SSL certificate" am Handshake, Enroll-Plane
  `:8444` weiter offen; Rollback → 200). Betriebs-Anleitung (Scharfschalten, Rollback,
  Lock-out-Vermeidung, Bootstrap-Fenster) unter „Betrieb &amp; Konfiguration" (DE+EN). Das
  tatsächliche Scharfschalten bleibt eine bewusste Operator-Aktion nach GUI-Hardware-Verifikation.
- **Admin-Enrollment-Token für fremde Identitäten** (`POST /api/enrollment/token/for`, admin-only).
  Ein Admin mintet ein einmaliges `access`-Enrollment-Token für einen existierenden Ziel-User und
  reicht es out-of-band weiter; der neue Nutzer löst es certless an der Enroll-Plane `:8444` ein.
  Erster Baustein der **entkoppelten Enrollment-Tür** (ADR 0003), damit neue Clients auch bei
  erzwungenem mTLS ohne permissives Fenster onboarden können (CN = Ziel-Username, issuer-diktiert).
- **Desktop: „Mit Token enrollen"-Erst-Start-Flow** (ADR 0003, entkoppelte Enrollment-Tür). Der
  Login-Screen hat jetzt einen Umschalter „Erstes Mal? Gerät mit Token einrichten": mit Server-URL +
  einem (vom Admin out-of-band erhaltenen) Enrollment-Token holt der Client sein mTLS-Zertifikat
  **ohne vorigen Login** an der certless Enroll-Plane `:8444` und meldet sich danach normal an. Damit
  lässt sich ein neuer Nutzer auch bei erzwungenem mTLS onboarden, ohne die Datenebene kurzzeitig
  permissiv zu schalten (das bleibt nur für den allerersten Admin nötig).
- **Sofortiger Identitäts-Widerruf (Schnell-Widerruf ohne CRL, ADR 0001 §3.4).** Das Löschen eines
  Benutzers bzw. Servers schreibt jetzt einen `revoked_identities`-Eintrag: der `ca-issuer`
  verweigert dem Cert die Erneuerung (`/renew`) **und** die Datenebene weist es im erzwungenen Modus
  pro Request mit `403` ab (vorher wurde die Liste nie befüllt — der Widerruf war wirkungslos). Das
  Neuanlegen eines gleichnamigen Benutzers räumt einen veralteten Eintrag.
- **Cleanup-Job für `enrollment_tokens`.** Verbrauchte/abgelaufene Enrollment-Token werden periodisch
  gelöscht (analog zur JWT-Blacklist), statt die Tabelle unbegrenzt wachsen zu lassen.
- **Rate-Limit auf der certless Enroll-Plane `:8444`** (`limit_req`, per-IP, 10 r/s, Status 429) gegen
  Token-Brute-Force/Enroll-Flooding (das in ADR 0003 §5 versprochene Limit war nie konfiguriert).

### Changed

- **FRP-Tunnel auf die einheitliche PKI umgestellt** (ADR 0001 D1, Provider-Seite). Das
  frps-Server-Cert und das Agent-Tunnel-Cert kommen jetzt aus der `tunnel`-Intermediate des
  `ca-issuer` (ECDSA P-256) statt aus einer frps-eigenen RSA-CA: der Issuer provisioniert
  `frps.crt`/`frps.key`/`ca.crt` (tunnel-Kette) in ein neues `frps-certs`-Volume, das frps
  read-only unter `/etc/frp-pki` mountet; der Agent nutzt für den frp-Tunnel **dasselbe**
  enrollte Tunnel-Cert wie für seine Server-Pushes. `trustedCaFile` ist beidseitig die
  tunnel-Kette; der Server mintet kein per-Client-frp-Zertifikat mehr. Der **Desktop-Visitor**
  ist inzwischen ebenfalls migriert (siehe „Changed → STCP-Visitor"/„Removed → FRP-CA").
- **Der Server terminiert kein TLS mehr selbst.** Er lauscht plain-HTTP intern auf `:8080` hinter
  dem Gateway und hat **keinen Host-Port** mehr; `server` und `ca-issuer` sind nur noch im
  Compose-Netz erreichbar. Dadurch ist der vom Gateway gesetzte Identitäts-Header von außen
  unfälschbar. Die frühere Self-Signed-Zertifikat-Erzeugung im Server-Entrypoint entfällt
  (das TLS-Zertifikat kommt jetzt vom `ca-issuer`). **frps** bleibt seine eigene TLS-Kante.
- **STCP-Visitor (Desktop) auf die einheitliche PKI migriert.** Der Visitor präsentiert jetzt seine
  **enrollte access-Identität** als frpc-Client-Cert (der Desktop exportiert Key/Cert/CA aus dem
  Keyring in Dateien für den frpc-Sidecar) statt eines server-gemünzten Certs der alten FRP-CA. frps
  vertraut dafür zusätzlich der `access`-Intermediate (der `ca-issuer` trägt sie in frps' `ca.crt`
  ein); die echte Per-Tunnel-Autorisierung bleibt der STCP-`secretKey` + die server-seitige
  Bundle-Filterung. **Real-Roundtrip nur manuell verifizierbar** (kein CI-Schutz).
- **Renew schreibt die Identität crash-sicher** (Agent: Staging + atomarer Rename; Desktop:
  Schlüssel-Wiederverwendung). Ein Absturz mitten im Renew kann keine unbrauchbare Key/Cert-Paarung
  mehr hinterlassen (vorher: stiller Lock-out bis zur Neu-Provisionierung).
- **Gateway-/frps-Leaf wird vor Ablauf erneuert.** Der `ca-issuer` mintet ein bereitgestelltes
  Server-Leaf beim Boot neu, sobald es die Hälfte seiner Laufzeit überschritten hat — ein
  langlaufender Stack verliert `:443`/`:8444` (bzw. frps) nicht mehr durch ein abgelaufenes Cert.

### Removed

- **Browser-Erweiterung (`apps/extension/`) vollständig entfernt.** Die Chrome/Edge-MV3-Extension,
  die gespeicherte Web-Verbindungen als Popup anzeigte, wurde mitsamt Code, CI-Job (`ci.yml`),
  Release-Artefakt (`adminhelper-extension-*.zip` in `release.yml`) und Dokumentation (Admin-/
  Developer-Kapitel, README, `DEVELOPMENT.md`) aus dem Projekt gelöscht. Sie nutzte ausschließlich
  den **geteilten** `GET /api/connections`-Endpunkt mit einem `X-API-Key`-Header — es gab keine
  extension-exklusive Server-Schnittstelle, daher entfällt serverseitig nichts außer einigen
  Kommentar-Verweisen. Menschliche Browser-Nutzung läuft über das vom Desktop exportierte
  PKCS12-Client-Zertifikat (mTLS, A5c). Im PKI/mTLS-Plan (ADR 0001/0002) entfällt damit der
  Extension-Teil von A6.
- **Alte server-eigene FRP-CA vollständig entfernt** (D6 wirklich erfüllt — keine zweite
  Signier-Capability mehr im exponierten Server). Gelöscht: `app/modules/frp/pki.py` +
  `pki_router.py` (die `POST /api/frp/pki/ca|server-cert|client-cert`-Endpunkte), die
  CA-Erzeugung im Server-Start, das `frp-pki`-Volume sowie die **FRP-PKI-Admin-UI** im
  Web-Frontend (Modal, „CA generieren"-Knopf, API-Client, i18n-Strings). Die FRP-TLS-Materialien
  kommen seit der Provider-Migration ausschließlich aus dem `ca-issuer`.

## [0.27.0] - 2026-06-10

### Security

- **Server: Server-Name in die TOML-/Pfad-Boundary aufgenommen** (Audit-Residuum).
  `ServerCreate`/`ServerUpdate.name` lehnt jetzt TOML-Breaker und Pfad-Zeichen
  (`/`, `.`, `..`) ab — der Name fließt als FRP-Identifier (`user`/`serverUser`)
  in generierte Agent-Configs und als Pfad-Komponente ins Bulk-ZIP
  (`clients/{name}/frpc.toml`), war aber als einzige Eingangstür unvalidiert.
- **Server/FRP: `extra_config` lehnt Nicht-Skalar-Werte ab** (Audit-Residuum).
  Listen/Dicts umgingen den String-Breaker-Check und landeten als rohes
  Python-`repr` in der TOML (Injection über innere Strings möglich); Keys
  müssen jetzt TOML-Bare-Keys sein, Werte `str`/`bool`/`int`/`float`.
- **Server: Per-User-Isolation auf `/api/connections` durchgesetzt** (Audit-Fund).
  Non-Admins (und server-gebundene API-Keys) sehen und „touchen" nur noch
  Connections ihrer zugewiesenen Server — vorher lieferte die Liste **jedem**
  Non-Admin Host, Username und FRP-Visitor-Ports **aller** Server (IDOR). Spiegelt
  die bereits bestehende FRP-Visitor-Scoping-Invariante (`frp/generate_router.py`).
- **Server: Der letzte Admin kann nicht mehr per `update_user` herabgestuft
  werden** — verhindert den irreversiblen Self-Lockout aller admin-only-Endpunkte.
- **Server: Webhook-Ausführung blockiert nicht mehr den Event-Loop** (Audit-Fund).
  `run_hook_script` läuft jetzt über `run_in_threadpool` — ein einzelner langsamer
  Hook fror vorher das komplette Single-Worker-Backend (Login/APIs/Health) bis zum
  Timeout ein. Zusätzlich: eine Semaphore begrenzt gleichzeitige Hook-Subprozesse,
  und das Webhook-Trigger-Rate-Limit nutzt jetzt das zentrale `rate_limit`-Backend
  (mit Eviction/TTL) statt eines unbegrenzt wachsenden Per-IP-Dicts (Memory-DoS bei
  gefälschten `X-Forwarded-For`).
- **Server: Refresh-Token-Reuse invalidiert jetzt die ganze Token-Familie** (Audit).
  Bei erkanntem Reuse (Theft-Signal) wird `tokens_valid_after` des Users gesetzt —
  damit stirbt auch die bereits rotierte Angreifer-Kette, nicht nur das einzelne
  Token (vorher blieb sie unbegrenzt gültig).
- **Server: Rate-Limit fällt bei Redis-Ausfall nicht mehr „offen"** (Audit). Statt
  bei Redis-Fehlern still `0` zu liefern (Brute-Force-Schutz aus), **degradiert**
  das Backend auf einen lokalen In-Memory-Zähler — das Limit bleibt durchgesetzt.
- **Server/FRP: TOML-Injection an der Boundary geschlossen** (Audit). Felder, die
  roh in `frps.toml`/`frpc.toml`/Visitor-Config interpoliert werden (Tunnel-/
  Server-Name, `secret_key`, `auth_token`, `custom_domains`, `extra_config` …),
  lehnen jetzt Anführungszeichen/Backslash/Steuerzeichen ab; `secret_key`/
  `auth_token` haben einen Entropie-Floor (≥16 Zeichen). `get_allow_users` fällt
  zudem **fail-closed** (leere Allow-Liste statt `["*"]`).
- **Monitoring: MetricsQL-Label-Injection geschlossen** (Audit). `server_id`/
  `check_id` werden vor der Interpolation in Label-Matcher escaped — ein
  präparierter Wert kann nicht mehr aus dem Matcher ausbrechen und fremde
  Server-Metriken lesen.
- **Server: Agent-Report-Ingest (`/api/monitoring/agent/{id}/report`) ist
  rate-limitiert** (Audit) — der öffentliche, JWT-freie Proxy-Endpunkt cappt jetzt
  pro IP, statt eine unauthentifizierte Flut ungebremst durchzureichen.
- **Agent: Argument-Injection in watched-services geschlossen** (Audit). `--`
  vor dem server-gelieferten Service-Namen verhindert Flag-Confusion in den
  `systemctl`-Aufrufen (kein RCE — exec ohne Shell — aber Flag-Verwechslung).
- **Extension: API-Key wandert von `chrome.storage.sync` nach `chrome.storage.local`**
  (Audit). Der langlebige Key wird nicht mehr über den Browser-Account auf alle
  Geräte synchronisiert; eine einmalige Migration verschiebt bestehende Keys und
  löscht die Cloud-Kopie.
- **Desktop: TLS-Bypass durch TOFU-Zertifikat-Pinning ersetzt** (Audit-Fund,
  der einzige bestätigte MITM-Credential-Theft-Pfad). „Selbstsignierte
  Zertifikate erlauben" schaltete vorher via `danger_accept_invalid_certs(true)`
  die **komplette** TLS-Prüfung ab (Chain **und** Hostname, ohne Pinning) — ein
  On-Path-Angreifer konnte Login-Passwort, JWT-Access/Refresh-Token sowie den
  FRP-Client-Private-Key + `auth.token` aus dem Visitor-Bundle abgreifen. Jetzt
  pinnt der zentrale `auth::build_client` (und damit alle Pfade: Login, Refresh,
  `api_proxy`, Tunnel-, Connection- und Sync-Abrufe) beim ersten Verbinden den
  SHA-256-Fingerprint des Server-Leaf-Zertifikats (SSH-`known_hosts`-Modell,
  custom rustls `ServerCertVerifier`) und akzeptiert danach **nur** noch genau
  dieses Zertifikat; ein Wechsel wird abgelehnt (mögliche MITM). Der Pin liegt
  im OS-Keyring; neue Einstellung **„Gepinntes Zertifikat zurücksetzen"** stellt
  nach legitimer Cert-Rotation den First-Use wieder her. `check_server_cert`
  prüft zusätzlich das URL-Schema (kein Cleartext-Probe). Verifiziert per
  Echt-Handshake-Test (tokio-rustls-Server, Cert-Wechsel → reject).
- **Desktop: drei Defense-in-Depth-Härtungen rund um den gepinnten TLS-Pfad**
  (Audit, Rest des Desktop-Bündels — schließt #6 vollständig). (1) **Token-
  Destination-Pin**: `api_proxy` sendet den Session-JWT nur noch an die
  angemeldete Server-URL (`auth::stored_server_url`), ein abweichendes Ziel wird
  abgelehnt — ein kompromittiertes Frontend kann den Token nicht mehr an einen
  Fremd-Host umleiten. (2) **`ansible`-Pfad-Confinement**: `launch_ansible`
  akzeptiert nur noch Pfade unter dem App-Temp-Verzeichnis mit Präfix
  `adminhelper_ansible` (canonicalisiert, blockt `..`/Symlink-Ausbruch) — ein
  manipuliertes Frontend kann `ansible-playbook` nicht mehr auf ein fremdes YAML
  zeigen (RCE-Schutz). (3) **CSP**: `connect-src` von `'self' https:` auf
  `'self' ipc: http://ipc.localhost` verengt — schließt den XSS-Exfiltrations-
  Kanal; sämtlicher Server-Verkehr läuft ohnehin über den Rust-`api_proxy`, nie
  über Webview-`fetch`. (CSP-Änderung auf Windows manuell zu verifizieren.)
- **Web: Refresh-Token von `localStorage` in ein `HttpOnly`-Cookie verlagert**
  (Audit). Der langlebige Refresh-Token ist damit für JavaScript — und somit für
  XSS — unlesbar. Der Server setzt ihn auf `/login`, `/refresh` und `/bootstrap`
  als `HttpOnly; Secure; SameSite=Strict`-Cookie (Pfad `/api/auth`); `/refresh`
  und `/logout` lesen ihn aus Cookie **oder** Body, sodass Desktop- und CLI-
  Clients unverändert weiterlaufen (`Secure` folgt dem Request-Schema, damit
  localhost-Dev und Tests funktionieren). `SameSite=Strict` auf dem einzigen
  Cookie-lesenden Endpunkt ist der CSRF-Schutz — ein separates CSRF-Token wäre
  hier Over-Engineering. Der Web-Client hält den Refresh-Token nicht mehr und
  räumt Altbestände aus `localStorage`. Verifiziert per pytest (Cookie-Setzen/
  Rotation/Reuse-Detection/Logout-Clear + Body-Backward-Compat) und Playwright-E2E.
- **Server/Monitoring: gehashte Python-Lockfiles** (Audit, Supply-Chain). Die
  Production-Images installieren ihre Dependencies jetzt aus einer gepinnten +
  SHA-256-gehashten `requirements.txt` (generiert via `pip-compile
  --generate-hashes`) mit `pip install --require-hashes` — ein manipuliertes oder
  getauschtes Artefakt vom Index lässt den Build fehlschlagen. `requirements.in`
  ist die lose Intent-Quelle; Tests/CI nutzen sie (ungehasht). Verifiziert per
  realem Docker-Build (`--require-hashes`, exit 0) für beide Dienste.
- **`SECURITY.md`: Trust-Modell + Audit-Residuen dokumentiert** — FRP-`secretKey`
  als eigentliche Authz-Grenze (nicht `allowUsers`), globaler `auth.token` als
  akzeptiertes SPOF mit Rotations-Empfehlung, Single-Worker-Verfügbarkeitsprofil,
  und das Register der bewusst zurückgestellten/akzeptierten Funde
  (frps-Caps, Pagination, Watermark-Subsekunden …) mit Begründung + Plan.

### Changed

- **Agent: Service-Inventar wird nur noch bei Änderung gesendet** (Audit R8,
  Ziel 250–500 Agenten). `all_services` (100–300 weitgehend statische
  systemd-Units) geht nur noch mit, wenn sich der SHA-256-Hash des Inventars
  ändert oder der letzte Full-Send >1 h her ist (State-Datei
  `.inventory-state.json` neben `monitor.conf`, oneshot-fest; Fehler ⇒
  Full-Send, nie Push-Abbruch). Watched-Services und Legacy-Fallback-Keys
  gehen weiterhin bei jedem Push; serverseitig ist „Key fehlt ≠ leeres
  Inventar" jetzt dokumentiert und durch Tests festgenagelt. Windows
  meldet gestoppte Dienste nicht mehr fälschlich als `enabled_inactive`.
- **Agent-Pakete installieren nach `/usr/bin`** (vorher `/usr/local/bin` —
  FHS-untypisch für Paketmanager-Inhalte, `rpmlint`-Fehler). deb und rpm
  teilen sich die Unit-Datei, daher beide umgestellt; dpkg/rpm räumen den
  alten Pfad beim Upgrade ab. Build-Skripte brechen außerdem ab statt still
  ein Dummy-`frpc` zu packen oder eine geratene Default-Version zu bauen;
  rpm deklariert jetzt `Conflicts:` für die alten `srm-*`-Pakete; die
  Install-Hinweise nennen `provision` statt des entfernten `frpc init`.
- **Dependabot entfernt** (`.github/dependabot.yml`) — Dependency-Updates laufen
  künftig agent-getrieben (verträgt sich besser mit den gehashten Python-Locks und
  erlaubt koordinierte, getestete Bumps über alle Ökosysteme). GitHubs separate
  Security-Alerts bleiben als Sicherheitsnetz unberührt. Neuer Workflow in
  `DEVELOPMENT.md` dokumentiert.
- **Web: Monitoring-Seite zerlegt** (Audit F8). `Monitoring.svelte` schrumpft
  von 743 auf 153 Zeilen: Filter-/Gruppierungs-/Summen-Logik lebt jetzt
  testbar in `lib/utils/monitoring.ts`, die Tab-Inhalte in fünf
  Subkomponenten unter `lib/components/monitoring/` (Muster der
  Desktop-Sektionen). Verhalten und Optik unverändert (Screenshot-Tests
  grün); Polling/„zuletzt aktualisiert" bleiben auf Seitenebene.
- **Server: FK-Spalten indiziert** (Audit, Ziel 250–500 Server). Neue Migration
  `a258973bb7fd` legt Indizes auf `connections.server_id`,
  `frp_tunnels.server_id`/`frp_config_id`/`connection_id` und
  `provision_tokens.server_id` an — Postgres indiziert FK-Spalten nicht
  automatisch; Server-Deletes (CASCADE/SET NULL) und server-bezogene Filter
  liefen vorher als Full-Table-Scans.

### Fixed

- **Server: Webhook-Trigger blockiert den Event-Loop nicht mehr** (Audit-Rest).
  Der Redis-Rate-Limit-Increment und die Hook-DB-Query in `trigger_webhook`
  liefen als einzige sync-I/O-Reste direkt im Event-Loop des async-Handlers —
  jetzt via `run_in_threadpool`, konsistent zum bereits ausgelagerten
  Hook-Subprozess.
- **Agent: `service install` erzeugt jetzt dieselbe Unit-Semantik wie deb/rpm**
  (Audit). Die generierte systemd-Unit nutzte `run` (Dauerläufer) unter
  `Type=oneshot` + Timer — `systemctl start` hing bis zum Timeout und der Timer
  feuerte eine zweite, parallele Instanz (doppelte Pushes). Jetzt `run --once`
  + Timer wie im Paket, inkl. `RandomizedDelaySec`.
- **Agent: Metrik-Push mit 1 Retry (10 s Backoff)** — ein transienter
  Server-Neustart reißt kein 5-Minuten-Loch mehr in die Zeitreihen.
- **Agent: Docker-Collection mit Timeout + Batch-Inspect** — `docker info`/
  `ps`/`inspect` laufen mit 10-s-Timeout (hängender Daemon blockierte vorher
  den ganzen Push-Cycle unbegrenzt); Restart-Policies kommen aus EINEM
  Batch-`docker inspect` statt einem Subprozess pro Container.
- **Agent: TLS-HTTP-Client dedupliziert** (`internal/httpclient`) — die
  dreifach kopierte CA-Pinning-Logik (monitor/frpc/provision) hat jetzt eine
  Quelle; Timeout ist der einzige Parameter.
- **Web/Desktop: `types.ts`-Drift aufgelöst, Dictionaries entkoppelt** (Audit,
  Kritisch-Fund). Das Web übernimmt die Desktop-Typnamen (`FrpProvisionToken`,
  `FrpProvisionTokenCreateResult`, + `MonitoringAgentKeyResult`) — beide
  `lib/api/types.ts` sind wieder byte-identisch. `sync-from-web.sh`
  synchronisiert nur noch `types.ts` (die i18n-Dictionaries sind bewusst
  getrennte Produkte, ein `--apply` hätte ~200 Desktop-Keys still gelöscht)
  und bricht ab, wenn das Ziel Exporte enthält, die in der Quelle fehlen.
- **Desktop: TOFU-Pin-Cache übersteht Thread-Panics** — alle vier
  `.lock().unwrap()`-Stellen auf dem Pin-Cache-Mutex nutzen jetzt das
  Poison-tolerante Muster aus `frpc.rs`; vorher hätte ein einzelner Panic
  jede weitere TLS-Verifikation mitgerissen.
- **Desktop: `api_proxy` meldet kaputtes Antwort-JSON als Fehler** statt es
  still auf `null` zu mappen (leerer 2xx-Body bleibt zulässig).
- **Desktop: RDP-Fehlertoast bei extrem schnellen Verbindungen** —
  „verbunden"-Erkennung nutzt jetzt ein eigenes Flag statt des
  `connected_at_ms == 0`-Sentinels (Doppeldeutung bei <1 ms).
- **Produkt-Doku (DE+EN) auf den Code-Stand gebracht** (Audit X3/X5): alle
  Prä-v0.24-Pfade ohne `apps/`-Präfix korrigiert, Agent-Pfade
  (`/usr/bin`, `adminhelper.conf`, `%ProgramData%\AdminHelper`),
  HttpOnly-Cookie-Realität in der API-Referenz; neu dokumentiert:
  Pagination, Push-Retry/Inventar-Drosselung, Web-Auto-Refresh,
  Scheduler-Defaults, Alert-Log-Retention, alle neuen CI-Gates.
  CLAUDE.md-Testspalte korrigiert (alle Komponenten haben Tests; der
  `version_locations`-Verweis ist als lokale, gitignorte Agent-Memory
  gekennzeichnet).
- **Doku-Drift behoben** (Audit X1/X2/X6): README-Quick-Start zeigte auf das
  nicht existierende `http://localhost:8080` (richtig: `https://localhost`,
  Compose published nur 443); DEVELOPMENT.md beschrieb den entfernten
  `admin/admin`-Login, verlangte Go 1.24 (go.mod: 1.25), verschwieg die
  Node.js-Voraussetzung und zeigte ein Override-Beispiel mit totem
  Build-Context; CONTRIBUTING verlangte ein nicht existierendes
  `npm run test` fürs Web.
- **Monitoring: Connection-Leak im Alerter geschlossen** (Audit). Die
  Zweit-Session in `_build_message` wurde nur im Happy-Path geschlossen —
  bei Fehlern blieb die Pool-Verbindung hängen; jetzt Context-Manager.
- **Monitoring/Server: APScheduler-Defaults explizit gesetzt** (Audit, Ziel
  250–500 Server). `misfire_grace_time=30` statt 1 s (verspätete Runs wurden
  still verworfen → Zeitreihen-Lücken), Monitoring-Pool auf 30 Worker für
  I/O-gebundene Checks; `coalesce`/`max_instances` als Entscheidung gepinnt.
- **Monitoring: Push- und Scheduler-Checks nutzen dieselbe Damping-Logik**
  (Audit Q1). Der Agent-Report-Pfad hatte die `consecutive_fails`-Transition
  inline reimplementiert (ungetestete Kopie der getesteten
  `check_engine`-Funktionen, Drift-Gefahr) — jetzt eine Quelle; unterdrückte
  Meldungen tragen auch im Push-Pfad das „(Fehler n/m)"-Suffix.
- **Desktop-UI: Alert-Ladefehler sind sichtbar** (Audit). `loadAlerts`/
  `loadAlertLog` schluckten API-Fehler still — ein toter Monitoring-Service
  sah aus wie „keine Alerts". Jetzt `reportError` wie in `loadMonitoring`
  (Session-Expiry weiterhin ausgenommen).
### Added

- **CI schließt die „grün-aber-kaputt"-Blindspots** (Audit C1–C3): neuer
  Windows-`cargo check`-Job (der `windows`-Crate-Code wurde nie in CI
  kompiliert), ein `cargo tauri build`-Smoke auf Linux (beforeBuildCommand/
  UI-Embedding/deb-Bundling liefen nur auf Tags) und Docker-Builds beider
  Images auf PRs (`push: false`). Dazu ein FRP-Pin-Konsistenz-Check über
  die drei `FRP_VERSION`-Stellen.
- **Wöchentlicher Dependency-Audit-Workflow** (`audit.yml`, Audit D2):
  pip-audit (beide gehashten Locks), cargo audit, govulncheck, npm audit —
  das automatische CVE-Signal zwischen den agent-getriebenen Update-Runden.
- **Coverage-Reporting in CI** (Audit C4, report-only): pytest-cov für
  Server/Monitoring, `go test -cover`, vitest `--coverage` in beiden UIs.
- **ruff für die Python-Komponenten** (Audit C8). Server und Monitoring waren
  als einzige Komponenten ohne Lint-/Format-Gate — jetzt `ruff check`
  (+ Import-Sortierung) und `ruff format` mit CI-Job; einmaliger
  Format-Lauf über den Bestand (96 Auto-Fixes + 77 reformatierte Dateien,
  rein mechanisch, Suiten grün).
- **Release: Extension als versioniertes Zip-Artefakt** (Audit C5) — bisher
  wurde die MV3-Extension getestet, aber nie ausgeliefert („Load unpacked"
  aus dem Clone); jetzt hängt sie als `adminhelper-extension-X.Y.Z.zip` am
  Draft-Release und ist Teil des Release-Gates. `tauri-cli` ist im
  Release-Build exakt gepinnt statt floatendem `^2`.
- **API: optionale Pagination auf den Listen-Endpunkten** (Audit P4, Ziel
  250–500 Server). `limit`/`offset`-Query-Parameter (1–1000) +
  `X-Total-Count`-Header auf `GET /api/servers`, `/api/connections`,
  `/api/hooks` sowie Monitoring-Checks/-Status/-Alert-Regeln — ohne
  Parameter unverändertes Verhalten (volle Liste), Frontends unberührt.
  Pagination läuft in SQL nach dem Per-User-Scoping; der Monitoring-Proxy
  reicht `X-Total-Count` jetzt durch (Whitelist). 21 neue Tests.
- **Web: Monitoring aktualisiert sich automatisch** (Entscheidung nach Audit).
  30-s-Polling wie im Desktop, aber pausiert bei verstecktem Tab
  (`visibilitychange`; beim Sichtbarwerden sofortiger Refresh) — bei
  250–500 Servern pollen Hintergrund-Tabs damit nicht. Dezente „zuletzt
  aktualisiert"-Anzeige im Seitenkopf; Run-now-Button hat jetzt ein
  `aria-label`.
- **Monitoring: Retention-Cleanup für `monitor_alert_log`** (Audit). Täglicher
  System-Job löscht Einträge älter als 90 Tage — flatternde Checks schrieben
  die Tabelle vorher unbegrenzt voll (analog zum Blacklist-Cleanup des
  Servers). Dazu Tests für Trigger-Parsing, Push-Only-Skip und Cleanup.
- **Migrations-Smoke-Tests für Server und Monitoring** (Audit T1 — größter
  Test-Blindspot). Die Suite lief bisher ausschließlich gegen
  `create_all()`-Schemata; die echte Alembic-Kette wurde nie ausgeführt —
  eine kaputte Migration wäre grün durchgerutscht und erst im Deployment
  aufgefallen. Jetzt: `alembic upgrade head` gegen eine frische DB +
  `compare_metadata`-Abgleich (Server zusätzlich: Reentrance). Der
  Monitoring-CI-Job bekommt dafür einen Postgres-Service; lokal skippt der
  Monitoring-Smoke ohne `DATABASE_URL`.
- **Monitoring: Tests für `template_sync` und den Agent-Report-Pfad** (Audit
  T2 — die komplexeste, bisher ungetestete Monitoring-Logik). Variablen-
  Substitution, Create/Update/Delete-Diffing über mehrere Server, Schutz
  manueller Checks, Assignment-Entfernung, Server-Cleanup; dazu
  Endpoint-Verhaltenstests für das `consecutive_fails`-Damping im Push-Pfad.
  Monitoring-Suite 53 → 72 Tests.
- **Web: E2E-CRUD- und Fehler-Flows** (Audit T2). Stateful-Mocks +
  `crud.spec.ts`: Connection-Roundtrip (anlegen → Liste → löschen),
  Server-Anlage, API-500 → Fehler-Toast-Assertion; dazu 17 Unit-Tests für
  die extrahierte Monitoring-Filter-/Gruppierungslogik. Web-Suite 41 → 59
  Unit-Tests, Playwright 18 → 21 Specs.
- **Frontend: Tests für Token-Refresh und i18n-Parität** (Audit T3/T5).
  `client.ts` (401→Refresh→Retry, Refresh-Fehlschlag→Logout, parallele
  Requests teilen einen Refresh, 204→null) war als sicherheitskritischste
  Web-Logik ungetestet; dazu DE≡EN-Schlüssel-Paritäts-Tests in beiden
  Frontends — die heutige 100-%-Parität ist damit gegen Drift geschützt.
- **Agent: Tests für SMART-Parsing, Report-Aufbau und Push-Retry** —
  smartctl-7.x-JSON-Fixtures (ATA + NVMe + Degenerat-Fälle), `BuildReport`-
  Grundstruktur, Retry-Verhalten gegen httptest-Server, `hasPrefix`/`getFloat`.
- **Desktop: RDP-Fehlerklassifizierung testbar extrahiert**
  (`connection/rdp_logic.rs`) — `parse_freerdp_error` als datengetriebene
  Regel-Tabelle (verhaltensgleich), dazu 25 neue Tests (FreeRDP-Fehlerklassen,
  `parse_custom_size`, `hdpi_scale`, `resolve_connection`-Tunnel-Mapping,
  Windows-Cmdline-Quoting); Rust-Suite 24 → 49 Tests.

### Removed

- **Web: 5 verwaiste UI-Komponenten gelöscht** (`StatusPill`, `Badge`, `Tabs`,
  `Spinner`, `Field` — 0 Importe im gesamten `src`, per grep verifiziert).

## [0.26.0] - 2026-06-07

### Changed

- **FRP von 0.61.1 auf 0.69.1 angehoben** — frps-Image (`docker-compose.yml`),
  gebundeltes frpc (CI/Release) und die SHA-256-Pins der frp-Artefakte im
  Gleichschritt. Das Wire-Protokoll bleibt v1 (Default in 0.69), daher
  abwaerts­kompatibel; v2 ist opt-in (`transport.wireProtocol`) und wird nicht
  gesetzt. **Tunnel-getestet:** frps+frpc 0.69.1 mit der vom `config_generator`
  erzeugten Struktur (STCP-Proxy + `allowUsers`, Visitor mit `serverUser`,
  mutual `transport.tls` gegen eine eigene CA) — `verify` akzeptiert die Config
  und Nutzdaten fliessen durch den Tunnel.

## [0.25.0] - 2026-06-06

### Security

- **Desktop: Path-Traversal (Zip-Slip) beim Schreiben server-gelieferter
  PKI-Dateinamen geschlossen.** Ein boesartiger/kompromittierter Server konnte
  ueber den Visitor-Bundle-Dateinamen (`pki_dir.join(filename)`) beliebige Dateien
  auf dem Client schreiben. Dateinamen werden jetzt als einzelne, separator-freie
  Pfad-Komponente validiert.
- **Desktop: TLS auf der authentifizierten Server-URL erzwungen.** Login/Refresh/
  Logout/`authenticated_get` senden Passwort + Tokens nur noch ueber `https://`
  (Ausnahme: Loopback fuer lokale Entwicklung) — kein Klartext mehr ueber das Netz.
- **Monitoring: VictoriaMetrics-Line-Protocol-Injection geschlossen.** Agent-Report-
  Felder werden numerisch erzwungen, Tags/Measurements escaped (Backslash/Newline/
  Control-Chars) — ein Agent-Key kann keine fremden Zeitreihen mehr faelschen.
- **FRP-PKI: CA-Private-Key + alle Client-Keys aus dem internet-zugewandten
  frps-Volume entfernt.** Master-PKI liegt jetzt server-privat (Volume `frp-pki`);
  ins geteilte `frp-config`-Volume wird nur noch die frps-Teilmenge
  (`ca.crt`/`frps.crt`/`frps.key`) publiziert. Bestandsdeployments werden beim
  Startup einmalig migriert (CA bleibt erhalten).
- **Monitoring: Admin-API nicht mehr direkt zum Host exponiert.** Agent-Metriken
  laufen jetzt tunnelfrei ueber den Server-Proxy (`POST /api/monitoring/agent/
  {id}/report` auf 443); der Monitoring-Dienst ist nur noch intern erreichbar.
  `/docs`+`/openapi.json` sind standardmaessig aus (Env `MONITOR_ENABLE_DOCS`),
  der interne/Agent-Key wird konstant-zeitig (`secrets.compare_digest`,
  fail-closed) verglichen.

- **Server: Passwort-Reset widerruft jetzt bestehende JWTs.** Ein Passwort-Wechsel
  setzt `users.tokens_valid_after`; Tokens mit `iat` davor (oder ohne `iat`) werden
  abgelehnt — vorher blieben Access-(8h)/Refresh-(7d)-Tokens nach einem Reset gueltig.
- **Server: Input-Validierung auf User-Endpunkten.** `UserCreate`/`UserUpdate`
  erzwingen Passwort-Mindestlaenge (8) und einen Username-Charset
  (`^[a-zA-Z0-9._-]+$`, 3–64) — der Username fliesst in FRP-TOML und PKI-Dateinamen.

- **Extension: API-Key nicht mehr im URL-Query-String.** `background.js`/`popup.js`/
  `options.js` senden den Key jetzt über den `X-API-Key`-Header statt `?api_key=`
  (vorher landete der langlebige Key in Access-/Proxy-Logs, Referer, History).
  Zusätzlich: überflüssige `tabs`-Permission entfernt, und Verbindungs-URLs werden
  vor dem Öffnen auf `http(s)` geprüft.
- **Agent: `--insecure` persistiert nicht mehr in die Schleife.** Statt `INSECURE=1`
  dauerhaft zu speichern (TLS-Verify dauerhaft aus + API-Key-Leak pro Zyklus),
  erfasst der Agent beim Provisioning das Server-Zertifikat und pinnt es (TOFU) —
  `--insecure` gilt nur noch für den einmaligen Activate-Aufruf. Zusätzlich:
  Secret-Verzeichnisse `0700` (auch bei Raw-Binary-Provisioning), Config-Writer
  lehnt Steuerzeichen ab (verhindert `INSECURE=1`-Injection via Newline),
  PKI-Bundle-Dateien default `0600` (nur `.crt` auf `0644`).
- **Container laufen nicht mehr als root.** Server- und Monitoring-Image starten
  nur kurz als root (chownt die gemounteten Pfade), droppen dann via `gosu` auf
  einen Non-root-User (uid 10001) — uvicorn, Alembic, Cert-Generierung und
  Hook-Subprozesse laufen unprivilegiert. Begrenzt die Auswirkung einer
  App-RCE/Path-Traversal auf einen Non-root-Prozess.
- **`frps.toml` jetzt `0600`.** Die Datei (globaler `auth.token` +
  Dashboard-Passwort) im mit frps geteilten Volume wurde zuvor world-readable
  (`0664`) geschrieben; jetzt umask-robust `0600` (frps liest sie als root).
- **CI/CD-Supply-Chain gehärtet.** Alle third-party GitHub-Actions sind auf den
  vollen Commit-SHA gepinnt (vorher mutable Tags/Branch-Refs wie
  `rust-toolchain@stable` in Jobs mit ghcr-Push + `contents:write`); der
  `frpc`-Download wird vor Nutzung gegen einen gepinnten SHA-256 verifiziert;
  Dependabot (`github-actions` + pip/npm/gomod/cargo) hält die Pins aktuell.
- **Desktop: drei aktive `rustls`-Advisories geschlossen** (`reqwest` 0.11 → 0.12).
  `reqwest` 0.11 war der einzige Konsument des EOL-`rustls` 0.21 →
  `rustls-webpki` 0.101.7 mit zwei Cert-Validation-Bypässen
  (RUSTSEC-2026-0098/-0099: Name-Constraints für URI-/Wildcard-Namen fälschlich
  akzeptiert) und einem DoS-Panic (RUSTSEC-2026-0104, CRL-Parsing). Jetzt
  `rustls` 0.23.40 / `rustls-webpki` 0.103.13 — Krypto-Provider bleibt **`ring`**
  (kein `aws-lc-rs`, also kein neuer NASM-Build-Zwang auf Windows), Roots bleiben
  `webpki-roots` (unveraendertes Trust-Verhalten). Keine Code-Aenderung noetig.

### Changed

- **Provisioning-Antwort `monitorUrl` ist nun ein server-relativer Pfad
  (`/api/monitoring`).** Der Agent setzt ihn an die bereits TLS-vertraute
  Server-URL, gegen die er provisioniert wurde — der Metrik-Push trifft so immer
  denselben Host/Cert, ohne dass der Server seine oeffentliche Adresse kennen muss.
- **Desktop: `keyring`-Crate von 2.3 auf 3.6 angehoben.** Verhalten unveraendert
  (gleiche Backends: Linux `secret-service`/zbus + `crypto-rust`, macOS Keychain,
  Windows Credential Manager). Der Major-Bump zieht ein neueres `zbus` (4.x) nach
  und entfernt damit die als **unmaintained** geflaggte transitive Abhaengigkeit
  `derivative` (RUSTSEC-2024-0388); netto **-12** Crates im Lockfile. Dependabots
  vorgeschlagener Sprung auf `keyring` 4.0 wurde bewusst **nicht** uebernommen: Die
  4.x-Crate ist auf Sample-/CLI-Code umgebaut (re-exportiert `Entry`/`Error` nicht
  mehr → unbaubar) und zieht ueber den unbedingten `db-keystore`-Store eine ganze
  SQL-Engine (Turso) + Volltextsuche (Tantivy) + `bindgen` herein (+160 Crates).
- **Desktop: `windows`-Crate von 0.56 auf 0.61 angehoben.** Der `flags`-Parameter
  von `CredReadW`/`CredDeleteW` ist in 0.61 `Option<u32>` statt `u32` — der
  Windows-Credential-Code (`password.rs`) wurde entsprechend von `0` auf `Some(0)`
  angepasst. Verhalten unveraendert (`0` ≙ keine Flags). Nur subtraktiv im Lockfile
  (-5 Crates: doppelter 0.56-Subtree entfernt, 0.61.3 war via Tauri bereits
  vorhanden). Verifiziert per isoliertem Cross-Compile gegen `x86_64-pc-windows-gnu`,
  da der Linux-CI-Job den `#[cfg(windows)]`-Pfad nicht kompiliert.
- **Desktop-UI: Build-Toolchain modernisiert** — Vite 5→8, TypeScript 5→6,
  ESLint 9→10, `@sveltejs/vite-plugin-svelte` 4→7, `eslint-plugin-svelte` 2→3
  (+ `svelte-eslint-parser`, `globals`, `prettier-plugin-svelte`, `@types/node`).
  `tsconfig.json` auf relative `paths` ohne `baseUrl` umgestellt (TS-7-fest).
  Der strengere `eslint-plugin-svelte@3`-Regelsatz deckte echte Mängel auf, die
  **gefixt** statt unterdrückt wurden: 18 `{#each}`-Blöcke in den Monitoring-Views
  haben jetzt stabile `(key)` (korrekte DOM-Reconciliation beim Umsortieren/Entfernen),
  und `normalizeConnection` dedupliziert Connection-Tags (keine doppelten Tag-Chips,
  kollisionsfreie Keys). Drei Regel-Treffer waren Fehlalarme (uPlot-DOM-Interop,
  transiente `Map` in `$derived.by`, bewusste `$effect`-Dependency-Registrierung)
  und sind mit begründeten `eslint-disable`-Kommentaren versehen.
- **Web-Frontend: Build-Toolchain modernisiert** — Vite 5→8, TypeScript 5→6,
  ESLint 9→10, Vitest 2→4, `@sveltejs/vite-plugin-svelte` 4→7,
  `eslint-plugin-svelte` 2→3, Svelte 5.1→5.56, `typescript-eslint`,
  `@playwright/test`, `svelte-check`, `@types/node`, `globals`,
  `prettier-plugin-svelte`. Fehlendes direktes `@eslint/js` ergänzt (wurde unter
  ESLint 9 nur transitiv aufgelöst, unter 10 nicht mehr). `tsconfig.json` auf
  relative `paths` ohne `baseUrl` umgestellt (TS-7-fest). In `client.ts` eine tote
  `null`-Initialisierung entfernt. Die sieben `prefer-svelte-reactivity`- und der
  eine `no-dom-manipulating`-Treffer waren allesamt Fehlalarme (transiente
  `Map`/`Set` in `$derived.by`, Copy-then-reassign-Pattern, uPlot-DOM-Interop) und
  sind mit begründeten `eslint-disable`-Kommentaren versehen.
- **Ops: schwebende `:latest`-Images in `docker-compose.yml` gepinnt.**
  `snowdreamtech/frps` → `0.61.1` (im Gleichschritt mit der gebundelten frpc-Version
  `FRP_VERSION`, damit Server/Client nicht auseinanderlaufen) und
  `victoriametrics/victoria-metrics` → `v1.144.0` — reproduzierbare Deployments,
  keine ueberraschenden Versionsspruenge mehr. (Ein FRP-Bump auf 0.69.x ist bewusst
  separat zu testen.)
- **Server: totes `requests`-Dependency entfernt** (`apps/server/requirements.txt`);
  der einzige HTTP-Client ist `httpx` (`monitoring_proxy.py`).

### Fixed

- **Desktop:** frpc-Status wird nach Prozess-Ende zurueckgesetzt (Restart war
  zuvor mit „frpc laeuft bereits" blockiert). (#2)
- **Desktop:** Dashboard-Connections-Subscription wird in `onDestroy` aufgeraeumt
  (Subscription-Leak pro Navigation). (#6)
- **Desktop:** Wechsel in den Server-Modus mit gueltiger Session laedt jetzt
  neu und startet den Tunnel (zuvor erst nach Neustart). (#7)
- **Desktop:** re-entrantes `requestPassword` haengt nicht mehr den ersten
  Connect-Flow (in-flight-Prompt wird als „cancelled" aufgeloest). (#8)
- **Windows-Desktop:** Session-Load implementiert (`CredReadW`) — kein
  Re-Login mehr bei jedem Start. (#4)
- **Windows-Agent:** Service ist SCM-aware (`svc.Run`) — `sc start` laeuft nicht
  mehr in Fehler 1053. (#3)
- **Agent:** Watched-Service-Health wird pro Zyklus nur einmal erhoben (#5);
  letzter STOPPED-Service auf Windows korrekt als `enabled_inactive` (#11);
  re-Provisioning ueberschreibt `SERVICES` nicht mehr mit leer (#12).
- **Server:** `GET /api/frp/status` blockiert den Event-Loop nicht mehr
  (sync-Endpoint) (#9); Ansible-Playbook-Schreib/Loeschvorgaenge sind mit der
  DB-Transaktion geordnet (keine verwaisten Dateien/Rows) (#10).
- **Frontend:** englischsprachige Nutzer sehen keine deutschen Strings mehr
  (Tunnel-Status-Labels + ~54 `'Fehler'`-Toast-Fallbacks i18n-isiert) (#13);
  Metrik-Fetches bei schnellem Perioden-Wechsel werden sequenziert
  (kein Stale-Overwrite) (#14).

### Removed

- **Monitoring-Host-Port (`MONITOR_AGENT_PORT`/`8480`) aus `docker-compose.yml`
  entfernt** (nur noch `expose: 8080`).
  **Breaking (Ops):** Nach dem Upgrade muessen bereits provisionierte Agents
  **neu provisioniert** werden — ihre gespeicherte `MONITOR_URL` zeigt sonst auf
  den weggefallenen Port. Wer direkt gegen `:8480` skriptet, stellt auf
  `https://<server>/api/monitoring/agent/{id}/report` um.

## [0.24.0] - 2026-06-04

### Security

- **FRP-PKI-Schluessel jetzt `0600`, PKI-Verzeichnis `0700`.** Private Keys
  (`ca.key`, `frps.key`, Client-Keys) wurden zuvor umask-abhaengig (oft
  world-readable `0644`) geschrieben. `_write_key` erzeugt sie nun atomar mit
  `0600`; bestehende lax-permissionierte Deployments werden bei jedem
  PKI-Zugriff idempotent nachgezogen.
- **IDOR auf `GET /api/frp/provision/{server_id}/config(-hash)` geschlossen.**
  Mit einem beliebigen gueltigen Read-API-Key war zuvor die `frpc.toml`
  (globaler `auth.token` + STCP-Secrets) jedes Servers abrufbar. API-Keys sind
  jetzt an einen `server_id` gebunden; der Endpoint prueft die Server-Scope
  strikt (403) und ist Admin-only.
- **TOCTOU im Provision-Activate behoben.** Der Einmal-Token wird nun atomar
  per bedingtem `UPDATE ... WHERE used_at IS NULL` konsumiert; ein verlorenes
  Rennen liefert `409` und erzeugt fail-closed keinen API-Key.
- **Hook-Ausfuehrung: ehrliche Sicherheits-Posture.** Das wirkungslose
  `exec()`-Pseudo-Sandbox wurde entfernt; die Worker-Umgebung ist auf das
  Noetigste minimiert (entfernt u.a. `ADMIN_PASSWORD`). Hooks bleiben bewusst
  vertrauenswuerdiger Admin-Code mit DB-Zugriff — das ist nun dokumentiert und
  testverankert, statt faelschlich „isoliert" zu suggerieren.

### Added

- **GitHub Actions CI/CD.** `ci.yml` (Lint/Tests aller Komponenten),
  `docker.yml` (Server- + Monitoring-Images nach ghcr.io) und `release.yml`
  (Desktop-DEB/RPM, Agent-Pakete + Binaries, Checksums, Draft-Release).
- **Periodische JWT-Blacklist-Bereinigung.** `cleanup_expired_blacklist` laeuft
  jetzt als System-Job (Intervall 6 h); zuvor wuchs die `token_blacklist`-
  Tabelle unbegrenzt.
- **Server-Bindung fuer API-Keys** (`api_keys.server_id`, inkl.
  Alembic-Migration mit Backfill).

### Changed

- **Docker-Images kommen aus ghcr.io**
  (`ghcr.io/ks98/adminhelper/{server,monitoring}`); `docker-compose.yml` und
  `.env.example` entsprechend vereinheitlicht.
- **Quellcode-Kommentare und README auf Englisch** vereinheitlicht; Doku-Links
  und CI-Beschreibung von GitLab auf GitHub umgestellt. Lokalisierte
  UI-Strings (DE/EN) bleiben unveraendert.

### Removed

- Toter Code: `ScriptSecurityError`, `ScriptTimeoutError`, ungenutzte
  `UserResponse` und die wirkungslose Hook-Sandbox.

### Fixed

- Alembic-`downgrade` Postgres-kompatibel (`sa.DateTime()` / `sa.String()`
  statt `sa.DATETIME()` / `sa.VARCHAR()`).

## [0.23.2] - 2026-05-03

### Fixed

**Desktop-Client: alte Connections nach Server-Wechsel sichtbar**

Beim Wechsel zwischen zwei AdminHelper-Servern (Login zu B nach Login zu A,
oder serverUrl-Aenderung in den Settings) blieben die Verbindungen vom
vorherigen Server im Desktop-Client sichtbar — sowohl im Memory-Store als
auch persistent in `connections.json` (Tauri-AppDataDir). Bei Fehlschlag
des Fetch-Calls zum neuen Server (z.B. falscher Port) blieb der alte Stand
unveraendert.

Drei Code-Pfade hatten den Connection-Reload nicht getriggert:

- `session.ts:login()` aktualisierte nur das Session-Objekt, ohne
  `connections.reloadForMode()` zu rufen → frischer Login zu Server B
  liess die alten Daten von Server A stehen, bis der User manuell die
  Connections-Page wechselte (was ohne Trigger auch nichts neu lud).
- `session.ts:logout()` setzte nur die Session auf `null`, leerte aber
  nicht den Connection-Cache → die Datei blieb voll mit Server-A-Daten
  und tauchte nach dem naechsten App-Start wieder auf.
- `settings.ts:saveSettings()` ignorierte serverUrl-Wechsel mit aktiver
  Session — das alte JWT gehoerte zum alten Server, der neue Server
  haette es abgelehnt, aber der User merkte das nie, weil kein Reload
  triggerte.

Fix: Login triggert nun `reloadForMode(settings, sess)` direkt nach dem
Token-Setzen. Logout leert vor dem Session-Reset den Connection-Cache
(Memory + Datei via `saveAll([])`). Settings erzwingen bei serverUrl-
Wechsel mit aktiver Session ein `serverLogout()`, sodass der User in den
needsLogin-Flow geschickt wird.

## [0.23.1] - 2026-05-03

### Highlights

**Server-zentrisches Provisioning** — bis v0.22.x war der Provision-Flow
fest an FRP gekoppelt; wer keinen Tunnel hatte, konnte den Token-Flow nicht
nutzen und bekam keinen Monitor-Agent-Key. Ab v0.23.x lebt Provisioning im
Server-Modul und liefert je nach Konfiguration optional FRP-Bundle und
Monitor-Key. Ein einziger Agent-Aufruf ersetzt das alte zweistufige Setup.

(v0.23.0 wurde lokal getaggt, aber nie auf origin gepusht — der CI-Job
scheiterte an einer Prettier-Verletzung in `Frp.svelte`. v0.23.1 enthaelt
denselben Funktionsumfang plus den Style-Fix.)

### Fixed

- `prettier --check` failte im CI-Job auf `Frp.svelte`, weil beim Entfernen
  der Provision-Modal-Einbindung eine ueberzaehlige Leerzeile stehengeblieben
  war. Inhaltlich kein Effekt, blockierte aber die Tag-Pipeline.

### Added

- Neues Backend-Modul `app.modules.provisioning` mit Endpoints
  `POST /api/servers/{id}/provision/token`, `GET /tokens` und
  `POST /activate` (Header `X-Provision-Token`). Activate-Antwort:
  `{ serverName, apiKey, monitorApiKey?, monitorUrl?, frp? }` —
  Felder sind `null`, wenn die jeweilige Komponente nicht konfiguriert
  oder nicht erreichbar ist. Resilience-Pattern: ausgefallener
  Monitor-Service blockiert das Provisioning nicht.
- Neuer Agent-Subbefehl `adminhelper-agent provision --url ... --token ... --server-id ...`
  in `internal/provision/`. Orchestriert Activate-Aufruf, dann je nach
  Antwort `monitor.Init` und `frpc.Apply`.
- Frontend: `ServerProvisionModal.svelte` an der Servers-Page (statt
  vorher in der Frp-Page); generiert genau einen `provision`-Befehl
  zum Kopieren.
- Tests: `server/tests/test_provisioning.py` mit pytest-httpx-Mocking
  fuer den Monitor-Service-Aufruf (8 Testfaelle, u.a. minimal/with-monitor/
  monitor-down/wrong-token/used-twice/wrong-server).
- Neue Test-Dependency: `pytest-httpx>=0.30` in `requirements-dev.txt`.

### Changed

- Tabelle `frp_provision_tokens` umbenannt zu `provision_tokens` per
  `op.rename_table` (nicht-destruktive Alembic-Migration
  `0494a8f377ef_rename_frp_provision_tokens_to_provision_tokens`).
  Constraints (PK, UNIQUE auf `hashed_token`, FK auf `servers`) werden
  von Postgres automatisch mit umbenannt.
- `frpc.Init` (HTTP + Datei + Service in einem) wurde zu `frpc.Apply`
  (nur Datei + Service) zerlegt — der HTTP-Activate-Aufruf wandert in
  das neue `internal/provision/` Package.
- `frp/models.py` exportiert `ProvisionToken` weiterhin (Re-Export aus
  `app.modules.provisioning.models`) als Backwards-Compat fuer Test-
  Fixtures, die das alte Symbol importieren.

### Removed (Breaking)

- Alte Endpoints `/api/frp/provision/{id}/token`, `/tokens` und `/activate`
  sind komplett entfernt — Pre-Release, kein Deprecation-Window.
  Das FRP-Modul behaelt nur noch `/api/frp/provision/{id}/config` und
  `/config-hash` fuer den laufenden Sync-Agent.
- Agent-Subbefehl `adminhelper-agent frpc init` ist entfernt — Setup
  laeuft nun ausschliesslich ueber `adminhelper-agent provision`.
- Frontend-API: `createMonitoringAgentKey()` (toter Code, war im alten
  Modal als Fallback gedacht) und der API-Type `MonitoringAgentKeyResult`
  sind weg. Die zugehoerigen Funktionen `listProvisionTokens` /
  `createProvisionToken` sind aus `lib/api/frp.ts` in das neue
  `lib/api/provisioning.ts` umgezogen, Types `FrpProvisionToken[…]`
  heissen jetzt `ProvisionToken[…]`.
- Versions-Bump aller Komponenten auf `v0.23.1` (Server, Monitoring,
  Web-Admin-Panel, Desktop-Client, Browser-Extension, Go-Agent via
  `.gitlab-ci.yml AGENT_VERSION`, 40 Doku-HTML-Footer).

## [0.22.1] - 2026-05-02

### Fixed

- `docker compose pull` scheiterte mit `pull access denied for
  adminhelper-monitoring`, weil das Monitoring-Image nirgends in
  der Registry lebte (es gab nur einen `docker_server`-Job). Neuer
  `docker_monitoring`-Job in `.gitlab-ci.yml` (1:1 analog zu
  `docker_server`) baut + pusht jetzt das Monitoring-Image nach
  `docker.nevondo.com/$CI_PROJECT_PATH/monitoring` mit den Tags
  SHA, `latest`, `dev` (main-Branch) und `$CI_COMMIT_TAG` (bei Tags).
  `MONITORING_IMAGE`-Default in `docker-compose.yml` zeigt jetzt
  auf den Registry-Pfad statt den nicht-pullbaren lokalen Tag.

### Changed

- Versions-Bump aller Komponenten auf `v0.22.1` (Patch-Release).

## [0.22.0] - 2026-05-02

### Changed

- Koordinierter Versions-Bump aller Komponenten auf `v0.22.0`
  (Server, Web-Admin-Panel, Desktop-Client, Browser-Extension,
  Go-Agent via `.gitlab-ci.yml AGENT_VERSION`, Doku-Footer in
  40 HTML-Dateien). Sammel-Release ohne funktionale Aenderungen.

### Fixed

- CI-Job `server_test` scheiterte mit `pytest: command not found`,
  weil `pytest` und `testcontainers` nur lokal im venv installiert
  waren, nicht in `requirements.txt`. Neu: `requirements-dev.txt`
  mit `pytest`, `pytest-asyncio` und `testcontainers[postgres]`;
  CI installiert beide Files. Production-Container (Dockerfile)
  bleibt schlanker, weil testcontainers + pytest nicht mehr in
  jedem Server-Image landen.

## [0.21.0] - 2026-05-02

### Highlights

**Pre-Release-Welle**: drei groesse Stoesse parallel gefahren —
Brand-Umbenennung **SimpleRemoteManager/SRM &rarr; AdminHelper**,
**6 P0-Sicherheits-Fixes** aus dem Pre-Release-Audit, und Migration
der Server-Side-Persistenz von **SQLite auf PostgreSQL 17**
(server + monitoring). Plus 2 P1-Cleanups, Plain-JS-Desktop-Client-
Reste entfernt, Doku komplett aufgeraeumt.

Beide FastAPI-Services teilen sich einen Postgres-Cluster mit zwei
DBs (`adminhelper`, `adminhelper_monitor`). Schema-Anlage uebernimmt
jetzt **Alembic** statt `Base.metadata.create_all()`. Tests laufen
gegen ein echtes Postgres via `testcontainers` (lokal) bzw.
`services: postgres:17-alpine` (CI), nicht mehr gegen SQLite-in-memory.

22 Commits seit v0.20.0.

### Brand

- Vollstaendige Umbenennung des Projekts von "SimpleRemoteManager"
  (intern auch "SRM") auf **"AdminHelper"** &mdash; in Doku, Code,
  Storage-Keys (localStorage `adminhelper_token`, `adminhelper_refresh_token`,
  `adminhelper_language`), Tauri-Keyring-Service (`com.adminhelper.app`),
  Browser-Extension, FRP-Provision-Token-Prefix, Go-Agent-Variablen.
- GitLab-Repo migriert auf <https://git.nevondo.com/ks98/adminhelper>;
  Doku-Verweise und CHANGELOG-Release-Links aktualisiert.
- Bewusst behalten: Legacy-Paketnamen (`srm-frpc-client`, `srm-monitor-agent`,
  `srm-agent`) in DEB-`Replaces`/RPM-`Obsoletes` &mdash; werden gebraucht
  fuer DEB/RPM-Upgrades von Vorgaenger-Installationen.

### Security (Pre-Release-Audit-Fixes)

- **P0-1**: API-Key wird jetzt zusaetzlich als Query-Parameter akzeptiert
  (`?api_key=...`), nicht nur als `X-API-Key`-Header &mdash; Browser-
  Extension funktionierte vorher gar nicht.
- **P0-2**: `MONITOR_API_KEY`-Mismatch zwischen server und monitoring
  geloest; `init-secrets.sh` generiert jetzt einen synchronen Wert.
  Vorher: Default-Setup hatte 401 auf jedem `/api/monitoring/*`-Aufruf.
- **P0-3**: Authorization-Bypass im FRP-Visitor-Bundle behoben &mdash;
  Non-Admin-User ohne Server-Zuweisungen sahen vorher *alle* STCP-Tunnel
  inklusive Secret-Keys (`if server_ids:`-Logik invertiert). Plus
  5 Regression-Tests in `test_frp_permissions.py`.
- **P0-4**: Frontend-Logout invalidiert JWT jetzt auch serverseitig
  via `POST /api/auth/logout`. Vorher: Token blieb 8h gueltig nach "Abmelden".
- **P0-5**: Security-Headers-Middleware hinzugefuegt
  (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
  CSP nur fuer SPA-HTML, nicht fuer `/api/docs` (Swagger-UI braucht CDN).
- **P0-6**: Default-Admin `admin/admin` entfernt; ersetzt durch
  Bootstrap-Token-Pattern (Vaultwarden/Gitea-Style). Server schreibt
  Setup-Token in `data/.bootstrap_token`, Admin wird ueber
  `POST /api/auth/bootstrap` angelegt. 6 neue Endpoint-Tests.
- **P1-6 + P1-7**: stale `server/frontend/`-Stub-Verzeichnis entfernt,
  Dead Config `MONITOR_AGENT_API_KEYS` aus `docker-compose.yml` raus.

### Database (SQLite &rarr; PostgreSQL)

- PostgreSQL 17 als neuer `postgres`-Service in `docker-compose.yml`
  mit Healthcheck und `service_healthy`-Dependencies fuer beide Apps.
- `server/alembic/` und `monitoring/alembic/` mit initialen Migrations.
- `monitoring/docker-entrypoint.sh` neu (vorher nur `CMD`).
- Server- und Monitoring-Entrypoint warten via `pg_isready` auf die DB
  und fuehren `alembic upgrade head` vor `uvicorn`-Start aus.
- `scripts/postgres-init.sh` legt beim ersten Postgres-Start die zweite
  DB (`adminhelper_monitor`) idempotent an.
- `scripts/pg-backup.sh` + `scripts/pg-restore.sh` fuer pg_dump-basiertes
  Backup beider DBs (Custom-Format, 7-Tage-Retention).
- Optionaler `pg-backup`-Service in `docker-compose.yml` (auskommentiert
  als Opt-In-Beispiel) &mdash; taegliche Backups nach `./backups/`.
- `init-secrets.sh` erzeugt zusaetzlich `POSTGRES_PASSWORD` (32 Bytes hex).
- `psycopg[binary]>=3.1`, `alembic>=1.13` in beiden requirements.txt.
- `testcontainers[postgres]>=4.7` als dev-dependency im server.
- Server-`pytest`-Job in `.gitlab-ci.yml` (existierte vorher nicht):
  nutzt `services: postgres:17-alpine` als CI-Sidecar.
- `tests/test_alembic_consistency.py`: Drift-Detector zwischen
  `Base.metadata` und Alembic-Migrations, laeuft bei jedem CI-Run.

### Other

- Plain-JS-Desktop-Client (`desktop/src/`, ~6670 Zeilen) komplett
  geloescht &mdash; war seit v0.19.0 nur noch historisch im Repo.
  8 Migrationskontext-Kommentare in `desktop-src/` bereinigt.
- `/api/docs` Swagger-UI-Pfad in der Doku korrigiert (war faelschlich
  als `/docs` dokumentiert; `app/main.py` setzt explizit
  `docs_url='/api/docs'`).
- README + DEVELOPMENT.md auf aktuellen v0.20.0-Stand gebracht
  (Lead-Beschreibung Svelte 5, Project-Tree mit `desktop-src/` +
  `frontend-src/` als produktiven Frontends).

### Changed

- Server-Side-DBs von SQLite auf PostgreSQL umgestellt:
  - `server/app/core/database.py` + `monitoring/app/core/database.py`:
    Engine ohne `check_same_thread`, dafuer Pool (size=10, overflow=20,
    pre-ping, recycle=3600).
  - `server/app/core/config.py` + `monitoring/app/core/config.py`:
    `DATABASE_URL` aus Env mit Postgres-Default-Fallback.
- Beide Dockerfiles installieren `postgresql-client` (fuer `pg_isready`),
  kopieren `alembic/`-Folder in den Container.
- `server/tests/conftest.py` komplett neu: testcontainers-Postgres,
  SAVEPOINT-Pattern fuer Test-Isolation (kein DROP/CREATE pro Test).
- Tests jetzt 78 (77 bestehende + 1 alembic-consistency); Wallclock
  ~17s lokal (12s Container-Boot einmalig), ~8s im Cache-Lauf.

### Removed

- `_migrate_connections_json`, `_migrate_add_columns`,
  `_migrate_visitors_to_users` aus `server/app/main.py` (PRAGMA-basierte
  SQLite-only Migrationen, jetzt durch Alembic ersetzt).
- `_migrate_columns`, `_migrate_agent_keys_to_hash` aus
  `monitoring/app/main.py` (gleiches Pattern).
- `Base.metadata.create_all()` aus beiden Lifespans (Alembic ist neuer
  Schema-Owner).
- `CONNECTIONS_FILE`-Konstante aus `server/app/core/config.py`
  (Konsument war `_migrate_connections_json`).
- `desktop/src/` (Plain-JS-Frontend) und 8 SQLite-Stub-Files unter
  `server/frontend/`.

### Migration

- Bestehende lokale `data/db.sqlite3` und `data/monitor.sqlite3` sind
  obsolete und koennen geloescht werden.
- Pre-Release-Status: keine Production-Datenmigration noetig.
- Beim Update bestehender Setups vor dem ersten Restart:
  `./scripts/init-secrets.sh` ausfuehren, damit `POSTGRES_PASSWORD`
  in der `.env` steht (sonst weigert sich der Postgres-Container).
- `data/`-Verzeichnis bleibt erhalten (Bootstrap-Token, .secret_key,
  FRP-PKI), nur die DB-Datei darin ist obsolete.

### Added

- PostgreSQL 17 als neuer `postgres`-Service in `docker-compose.yml`
  mit Healthcheck und `service_healthy`-Dependencies fuer beide Apps
- `server/alembic/` und `monitoring/alembic/` mit initialen Migrations
- `monitoring/docker-entrypoint.sh` neu (vorher nur `CMD`)
- Server- und Monitoring-Entrypoint warten via `pg_isready` auf die DB
  und fuehren `alembic upgrade head` vor `uvicorn`-Start aus
- `scripts/postgres-init.sh` legt beim ersten Postgres-Start die zweite
  DB (`adminhelper_monitor`) idempotent an
- `scripts/pg-backup.sh` + `scripts/pg-restore.sh` fuer pg_dump-basiertes
  Backup beider DBs (Custom-Format, 7-Tage-Retention)
- Optionaler `pg-backup`-Service in `docker-compose.yml` (auskommentiert
  als Opt-In-Beispiel) — taegliche Backups nach `./backups/`
- `init-secrets.sh` erzeugt zusaetzlich `POSTGRES_PASSWORD` (32 Bytes hex)
- `psycopg[binary]>=3.1` und `alembic>=1.13` in beiden requirements.txt
- `testcontainers[postgres]>=4.7` als dev-dependency im server
- Server-`pytest`-Job in `.gitlab-ci.yml` (existierte vorher nicht):
  nutzt `services: postgres:17-alpine` als CI-Sidecar
- `tests/test_alembic_consistency.py`: Drift-Detector zwischen
  `Base.metadata` und Alembic-Migrations, laeuft bei jedem CI-Run

### Changed

- Server-Side-DBs von SQLite auf PostgreSQL umgestellt:
  - `server/app/core/database.py` + `monitoring/app/core/database.py`:
    Engine ohne `check_same_thread`, dafuer Pool (size=10, overflow=20,
    pre-ping, recycle=3600)
  - `server/app/core/config.py` + `monitoring/app/core/config.py`:
    `DATABASE_URL` aus Env mit Postgres-Default-Fallback
- Beide Dockerfiles installieren `postgresql-client` (fuer `pg_isready`),
  kopieren `alembic/`-Folder in den Container
- `server/tests/conftest.py` komplett neu: testcontainers-Postgres,
  SAVEPOINT-Pattern fuer Test-Isolation (kein DROP/CREATE pro Test)
- Tests jetzt 78 (77 bestehende + 1 alembic-consistency); Wallclock
  ~17s lokal (12s Container-Boot einmalig), ~8s im Cache-Lauf

### Removed

- `_migrate_connections_json`, `_migrate_add_columns`,
  `_migrate_visitors_to_users` aus `server/app/main.py` (PRAGMA-basierte
  SQLite-only Migrationen, jetzt durch Alembic ersetzt)
- `_migrate_columns`, `_migrate_agent_keys_to_hash` aus
  `monitoring/app/main.py` (gleiches Pattern)
- `Base.metadata.create_all()` aus beiden Lifespans (Alembic ist neuer
  Schema-Owner)
- `CONNECTIONS_FILE`-Konstante aus `server/app/core/config.py`
  (Konsument war `_migrate_connections_json`)

### Migration

- Bestehende lokale `data/db.sqlite3` und `data/monitor.sqlite3` sind
  obsolete und koennen geloescht werden.
- Pre-Release-Status: keine Production-Datenmigration noetig.
- Beim Update bestehender Setups vor dem ersten Restart:
  `./scripts/init-secrets.sh` ausfuehren, damit `POSTGRES_PASSWORD`
  in der `.env` steht (sonst weigert sich der Postgres-Container).
- `data/`-Verzeichnis bleibt erhalten (Bootstrap-Token, .secret_key,
  FRP-PKI), nur die DB-Datei darin ist obsolete.

## [0.20.0] - 2026-04-19

### Changed

- Koordinierter Versions-Bump ueber alle Komponenten
  (Desktop-Client, Web-Admin-Panel, Go-Agent, Browser-Extension,
  Docker-Image, CI-Pipeline) auf `v0.20.0` — Sammel-Release ohne
  funktionale Aenderungen, um alle Artefakte wieder auf einen
  gemeinsamen Versions-Stand zu heben

## [0.19.1] - 2026-04-18

### Changed

- Einmalige Prettier-Formatierung ueber `frontend-src/` (rein
  kosmetisch, 31 Dateien)

### Fixed

- CI-Failure bei `npm run lint` im Frontend behoben: ESLint 9
  Flat-Config (`eslint.config.js`) eingefuehrt, `typescript-eslint` +
  `globals` als Dev-Dependencies ergaenzt, `.prettierignore` fuer
  `frontend-src/`

## [0.19.0] - 2026-04-18

### Highlights

Big-Bang-Migration des **Desktop-Clients** von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (11 Phasen). Das alte `desktop/src/`
wurde vollstaendig durch `desktop-src/` ersetzt und baut ueber
`npm --prefix ../desktop-src run build` in den Tauri-Release.
Funktional bleibt der Client unveraendert; intern ist alles typisiert
und reaktiv ueber Stores statt DOM-imperativen Managern.

Zusaetzlich in 0.19.0: mehrere Security-Haertungen (Refresh-Token-
Rotation mit Blacklist/Reuse-Detection, Login-Rate-Limit auf Redis,
Tauri-Capability-Scoping, PKI-Bundle-Zip-Slip-Schutz), ein komplett
ueberarbeitetes Monitoring-Dashboard sowie ein Doku-Komplett-Rewrite
mit getrennten Admin- und Developer-Sektionen (DE + EN).

### Added

- `desktop-src/` als eigenstaendiges Projekt (kein Monorepo) mit
  Svelte 5 Runes, TS strict, Vite-Build, Pfad-Aliassen (`$lib`)
- Typisierte Tauri-Bridge (`src/lib/bridge/`) mit 1:1-Mapping zu allen
  24 `#[tauri::command]` Backend-Funktionen
- Store-Architektur: `sessionStore`, `connectionsStore`, `tunnelStore`,
  `monitoringStore`, `ansibleStore`, `settingsStore`, `connectFlow`,
  `passwordPrompt`, `editorStore`, `statusBarStore`
- Seiten: Dashboard, Connections (mit Live-Suche + Kind/Group-Filter),
  Monitoring (Overview/Alerts/Log mit uPlot-Charts), Ansible
  (3-Stufen-Wizard mit Server/Tag-Auswahl)
- Modals: ConnectionEditor, PasswordPrompt (Promise-Continuation),
  SettingsModal (Sync/Server-Mode, RDP-Optionen, Sprache, Logout)
- Connect-Flow mit RDP-Race-Guard (monotone Connect-ID) und
  Tunnel-Auto-Resolve fuer Server-Modus
- Vitest-Suite: 41 Tests fuer Models (connection, settings, ansible,
  monitoring) und Stores (ansible, connections)
- Monitoring-Detail: Current-Values-Panel und Status-Timeline pro Check
- Grouped-View und Tree-View fuer die Connections-Seite
- Scroll-Beschleunigung als wiederverwendbare Svelte-Action
- Refresh-Token-Rotation mit Token-Blacklist und Reuse-Detection
  (kompromittierte Tokens werden erkannt und alle Sessions der
  betroffenen User-Kette invalidiert)
- Komplette Dokumentation neu aufgesetzt: getrennte Admin- und
  Developer-Sektionen, vollstaendige EN-Spiegelung unter `docs/en/`

### Changed

- `desktop/src-tauri/tauri.conf.json` `beforeBuildCommand` zeigt auf
  `../desktop-src` statt `../src`
- Sidebar-Version-Label auf `v0.19.0`
- Monitoring-Detail auf Sektions-Dashboard umgestellt: pro Server werden
  alle Checks in typ-spezifischen Sektionen (Heartbeat, Live, Network,
  Services, Docker, Backups, ZFS, SMART) gruppiert; jede Zeile klappt
  inline auf zu Perioden-Tabs (1h/6h/24h/7d) mit Graph und Timeline
- Monitoring-Dashboard v2: Card-Layout mit typ-spezifischen Heroes,
  Master-Detail-Layout fuer die Overview, Sektions-basiertes Dashboard
  statt Card-Grid
- Connections-Liste: Card fungiert als Connect-Button, Edit-Icon nur
  noch per Hover eingeblendet, aufgeraeumte Button-Anordnung
- Login-Rate-Limit auf Redis migriert (mit In-Memory-Fallback, wenn
  Redis nicht erreichbar ist) — skaliert ueber mehrere Server-Worker
  hinweg konsistent
- Tauri-Capabilities strikt gescopt (minimale Permissions statt
  Default-Allow-All), RDP-Fenstertitel werden sanitisiert
- i18n fuer Stores, Validatoren und `timeAgo` eingefuehrt, i18n-Leaks
  in AppShell/App/Connections geschlossen
- `metricLabel` als eigenes Modul ausgelagert, toter Alert-Log-Wrapper
  entfernt

### Fixed

- RDP-Race-Condition zwischen aufeinanderfolgenden Connects ueber
  Correlation-IDs geschlossen
- `lastUsed` wird pro Connect-Modus getrennt gefuehrt (statt global)
- `trustCert`-Checkbox logisch zu RDP zugeordnet (war faelschlich
  auch bei Web aktiv)
- Transparente Modals durch fehlende `--bg-panel`- und
  `--bg-input`-CSS-Variablen beseitigt
- PKI-Bundle-Import gegen Zip-Slip und Zip-Bomb geschuetzt, erzeugte
  Secrets landen mit `0600` auf der Platte
- Visuelle Regressionen, Monitoring-TLS-Handling und i18n-Engine
  in der Desktop-UI

### Removed

- Altes Plain-JS-Frontend (`desktop/src/`) wird vom Tauri-Build nicht
  mehr verwendet (bleibt historisch im Repo erhalten, bis alle
  Referenzen entfernt sind)
- Monitoring-Card-Grid, Filter-Bar, View-Switch und Hero-Komponenten
  (`MonCheckPanel/Card/Row`, `MonFilterBar`, `MonDetailPanel`,
  `hero/Hero*.svelte`) — ersetzt durch `MonServerDashboard` +
  `section/Sec*.svelte` mit wiederverwendbarem `MonCheckLine`-Snippet

## [0.17.0] - 2026-04-18

### Highlights

Big-Bang-Migration des Web-Admin-Panels von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (12 Phasen). Das alte `server/frontend/`
wurde vollstaendig durch `frontend-src/` ersetzt und wird im Docker-Image
ueber einen Multi-Stage-Build ausgeliefert.

### Added

- Svelte 5 Frontend in `frontend-src/` mit Hash-Router, Token-Auth,
  i18n (DE/EN), Toast- und ConfirmDialog-Komponenten
- UI-Komponentenbibliothek (`Button`, `Modal`, `TagChip`, `Tabs`,
  `EmptyState`, uvm.) mit einheitlichem Design-System
- Alle 8 Produktiv-Seiten portiert: Connections, Servers, Users,
  API-Keys, Hooks, Ansible, FRP-Tunnels, Monitoring
- Monitoring-Seite mit uPlot-Charts fuer SMART-Temperaturen und
  Resource-Gauges
- Playwright E2E-Tests: Smoke-Tests fuer alle 8 Routen + Login,
  Visual-Diff Screenshots (`frontend-src/tests/e2e/`)
- CI: neue `check`-Stage mit `frontend_check` (svelte-check + lint)
  und `frontend_e2e` (Playwright mit HTML-Report-Artifact)
- Repo-Root `Dockerfile` als Multi-Stage-Build (Vite-Build ->
  Python-Runtime) und `.dockerignore`
- SMART-Health-Monitoring mit Kind-Erkennung (SATA/SAS/NVMe),
  Temperatur-Thresholds und NVMe-Bit-Dekodierung

### Changed

- `docker_server`-CI-Job: Build-Context auf Repo-Root (`-f Dockerfile .`)
- `server/app/main.py`: Static-Mounts auf Vite-Output angepasst
  (`/assets`, `/fonts`), SPA-Fallback prueft erst Datei-Existenz
- Agent-Version auf 0.17.0 synchronisiert (Desktop, Extension,
  Go-Agent-Pakete)

### Fixed

- Strict-MIME-Error auf `/assets/*.js` durch dedizierten Static-Mount
- Unterstrichene Sidebar-Menueeintraege (Browser-Default fuer `<a href>`)
- Fehlende Modal-Body-/Footer-Styles (Buttons klebten aneinander)
- Favicon-Referenz in `index.html` korrigiert (`/logo.svg`)
- Redirect nach Login via `$effect` statt nur in `onMount`

### Removed

- Altes Plain-JS-Frontend (`server/frontend/`) und separates
  `server/Dockerfile` + `server/.dockerignore`

## Vorherige Versionen

Aeltere Releases siehe Git-Tags `v0.7.0` bis `v0.16.0`.

[0.34.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.34.0
[0.33.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.33.0
[0.32.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.32.1
[0.32.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.32.0
[0.31.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.31.0
[0.30.4]: https://github.com/ks98/AdminHelper/releases/tag/v0.30.4
[0.30.3]: https://github.com/ks98/AdminHelper/releases/tag/v0.30.3
[0.30.2]: https://github.com/ks98/AdminHelper/releases/tag/v0.30.2
[0.30.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.30.1
[0.30.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.30.0
[0.29.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.29.0
[0.28.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.28.0
[0.27.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.27.0
[0.26.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.26.0
[0.25.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.25.0
[0.24.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.24.0
[0.23.2]: https://github.com/ks98/AdminHelper/releases/tag/v0.23.2
[0.23.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.23.1
[0.22.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.22.1
[0.22.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.22.0
[0.21.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.21.0
[0.20.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.20.0
[0.19.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.19.1
[0.19.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.19.0
[0.17.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.17.0
