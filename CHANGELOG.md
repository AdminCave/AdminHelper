# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

- **Server: `GET /api/servers/summary`:** liefert je Server nur `id`, `name` und `hostname`, nach Name sortiert
  (admin), fuer die Server-Zuweisung im Benutzerdialog des Web-Panels, das dafuer bisher das ganze Inventar samt
  Verbindungen und Tunneln lud. Doku: API-Referenz fuer Entwickler (DE+EN).
- **Event `user.promoted` bei einer Hochstufung zum Admin:** Setzt `PUT /api/users/{id}` das Admin-Recht eines
  Benutzers von `false` auf `true`, feuert der Server das Event `user.promoted` mit `id` und `username`; Event-Hooks
  koennen es abonnieren (Auswahl im Web mit Beschriftung DE+EN). Die Glocke meldet die Hochstufung unter
  „Sicherheit“ wie einen neu angelegten Admin („User promoted to admin: <Name>“, Schweregrad `warning`). Eine
  Herabstufung feuert kein Event. Doku: Monitoring (DE+EN), Hooks, Server und API-Referenz fuer Entwickler (DE+EN).
- **Agent: `provision --token-stdin` liest den Provisionierungs-Token von stdin:** Bisher nahm `adminhelper-agent
  provision` den Token nur als `--token`, also als Programmargument, das fuer die Dauer des Aufrufs in der
  Prozessliste steht. Mit `--token-stdin` liest es die erste Zeile von stdin (hoechstens 4 KiB, Leerraum an den Enden
  entfaellt) als Token. `--token` und `--token-stdin` schliessen einander aus, einer von beiden ist Pflicht; Aufrufe
  mit `--token` bleiben gueltig. Bleibt auf stdin kein Token, bricht `provision` mit „no provision token on stdin“ ab,
  bevor es den Server anspricht.
- **`install.sh --admin-password-file` liest das Admin-Passwort aus einer Datei:** Fuer eine nicht-interaktive
  Installation nahm `install.sh` das Passwort des Erst-Admins bisher nur als `--admin-password`, also als
  Programmargument, das fuer den ganzen Lauf in der Prozessliste und in der Shell-History steht. `--admin-password-file
  DATEI` nimmt die erste Zeile der Datei als Passwort (ein `\r` am Zeilenende entfaellt); ein relativer Pfad gilt ab
  dem Verzeichnis, in dem `install.sh` gestartet wurde, auch wenn es die Laufzeit-Dateien nach `--dir` laedt. Ist die
  Datei nicht lesbar oder ihre erste Zeile leer, bricht `install.sh` ab, bevor es etwas anlegt, und nennt nur den Pfad.
  `--admin-password` funktioniert weiter und weist auf stderr auf `--admin-password-file` hin; beide zusammen sind ein
  Fehler. README und Installations-Doku (DE+EN) nennen fuer den nicht-interaktiven Lauf nur noch
  `--admin-password-file`.
- **`SMTP_CA_FILE` fuer Relays mit eigener CA, im Notification-Hub und im Monitoring:** Die optionale Variable nennt
  eine PEM-Datei im Container mit der CA des Relays (selbstsigniertes Zertifikat oder Firmen-CA). Hub und E-Mail-Kanal
  der Alert-Regeln laden sie zusaetzlich zu den System-CAs, im Monitoring fuer jeden Relay, auch den einer Regel;
  Zertifikat und Hostname werden weiter geprueft. Eingebunden wird sie per `docker-compose.override.yml` (Variable und
  Datei fuer `server`, `scheduler` und `monitoring`), nicht ueber `docker-compose.yml` oder `.env.example`. Laesst
  sich die Datei nicht laden, geht keine Mail hinaus: Der Hub nennt den Grund im Log des `scheduler`-Dienstes, das
  Monitoring vermerkt `SMTP TLS failed` im Alert-Log. Ein Relay ohne STARTTLS bleibt auch damit aussen vor. Doku:
  Betrieb & Konfiguration, Monitoring (DE+EN).
- **Diagnose-Bundle: IP-Adressen und die Hostnamen der Installation auf Wunsch maskieren:**
  `scripts/diagnostics.sh --mask-hosts` ersetzt IPv4- und IPv6-Adressen nach ihrer Form durch `<ip>` (eine
  IPv6-Adresse mit IPv4-Ende wie `::ffff:192.0.2.1` als eine Adresse; ein Image-Tag aus vier Zahlen wie
  `.../server:1.2.3.4` bleibt stehen) und jeden Namen und jede Adresse aus `DOMAIN`, `EXTRA_SANS`, `CA_FRPS_EXTRA_SANS`, `ALLOWED_IPS`, `FRP_SERVER_ADDR`,
  `TRUSTED_PROXIES`, `SMTP_HOST` und `SMTP_FROM` (bei `SMTP_FROM` jede Adresse, bei einem Anzeigenamen nur die
  Adresse in spitzen Klammern, nicht der Name) sowie den Rechnernamen, auch ohne seine Domain, durch `<host>`, in
  `report.txt`, den Logs und
  `env.sanitized` (dort stehen diese Schluessel als `<masked>`). Ein Name mit Punkt trifft ohne Ruecksicht auf
  Gross-/Kleinschreibung und samt der Namen darunter (`registry.ah.example.com` bei `DOMAIN=ah.example.com`); ein
  Rechnername ohne Punkt nur in seiner Schreibweise und als ganzes Wort, samt einer Domain dahinter, nicht als Teil
  eines Dienst- oder Image-Namens (`adminhelper-server-1`, `.../server:0.46.0` bleiben stehen). Andere Namen, etwa verwalteter Server oder
  Webhook-Ziele, bleiben auch mit dem Schalter stehen. Ohne den Schalter bleiben Hostnamen und Adressen stehen wie
  bisher, damit Domain- und Zertifikatsfehler im Bundle zu sehen sind; Skript-Kopf, `--help`, die Abschlussmeldung
  und die Doku sagen das jetzt, statt das Bundle pauschal als unbedenklich fuer ein Issue zu bezeichnen. Doku:
  Troubleshooting (DE+EN), README.
- **Web-Panel: Abmeldung nach Inaktivitaet:** Das Web-Panel meldet in allen offenen Tabs ab, wenn in keinem davon
  30 Minuten lang bedient wurde (Maus, Tastatur, Touch); ein Hinweis bleibt stehen, bis man ihn schliesst. Die Dauer
  stellt die neue Env `WEB_IDLE_TIMEOUT_MINUTES` am Dienst `server` ein (`0` = aus, ein ungueltiger Wert gilt als 30),
  der Server liefert sie im neuen Feld `idle_timeout_minutes` von `GET /api/auth/me`. Das gilt auch nach Neuladen
  oder Wiederoeffnen im selben Browser: Liegt die letzte Bedienung dort laenger zurueck, endet die wiederhergestellte
  Sitzung beim Laden sofort mit demselben Hinweis. Doku: Benutzer & Zugriff, Installation, API-Referenz, Web-UI fuer
  Entwickler (DE+EN).

### Changed

- **Install/Update: Installationsverzeichnis 0750, Warnung bei belegter Container-UID:** `install.sh` und `update.sh`
  schliessen das Installationsverzeichnis fuer andere Konten (hoechstens `0750`, ein strengeres `0700` bleibt, Eigentuemer
  bleibt, wer installiert) und warnen, wenn ein Host-Konto die UID 10001 oder 70 traegt, die die Container nutzen;
  `update.sh --check` warnt, aendert aber nichts. Werkzeuge unter anderen Konten brauchen danach Gruppe oder root. Doku: Installation und
  Betrieb (DE+EN).
- **Web: der Cron-Hinweis im Hook-Dialog nennt UTC (R-0853):** Der Format-Hilfetext des Cron-Ausdrucks sagt jetzt
  „Zeiten in UTC“ (DE) bzw. „times in UTC“ (EN); der Scheduler rechnet Cron-Hooks in UTC (R-0756).
- **Desktop: verweigert der Server das Visitor-Bundle, stoppt der Tunnel (R-0453):** Antwortet der Server beim
  Abgleich mit 403, etwa nach Widerruf des Geraets oder Loeschen des Benutzers, stoppt der Desktop seinen Tunnel
  beim naechsten Abgleich wie bei 404, statt frpc mit der alten Konfiguration weiterlaufen zu lassen. Doku: Desktop
  fuer Entwickler (DE+EN).
- **Server-Log nennt bei weiteren Fehlern nur den Fehlertyp:** Scheitert das Entfernen der `frps.toml`, steht im
  Log der Fehlertyp ohne Traceback und ohne Fehlertext (R-0766). Die Warnungen des Redis-Rate-Limits nennen nur den
  Fehlertyp, und ein IPv6-Host steht im Log in eckigen Klammern (R-0776). Ein gescheiterter Start des SSE-Push und
  ein Loeschfehler der Bootstrap-Dateien nach dem ersten Admin stehen mit Fehlertyp, ohne Traceback, im Log (R-0776).
- **Desktop, Provisionierungs-Tab: der Einzeiler enthaelt den Token nicht mehr:** `agent-install.sh` fragt ihn beim
  Ausfuehren verdeckt ueber `/dev/tty` ab, der Tab zeigt ihn zum Kopieren daneben; so steht er weder in der
  Shell-History noch in der Prozessliste noch im sudo-Log (mit einem Agent, der `--token-stdin` kennt; aeltere bekommen
  ihn mit Warnung als Argument). Kopieren des Einzeilers blendet den Token nicht aus. Der Befehl "Nur provisionieren"
  behaelt `--token`. Doku: Agent-Deployment (DE+EN), README.
- **Server: Tokens nennen ihr Konto per ID:** Access- und Refresh-Token tragen zusaetzlich `uid` (`users.id`), und
  der Server ordnet jeden Token ueber diese ID seinem Konto zu, nicht mehr ueber den Benutzernamen. Tokens ohne `uid`
  gelten nicht mehr: nach dem Update melden sich Web und Desktop einmal neu an. Doku: Server-Entwicklerseite (DE+EN).
- **Agent: nach einem Update prueft der Agent die frpc-Konfiguration einmal neu:** Der erste Lauf nach einem
  Agent-Update holt die Konfiguration des Servers auch bei gleichem Hash und prueft sie; besteht sie, bleibt frpc
  unberuehrt, sonst stoppt der Agent frpc wie bei jeder abgelehnten Konfiguration. Neue Datei `/etc/frp/.checked-by`.
  Doku: Agent-Entwicklerseite (DE+EN).
- **Agent: ein abgelehnter frpc-Text stoppt frpc:** Weicht die frpc-Konfiguration des Servers von der Form ab, die
  der Generator schreibt, stoppt und deaktiviert der Agent frpc und loescht `frpc.toml` und Hash, statt frpc auf der
  alten Datei weiterlaufen zu lassen; der naechste Lauf holt und prueft erneut. Gilt fuer Abgleich und
  Provisionierung. Doku: Agent-Entwicklerseite, Agent-Verteilung (DE+EN).
- **Web-Panel: das Audit-Log zeigt die Spalte Detail:** Je Eintrag steht das Detail mit in der Tabelle, etwa die
  geaenderten Felder eines `user.updated`; bisher war es nur ueber `GET /api/audit` zu sehen. Doku: Betrieb (DE+EN).
- **Web-Panel: ein gescheitertes Kopieren meldet sich ueberall gleich:** Scheitert das Kopieren in die Zwischenablage,
  melden alle Dialoge des Web-Panels uebersetzt „Kopieren fehlgeschlagen“ statt „Clipboard error“ oder „Fehler“.
- **Entwicklung mit Claude Code: die Session baut selbst, ein Reviewer prueft Code und Tests:** Die Sub-Agenten
  `builder` und `tester` entfallen; die Session plant, implementiert und korrigiert jede Task selbst, `reviewer`
  prueft vor jedem Task-Commit und vor dem PR den ganzen Branch ueber Code und Tests (Abdeckung, echte Assertions,
  Fehlerpfade, hoechstens drei Gegenproben), `security` bleibt fuer Risikopfade, `advisor` hilft gezielt bei
  schwierigen Fragen. Session und Pruefer laufen auf Opus mit Effort high (nicht mehr xhigh); Sonnet gezielt per
  `claude --model sonnet`, xhigh per `advisor` oder `claude --effort xhigh`.
  `review.sh final` prueft das Branch-Urteil vor PR und Merge. `verify.sh` legt die volle Ausgabe unter
  `.ah-out/logs/` ab und zeigt einen Digest (`log-digest.sh`), `--full` streamt alles. Doku darf in einer Doku-Task
  desselben Ledgers gebuendelt werden und ist vor der Abschlusspruefung DE+EN vollstaendig. Doku: CI/CD fuer
  Entwickler (DE+EN), DEVELOPMENT.md.
- **Desktop: „Gepinntes Zertifikat zuruecksetzen“ in den Einstellungen fragt vorher nach:** Der Knopf zeigt vor dem
  Zuruecksetzen dieselbe Warnung wie der Anmeldebildschirm und setzt den Pin erst nach der Bestaetigung zurueck;
  Abbrechen laesst den Pin stehen. Doku: Desktop fuer Entwickler, Troubleshooting (DE+EN).
- **Web: Stores halten nach dem Anlegen nur die Felder der Liste:** Webhook-Token und Skript eines neuen oder
  bearbeiteten Hooks sowie Auth-Token und Dashboard-Passwort einer neuen FRP-Server-Konfiguration bleiben nicht bis
  zum Neuladen im Speicher der Seite; der Webhook-Token wird wie bisher einmal angezeigt. Doku: Web-UI fuer
  Entwickler (DE+EN).
- **Web: FRP-Konfigurationsvorschau wird beim Schliessen geleert:** Der Text von `frps.toml` bzw. `visitor.toml`
  (mit Auth-Token, Dashboard-Passwort bzw. STCP-Schluesseln) bleibt nach dem Schliessen der Vorschau nicht mehr bis
  zum Verlassen der FRP-Seite im Speicher der Seite.
- **Images server, ca-issuer und monitoring: Programme nur ausfuehrbar:** In den Images von server und scheduler,
  ca-issuer und monitoring gehoeren die Programme unter `/usr/local/bin`, `/usr/local/sbin`, `/usr/bin`, `/usr/sbin`
  und, in server, scheduler und monitoring, die PostgreSQL-Clientprogramme unter `/usr/lib/postgresql` (jede
  ELF-Datei mit x-Bit) root und sind fuer alle anderen nur noch ausfuehrbar (`chmod go-r`: aus `0755` wird `0711`,
  Eigentuemer und setuid-Bits bleiben), wie im frps-Image `frps` und `curl`. Prozesse des Nutzers `app` (UID 10001),
  die der Entrypoint ueber `gosu` startet, sind damit nicht dumpable: Ihre Eintraege unter `/proc/<pid>` gehoeren
  root. Skripte und Symlinks bleiben, wie sie sind; es zaehlt das Programm, das ein Skript ausfuehrt (`python3.12`,
  `dash`, `perl`). Als `app` kann `pg_isready` sein eigenes Programm nicht mehr lesen, schreibt
  `invalid binary "…": Permission denied` auf stderr und laeuft weiter; die Entrypoints leiten das nach `/dev/null`.
  `psql` bricht in dieser Lage ab, daher prueft monitoring beim Start seine Datenbank und legt sie an ueber Python
  (`psycopg`) statt ueber `psql`. Als root, etwa per `docker compose exec`, laufen beide wie bisher. Der Schritt ist
  der letzte `RUN` jedes der drei Images und erfasst so alles, was die Schritte darueber installieren. Die UID 10001
  sollte auf dem Host keinem anderen Konto oder Dienst gehoeren. Doku: Betrieb (DE+EN).
- **Hooks: Ablehnungen von `http_get`/`http_post` nennen nur den Hostnamen des Ziels:** Lehnt der SSRF-Schutz ein
  Ziel ab, nennt der Text des `ValueError` (und damit `error` und `logs` eines Laufs, der ihn nicht faengt) vom
  Ziel nur den Hostnamen, ohne Port, Pfad, Query und Zugangsdaten, wie die Log-Zeilen des Alert-Webhooks; hat die
  URL keinen lesbaren Host, steht dort `?`. Typ und Anfang der Texte bleiben. Doku: Hook-Entwicklerdoku (DE+EN).
- **Roadmap ohne `neu`-Deckel (Entwickler-Werkzeuge, Kevin 2026-10-22):** `roadmap.py add` nimmt jede neue Zeile an,
  auch wenn schon 20 oder mehr Zeilen `neu` sind; Exit 3 gibt es nicht mehr. `neu N/20` im WIP-Kopf bleibt Anzeige
  wie `aktiv N/2`. Der Wochenlauf (`heavy.sh`) laesst einen bestaetigten Fund damit nicht mehr ohne Roadmap-Zeile,
  die Notiz `ROADMAP FULL` im Report entfaellt. Anleitung: `DEVELOPMENT.md`, „Die Roadmap als Skript: `roadmap.py`",
  und der Skill `/roadmap`.
- **Sammellauf auf zwei Boxen parallel (R-0603):** `heavy.sh all` faehrt `run.sh all --strict` jetzt als zwei Teile
  gleichzeitig: Teil `rest` auf der warmen Box des Slots `desktop`, Teil `gui` (die Desktop-GUI-E2E samt Smoke-Test,
  `--part gui`) auf einer zweiten Box derselben Lane (`warm.sh gui`, `iter.sh --slot gui`), die geleast wird,
  waehrend `rest` schon laeuft. Ist die zweite Box auch im zweiten Versuch nicht zu bekommen, laeuft Teil `gui` nach
  Teil `rest` seriell auf der Box `desktop`, und die Notizen sagen es mit der letzten Zeile aus `warm-gui.log`; nur
  wenn `warm.sh gui` verweigert (Exit 2), bleibt der Lauf `UNVERIFIED`. Der Pre-flight fragt `vm.py doctor` deshalb
  nur nach dem Slot `desktop`, wenn seine Box nicht schon laeuft; ob die GUI-Box passt, entscheidet `vm.py clone`.
  Das Urteil heisst `PASS` nur mit zwei gruenen Teilen; ein Teil, der nicht lief oder keinen eigenen Beleg brachte
  (weder Summary-Zeile noch Artefakt, oder ein Artefakt des anderen Teils), macht den Lauf `UNVERIFIED`, und der
  Grund nennt den Teil und einen roten anderen Teil („FAIL in part rest“). Rote Schritte werden auf der Box ihres
  Teils wiederholt. Der Report setzt das Etikett des Teils vor seine Summary-Zeile (`[rest] run.sh[all]: …`), fuehrt
  die Schritte beider Teile mit Sekunden und Box und **eine** Ebenen-Zeile mit Wandzeit, beiden Boxen
  (`<box-rest>+<box-gui>`) und den Sekunden je Teil; `steps-all.tsv` nennt den Teil in einer vierten Spalte, jeder
  Teil hat sein Log (`all-rest.log`, `all-gui.log`) und sein Zieh-Verzeichnis, die JUnit-XML beider Teile liegen in
  `junit/`. `history.csv` behaelt ihr Format. Ein Abbruch von `heavy.sh` (INT/TERM/HUP) beendet beide Teile. Nach
  dem Lauf gibt `heavy.sh` die GUI-Box frei, wenn Teil `gui` gruen ist; nach einem roten Teil `gui` bleibt sie zur
  Sichtung stehen, bis ihre Frist ablaeuft, und die Notizen nennen `vm.py ssh <vmid>`. Doku: DEVELOPMENT, CI/CD fuer
  Entwickler (DE+EN), `/test`-Skill.
- **Desktop, Provisionierungs-Tab: Format und Quoting im erzeugten Befehl:** Token und Server-ID aus der Serverantwort
  werden auf ihr Format geprueft (Token aus Buchstaben, Ziffern, `_` und `-`, Server-ID als UUID); passt eins nicht,
  erscheint statt der Befehle eine Meldung, und die Token-Liste wird trotzdem neu geladen. Werte mit Sonderzeichen
  stehen im erzeugten Befehl in einfachen Anfuehrungszeichen; die vom Server erzeugten Werte sehen aus wie bisher.
- **Desktop: Sync nur aus der Quelle des eigenen Sync-Workspace:** Der Sync laedt nur im Sync-Workspace und nur
  dessen gespeicherte Sync-URL, nie mit dem Geraete-Zertifikat. Eine andere URL, auch desselben Servers, lehnt er ab;
  die Meldung nennt keine URL. Doku: Desktop fuer Entwickler (DE+EN).
- **Desktop: Ansible-Lauf in einem Command:** Ein Ansible-Lauf laedt Dateiname und Inhalt des Playbooks im Backend
  selbst vom angemeldeten Server; die Oberflaeche uebergibt nur die Playbook-Id und die Ziele. Die Tauri-Commands
  `ansible_generate_inventory`, `ansible_write_playbook` und `ansible_launch` sind durch `ansible_run` ersetzt;
  scheitert ein Schritt vor dem Start, loescht der Lauf die schon geschriebenen Temp-Dateien. Doku: Desktop fuer
  Entwickler, Ansible (DE+EN).
- **Agent: `provision` und `monitor init` nehmen je Aufruf genau eine Vertrauensquelle:** Beide lehnen `--cacert`
  zusammen mit `--insecure` ab, wie `provision` schon `--ca-fp` mit einem der beiden; `--cacert` prueft den Server
  bereits. Der Aufruf scheitert, bevor er etwas schreibt oder (bei `provision`) den Einmal-Token sendet, und die
  Meldung nennt beide Flags. Legt der Server bei `--insecure` kein Zertifikat zum Pinnen vor, bricht `provision` ab,
  statt ohne Pruefung weiterzumachen; `monitor init` bricht ebenso ab, wenn es das Zertifikat nicht holen oder
  speichern kann, und schreibt nie `INSECURE=1` in `monitor.conf`. `--insecure` gilt so nur fuer den einen Aufruf.
  Doku: Agent-Deployment (DE+EN).
- **Agent: `diagnostics` legt jeden Bericht als neue Datei an:** Der Bericht heisst
  `adminhelper-agent-diagnostics-<Zeitstempel>-<Zufall>.txt`, liegt wie bisher im Temp-Verzeichnis und hat die Rechte
  0600; eine vorhandene Datei ueberschreibt `diagnostics` nie. Den Pfad gibt der Befehl wie bisher aus.
- **Agent: die frpc.toml des Servers nur in der Form, die der Server erzeugt:** Der Agent wendet eine frpc.toml des
  Servers nur an, wenn jede Zeile die Form des Generators hat: leer, `[transport.tls]`, `[[proxies]]` oder
  `schluessel = wert` mit einem einzeiligen Wert. In der Wurzel nimmt er nur die Schluessel, die der Server schreibt,
  in einem Proxy keinen Schluessel, dessen erstes Segment `plugin` ist, gleich ob gross oder klein geschrieben
  (Proxy-Plugins richtet der Server nicht ein; einen solchen `extra_config`-Schluessel eines Tunnels lehnt der Server
  mit `422` ab), kein Schluessel steht in einer Tabelle zweimal, und der Text enthaelt kein `{{`. Einen anderen Text
  wendet er nicht an: Er meldet einen Fehler mit Zeile und Schluessel (nie den Wert), schreibt und startet nichts, und
  der naechste Lauf versucht es erneut. Doku: Agent-Entwicklerseite und API-Referenz (DE+EN).
- **Agent: nur die Einrichtung schaltet `adminhelper-agent.timer` ein (R-0641):** Ein Agent-Lauf schaltet den Timer
  nicht mehr ein. Bisher tat das der FRP-Abgleich bei jedem Einschalten von frpc, auch im Dauerbetrieb `run` ohne
  `--once`, der dann neben dem Timer lief. Den Timer schalten jetzt `provision`, `monitor init` und `service install`
  ein, mit einem Deckel von 30 s; `provision` immer, am Ende, auch ohne Monitor und ohne Tunnel (bisher nur mit
  Monitor oder wenn es frpc einschaltete). Scheitert das, melden `provision` und `monitor init` es und gelingen
  trotzdem. Doku: Agent fuer Entwickler (DE+EN).
- **Agent: `provision --ca-fp` prueft auch den Hostnamen (R-0639):** Nennt das Zertifikat des Gateways den Host aus
  `--url` nicht, bricht `provision --ca-fp` jetzt ab, bevor der Einmal-Token den Host verlaesst; die Meldung nennt den
  Host und die Namen des Zertifikats. Bisher nahm der Erstkontakt das Zertifikat an, loeste den Token ein und meldete
  „OK: Provisioning abgeschlossen.“, danach scheiterte jeder Lauf an der Hostnamen-Pruefung. Das betrifft auch Befehle
  aus dem Provisionierungs-Tab eines Desktops, der ueber eine IP-Adresse verbunden ist, die das Zertifikat nicht nennt
  (eine IP-Adresse nennt es nur, wenn sie beim Ausstellen in `EXTRA_SANS` des Servers stand). Doku: Agent-Deployment
  (DE+EN).
- **Server: der Startabgleich der `frps.toml` loggt einen Fehler nur mit seinem Typ:** Scheitert beim Start der
  Abgleich der `frps.toml` mit der Datenbank (Konfiguration lesen oder Datei schreiben), schreibt der
  Server eine Warnung mit dem Fehlertyp, ohne Fehlertext und ohne Traceback, wie die uebrigen Startpruefungen der
  FRP-Server-Konfiguration. Bisher stand der Fehler samt Traceback im Log.
- **Server: `.secret_key`, `.bootstrap_token` und `.bootstrap_setup` entstehen von Anfang an mit Modus 0600:** Den
  selbst erzeugten Schluessel (kein `SECRET_KEY` gesetzt), den Hash des Setup-Tokens und den Setup-Token schreibt der
  Server je in eine temporaere Datei im selben Verzeichnis, die von Anfang an nur fuer ihren Besitzer lesbar ist, und
  benennt sie danach atomar um, wie die `frps.toml`. Bisher entstanden die Dateien mit den Rechten der umask und
  bekamen erst danach Modus 0600. Ein Fehler beim Entfernen der Bootstrap-Dateien steht mit Dateiname und Fehlertyp im
  Log; bisher wurde er verworfen.
- **Server: die Log-Zeilen zum Redis-Backend des Rate-Limits nennen nur Schema, Host und Port:** Von `REDIS_URL`
  nennen sie nur Schema, Host und Port (bei `unix://` den Socket-Pfad), von einem Verbindungsfehler nur den Typ, wie
  die Log-Zeilen des Alert-Webhooks. Bisher standen die ganze URL und der Fehlertext im Log.
- **Server: `POST /api/internal/events` lehnt die Quelltypen `frp_config` und `frps` ab:** Ein Event mit
  `source_type` `frp_config` oder `frps` ergibt `422` an `source_type`; nichts wird geschrieben. Unter diesen
  Quelltypen fuehrt der Server seine eigenen Meldungen. Der Monitoring-Dienst sendet `server` und ist nicht betroffen.
- **Desktop, Ansible: Inventory und Playbook eines Laufs in einem eigenen Verzeichnis:** Beide liegen je Lauf in einem
  eigenen, frisch angelegten Verzeichnis `adminhelper_ansible_<pid>_<n>_<zeit>` im Temp-Verzeichnis, unter Linux und
  macOS nur fuer den eigenen Nutzer lesbar (Modus 0700); neben ihnen liegt nur, was der Lauf schreibt. Scheitert ein
  Schritt vor dem Start, entfernt der Desktop das ganze Verzeichnis, auch eine halb geschriebene Datei; unter Linux
  entfernt das Terminal es nach dem Lauf. Doku: Desktop fuer Entwickler, Ansible (DE+EN).
- **Desktop, Ansible: Playbook-Dateiname nur aus sicheren Zeichen, Server-Antwort hoechstens 16 MiB:** Der Dateiname
  des Playbooks behaelt nur ASCII-Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich, andere Zeichen werden zu
  Unterstrichen (unter Windows geht der Pfad an Windows Terminal und `cmd`). Die Antwort des Servers auf den
  Playbook-Abruf liest der Desktop hoechstens 16 MiB weit; eine groessere oder eine, die kein Playbook ist, bricht den
  Lauf mit einem Fehler ab, der die Antwort nicht zitiert.
- **Audit-Log: Hooks, Provisionierungs-Token und Monitoring-Proxy:** Das Audit-Log erfasst jetzt die Aktionen der
  Admins an Hooks (`hook.created`, `hook.updated` mit den geaenderten Feldern in `detail`, auch fuer das Ein- und
  Ausschalten, `hook.deleted`, `hook.token_rotated`, `hook.run` mit `success` oder `failure`), das Erzeugen eines
  Provisionierungs-Tokens (`provision.token.minted` mit dem Server als Objekt) und Schreibzugriffe ueber den
  Monitoring-Proxy (`monitoring.post`, `monitoring.put`, `monitoring.delete` mit dem weitergeleiteten Pfad und
  `status=<HTTP-Status>` in `detail`; bricht die Weiterleitung nach dem Senden ab, Status `error` mit dem Typ des
  Fehlers). Kein Token, kein Skript, kein Fehlertext eines Laufs und kein Inhalt einer Anfrage steht im Eintrag; der
  Webhook-Trigger und lesende Zugriffe schreiben nichts. `user.updated` nennt in `detail` die geaenderten Felder
  (`password`, `is_admin=true|false`, `server_ids`). Routen und Antworten bleiben gleich. Doku: Betrieb (DE+EN),
  API-Referenz fuer Entwickler (DE+EN).
- **`python -m app.cli create-admin` feuert `user.created` wie die API:** Dieselbe Payload wie `POST /api/users`
  (`id`, `username`, `is_admin: true`), damit erreichen Event-Hooks und die Glocke („Sicherheit“) auch diesen Weg; auf
  einer frischen Installation meldet die Glocke dem ersten Admin so seine eigene Anlage. Doku: Monitoring (DE+EN),
  Hooks fuer Entwickler (DE+EN).
- **Monitoring: SMART-Serien kommen nur noch vom Check `smart_health` (R-0633):** Der Agent-Push schreibt keine
  eigenen SMART-Serien (`monitor_smart_temp_<Geraet>`, `monitor_smart_reallocated_...`, `monitor_smart_pending_...`)
  mehr nach VictoriaMetrics; diese Werte schreibt allein der Check `smart_health` mit seinen Check-Labels. Die
  bisherigen Serien des Pushs mit nur `server_id` und `device` las keine Ansicht; sie bleiben bis zum Ende der
  Retention in VictoriaMetrics. `metricsWritten` in der Antwort des Pushs zaehlt sie nicht mehr. Doku: Monitoring fuer
  Entwickler (DE+EN).
- **`agent-install.sh` installiert nur den gepinnten Repo-Schluessel:** Das Skript importiert die vom Server geladene
  Keyring-Datei in ein eigenes, temporaeres GnuPG-Verzeichnis, exportiert daraus nur den Schluessel, dessen
  Primaer-Fingerprint der Pin ist, und installiert diesen Export als `Signed-By` (apt) bzw. `gpgkey` (dnf), egal an
  welcher Stelle der Schluessel in der Datei steht; bisher brach die Installation ab, wenn er nicht an erster Stelle
  stand. Fehlt er, bricht es ab, bevor
  eine Paketquelle geschrieben wird, und nennt den erwarteten und die gefundenen Fingerprints; der Fingerprint eines
  Unterschluessels gilt nicht als Pin. `--gpg-fp` muss aus 40 Hex-Zeichen bestehen. Bestehende Agent-Hosts behalten
  ihren Keyring, bis `agent-install.sh` dort wieder laeuft.
- **`agent-install.sh` gibt den Provisionierungs-Token ueber stdin an den Agent:** Bisher las das Skript den Token
  zwar auf Wunsch von `/dev/tty`, reichte ihn dann aber als `--token` an `adminhelper-agent provision` weiter, wo er
  fuer die Dauer des Aufrufs in der Prozessliste stand. Kennt der installierte Agent `--token-stdin`, schreibt das
  Skript den Token jetzt in dessen stdin. Ein aelterer Agent (aus dem Repo eines noch nicht aktualisierten Servers)
  bekommt ihn wie bisher als `--token`, und das Skript warnt, dass der Token dabei als Programmargument uebergeben wird.
- **`update.sh` prueft in der `.env` auch Anfuehrungszeichen und Schluessel:** Die Pruefung vor dem ersten
  `docker compose`-Aufruf erkannte nur ein `${` ohne gueltigen Platzhalter. Ein nie geschlossenes Anfuehrungszeichen
  und ein Schluessel, den Compose nicht annimmt (auch Text direkt hinter einem schliessenden Anfuehrungszeichen, den
  Compose als naechsten Schluessel liest, oder ein Schluessel mit Leerzeichen), liess sie durch; Compose brach dann
  jeden Aufruf ab, erst nach Backup und Tausch. Jetzt endet `update.sh` in
  diesen Faellen vorher, ohne etwas zu aendern, auch bei `--check` und `--redeploy`, und nennt den Schluessel des
  Werts oder die Zeilennummer, nie Wert oder Zeile. Ein BOM am Anfang der `.env` nimmt die Pruefung wie Compose an.
  Doku: Installation (DE+EN).
- **Server: das `extra_config` eines FRP-Tunnels nimmt keinen Schluessel der plugin-Familie an:** Ein Schluessel im
  `extra_config` eines FRP-Tunnels, dessen erstes Segment `plugin` ist, gleich ob gross oder klein geschrieben (etwa
  `plugin.type` oder `PLUGIN.type`), ergibt bei `POST /api/frp/tunnels` und `PUT /api/frp/tunnels/{id}` jetzt `422`;
  bisher speicherte der Server ihn. Proxy-Plugins richtet der Server nicht ein, und der Agent wendet eine frpc.toml
  mit einem solchen Schluessel nicht an. Gespeicherte Eintraege bleiben, wie sie sind. Doku: API-Referenz (DE+EN).
- **Server: ein gespeicherter FRP-Tunnel, dessen `extra_config` die API heute ablehnt, fehlt in der frpc.toml seines
  Hosts:** Ein Tunnel, dessen gespeichertes `extra_config` einen Schluessel der plugin-Familie oder einen anderen
  Eintrag traegt, den die API heute ablehnt (oder kein JSON-Objekt ist), steht nicht mehr in der frpc.toml seines
  Hosts; der Server schreibt dazu eine WARNING mit Tunnelname und den betroffenen Schluesseln (nie den Werten) ins
  Log. Eine solche Zeile ergaebe sonst eine frpc.toml, die fuer den ganzen Host nicht gilt; die uebrigen Tunnel des
  Hosts bleiben. `GET /api/frp/generate/frpc-toml/{server_id}` antwortet `404`, wenn kein anderer Tunnel bleibt, und
  das Bulk-ZIP enthaelt dann keine `frpc.toml` fuer den Host. Die Zeile in der Datenbank bleibt, wie sie ist. Doku:
  API-Referenz, Server-Entwicklerseite (DE+EN).
- **Hooks: Worker laedt keine Python-Pakete aus dem Benutzerverzeichnis:** Der Hook-Worker startet mit `python -s`
  und bekommt `PYTHONNOUSERSITE=1`; weder er noch Python-Prozesse, die ein Skript startet, nehmen
  `$HOME/.local/lib/python3.X/site-packages` (samt `usercustomize`) auf, auch nicht beim Rueckfall `HOME=/tmp`.
  Pakete fuer Hooks gehoeren ins Image. Doku: Hook-Entwicklerdoku (DE+EN).
- **Hooks: Webhook-Trigger prueft seinen JSON-Body wie jeder andere Request-Body:** Ein NUL-Byte oder ein einzelnes
  Surrogat (U+D800 bis U+DFFF; JSON schreibt beide nur als Escape) in einem String oder Schluessel des Bodys von
  `POST /api/hooks/trigger` und `/api/hooks/trigger/{token}` ergibt `422` mit dem Ort im `loc`, statt das Skript damit
  zu starten; bisher endete die Antwort mit 500, sobald das Skript den Wert zurueckgab, und ein Skript, das ihn
  speicherte, scheiterte an der Datenbank. Rate-Limit, Token und Aktiv-Status werden weiter vorher geprueft; ein Body,
  der kein JSON ist, kommt wie bisher als leeres `payload` an. Doku: API-Referenz fuer Entwickler (DE+EN).
- **`create-admin --password` gibt das Passwort vor dem Anlegen ueber stdin an einen frischen Prozess weiter:**
  `python -m app.cli create-admin --password …` ersetzt sich vor dem Anlegen des Benutzers per `exec` durch
  `create-admin --password-stdin` und legt das Passwort dafuer auf stdin; Hooks auf `user.created` laufen so in einem
  Prozess, dessen Kommandozeile das Passwort nicht traegt. Bis zum Neustart steht es dort weiter, Interpreter-Optionen
  des ersten Aufrufs (`python -X …`) gelten danach nicht mehr, und Meldungen, die der Server beim Laden seiner
  Konfiguration auf stderr schreibt, erscheinen zweimal. Ein Passwort mit Zeilenumbruch (das `--password-stdin`
  nie annehmen konnte) oder eines, das samt Zeilenumbruch nicht in den Puffer einer Pipe passt (unter Linux meist
  64 KiB), lehnt `--password` mit Exit 2 ab. Empfohlen bleibt `--password-stdin`. Doku: README.
- **Compose: alle Dienste mit no-new-privileges und Prozessgrenze:** Jeder Dienst in `docker-compose.yml` laeuft mit
  `no-new-privileges` (bisher nur frps) und hat eine Prozessgrenze (`pids_limit`, Prozesse und Threads): server 4096;
  scheduler, monitoring und victoria 1024; postgres, gateway, ca-issuer und frps 512; redis 256. Der Dienst monitoring
  setzt `net.ipv4.ping_group_range` selbst, damit der Ping-Check ohne Sonderrechte laeuft. Eine Grenze hebt man per
  `docker-compose.override.yml` an, die `update.sh` stehen laesst; wer `WEB_CONCURRENCY` stark erhoeht, prueft die
  Grenze des server. Doku: Betrieb (DE+EN).
- **Compose: Speichergrenze je Dienst:** Jeder Dienst in `docker-compose.yml` hat eine Speichergrenze (`mem_limit`):
  postgres und victoria 8 GiB, server 6 GiB, monitoring 4 GiB, scheduler und frps 2 GiB, gateway 1 GiB, ca-issuer und
  redis 512 MiB. Die Grenzen liegen weit ueber dem Bedarf im Leerlauf und reservieren keinen Speicher; ist eine
  erreicht, lagert der Kernel auf einem Host mit Swap bis zur selben Menge aus und beendet danach einen Prozess in
  diesem Container, der Host und die uebrigen Dienste bleiben unberuehrt. VictoriaMetrics legt seine Caches auf 60
  Prozent des Speichers aus, den es sieht: liegt die Grenze unter dem Arbeitsspeicher des Hosts, sind es 60 Prozent
  der Grenze, sonst 60 Prozent des Arbeitsspeichers. Eine Grenze hebt man per
  `docker-compose.override.yml` an. Doku: Betrieb (DE+EN).
- **Compose: Gateway nur mit den Capabilities, die nginx braucht:** Der Dienst gateway laeuft mit `cap_drop: [ALL]`
  und behaelt nur `CHOWN`, `DAC_OVERRIDE`, `SETGID` und `SETUID`, die der nginx-Master zum Start braucht; die Worker
  laufen als Nutzer `nginx` ohne Capabilities. Wie bei frps setzt Compose `net.ipv4.ip_unprivileged_port_start` auf 0,
  damit nginx die Ports 443, 8444 und 8445 ohne `NET_BIND_SERVICE` oeffnet. Doku: Betrieb (DE+EN).
- **Gateway: Verbindungsgrenzen und kurze Timeouts auf den certless Ebenen:** Auf :8444 (Enrollment) und :8445
  (Paket-Repo) beantwortet das Gateway mehr als 16 bzw. 64 gleichzeitige Anfragen je Client-Adresse und mehr als 128
  bzw. 256 je Ebene mit 429. Dort schliesst es eine Verbindung, deren Anfrage-Kopf nicht binnen 10 s ankommt oder deren
  Body laenger als 10 s stockt, und untaetige Keep-Alive-Verbindungen nach 15 s (bisher 60 s bzw. 75 s). Die
  Daten-Plane :443 bleibt unveraendert. Doku: Betrieb (DE+EN).
- **Compose: Netz frpedge ohne IP-Masquerading:** Das Netz `frpedge`, in dem frps allein haengt, legt Compose ohne
  IP-Masquerading an: frps baut keine Verbindungen ueber den Host hinaus auf, seine veroeffentlichten Ports bleiben
  erreichbar. Die Betriebs-Doku nennt, was bleibt (Pakete ohne Antwort, Dienste des Hosts selbst), und zeigt eine
  optionale Regel in der Kette `DOCKER-USER`. Die Doku der Netze nennt Postgres neben Gateway und ca-issuer im Netz
  `pki`. Doku: Betrieb, Entwicklung (DE+EN).
- **Compose: CA-Root-Passphrase als Secret statt Umgebungsvariable:** Der ca-issuer bekommt `CA_ROOT_PASSPHRASE`
  als Compose-Secret, eine Datei unter `/run/secrets`, und nicht mehr als Umgebungsvariable; damit steht sie nicht
  mehr in der Umgebung des Containers (`docker inspect`, `/proc/<pid>/environ`). Compose liest den Wert weiter aus
  `CA_ROOT_PASSPHRASE` in der `.env` und setzt `CA_ROOT_PASSPHRASE_FILE` selbst. Nach dem ersten Start darf der Wert
  leer sein; danach erzeugt `docker compose up -d` den ca-issuer neu, und die Datei verschwindet (ein Label des
  Dienstes traegt, ob ein Wert gesetzt ist, nie den Wert). Die Zeile `CA_ROOT_PASSPHRASE=` muss bleiben: fehlt sie,
  bricht `docker compose up` ab. Voraussetzung ist Docker Compose v2.6 oder neuer. Doku: Installation (DE+EN).
- **init-secrets.sh: CA-Root-Passphrase nur bei frischer Installation:** `scripts/init-secrets.sh` erzeugt
  `CA_ROOT_PASSPHRASE` nur noch in dem Lauf, der auch `POSTGRES_PASSWORD` erzeugt, also bei einer frischen
  Installation. Bisher fuellte das naechste Update (`update.sh` ruft das Skript auf) einen geleerten Wert mit einer
  neuen Passphrase, die nicht zum vorhandenen Root-Key passte. Ist `POSTGRES_PASSWORD` gesetzt, bleibt ein leerer Wert
  leer, und das Skript sagt es in einer Zeile. Wer `POSTGRES_PASSWORD` vor der Installation von Hand setzt, setzt auch
  `CA_ROOT_PASSPHRASE` von Hand, sonst bricht der erste Start des ca-issuer ab. `restore.sh` sagt, dass `.env.restored`
  die Zeile `CA_ROOT_PASSPHRASE=` braucht, bevor sie die `.env` ersetzt. Doku: Betrieb (DE+EN).
- **Server und Compose: Client-Adresse hinter dem Gateway:** Compose setzt `TRUSTED_PROXIES` beim server auf den
  Dienst `gateway`, gefolgt von einem Wert aus der `.env`; `TRUSTED_PROXIES` nimmt dafuer neben Adressen und Netzen
  auch Hostnamen, die der Server alle 30 s neu aufloest. Hinter dem Gateway beziehen sich damit die Ratenlimits je
  Adresse (Login, Webhook-Trigger, Agent-Reports), `ALLOWED_IPS` und die Adresse im Audit-Log auf den Client statt auf
  das Gateway. Forwarded-Header anderer Gegenstellen wertet der Server weiterhin nicht aus, und `TRUST_PROXY_HEADERS`
  wirkt unter Compose nicht mehr. Wer `ALLOWED_IPS` gesetzt hat, prueft vor dem Update, dass die Netze der Clients
  enthalten sind: Bisher pruefte der Server die Adresse des Gateways, danach weist er Clients ausserhalb der Liste mit
  403 ab. Steht ein weiterer Proxy vor dem Gateway, sieht der Server dessen Adresse; ein Eintrag in `TRUSTED_PROXIES`
  aendert daran nichts. Doku: Installation, Benutzer (DE+EN).
- **Web: Hinweisseite fuer Benutzer ohne Admin-Rechte (R-0721):** Benutzer ohne Admin-Rechte sehen im Web-Panel
  einen uebersetzten Hinweis, dass das Panel Admins vorbehalten ist und der Desktop-Client der Weg ist (DE „Web-Panel
  nur fuer Admins“, EN „Web panel for admins only“), statt der alten Platzhalterseite „Nicht verfuegbar“. Doku:
  Admin-Handbuch, Benutzer (DE+EN).
- **Web: Seite „nicht gefunden“ fuer Admins (R-0721):** Eine unbekannte Adresse im Web-Panel zeigt Admins eine
  uebersetzte Seite „nicht gefunden“ (DE „Seite nicht gefunden“, EN „Page not found“) mit Link zur
  Benutzerverwaltung, statt der alten Platzhalterseite „Nicht verfuegbar“.
- **Monitoring: E-Mail-Alert-Regeln mit eigenem `smtp_host` melden sich nur mit eigenen Zugangsdaten an:**
  `SMTP_USER` und `SMTP_PASSWORD` gelten nur fuer den Relay aus `SMTP_HOST` (Vergleich ohne Gross-/Kleinschreibung).
  Eine Regel, die einen anderen `smtp_host` setzt, meldet sich nur mit ihren eigenen `smtp_user` und `smtp_password`
  an; fehlt eins davon, verschickt sie ohne Anmeldung. Verlangt ihr Relay eine Anmeldung, steht im Alert-Log dann
  `SMTP server refused the message`; Abhilfe sind eigene `smtp_user` und `smtp_password` in der Regel. Regeln ohne
  `smtp_host` oder mit dem Host aus `SMTP_HOST` verhalten sich wie bisher. Doku: Monitoring (DE+EN).
- **Monitoring: Template-Antworten zeigen ein `smtp_password` in Alert-Definitionen als `***`, wie die
  Alert-Regeln:** Das gilt fuer `GET /templates`, `GET /templates/{id}`, die Antworten von `POST`/`PUT /templates` und
  von `POST /templates/{id}/builtin-update` sowie fuer `current` in `GET /templates/{id}/builtin-update`. Ein
  `PUT /templates/{id}` mit `***`, leerem oder fehlendem `smtp_password` behaelt das gespeicherte Passwort der
  Definition mit derselben `def_id` (wie `PUT /alerts/{id}`); eine neue Definition speichert dann keins, ebenso
  `POST /templates` mit `***` oder leerem Wert. Wer ein Template aus einer API-Antwort neu anlegt, gibt das Passwort im
  `POST` neu ein.
- **Monitoring: Beim Bearbeiten von E-Mail-Alert-Regeln und Alert-Definitionen von Templates gilt `***` nur bei
  unveraendertem `smtp_host`/`smtp_port` als „Passwort unveraendert“:** Ein `PUT /alerts/{id}` oder
  `PUT /templates/{id}` mit `***`, leerem oder fehlendem `smtp_password` behaelt das gespeicherte Passwort nur, solange
  `smtp_host` (ohne Gross-/Kleinschreibung) und `smtp_port` gleich bleiben. Aendert derselbe Aufruf den Relay, lehnt
  er `***` mit 422 ab und speichert nichts; ohne Passwort entfaellt das gespeicherte. Nach einem Relay-Wechsel ist das
  Passwort neu einzugeben. Doku: Monitoring (DE+EN).
- **Notification-Hub: E-Mails nutzen STARTTLS auf jedem Port ausser 465 und pruefen Zertifikat und Hostnamen des
  Relays, wie der E-Mail-Kanal des Monitorings:** Ein Relay ohne STARTTLS (etwa ein lokaler Mailserver auf Port 25)
  oder mit einem Zertifikat, dem der Container nicht vertraut oder das nicht zu `SMTP_HOST` passt, nimmt danach keine
  Hub-Mails mehr an: Die Outbox wiederholt bis `NOTIFICATION_MAX_ATTEMPTS` und markiert die Mail dann als
  fehlgeschlagen, der Grund steht im Log des `scheduler`-Dienstes; Glocke und Desktop-Hinweise bleiben. Abhilfe:
  `SMTP_HOST` auf den Namen im Zertifikat des Relays setzen, fuer eine eigene CA `SMTP_CA_FILE` (siehe Added); der
  Relay muss STARTTLS oder implizites TLS auf Port 465 anbieten. Doku: Betrieb & Konfiguration (DE+EN).
- **Backup: Archiv von Anfang an privat und erst vollstaendig unter seinem Namen:** `scripts/backup.sh` schreibt das
  Archiv in eine versteckte Zwischendatei im Zielordner, die von Anfang an den Modus 0600 hat, bringt ihre Daten mit
  `sync` (nur diese Datei) auf die Platte und benennt sie erst danach in `adminhelper-backup-<ts>.tar.gz` um; danach
  synchronisiert es den Zielordner. So zeigt der Name auch nach einem Stromausfall nicht auf eine leere oder
  gekuerzte Datei. Ein Lauf, der bis zum Umbenennen scheitert, hinterlaesst weder ein Archiv noch eine Zwischendatei;
  scheitert das `sync` des Zielordners, endet das Backup mit Fehler, das Archiv bleibt liegen. Liegt unter dem
  Archivnamen schon ein Verzeichnis, bricht das Backup ab, statt das Archiv hineinzulegen; ein Symlink unter dem Namen
  wird durch das Archiv ersetzt, sein Ziel bleibt unberuehrt. Einen neu angelegten Zielordner legt das Skript mit
  0700 an, ein bestehender bleibt, wie er ist. Wer Backups mit einem anderen Nutzer abholt, gibt den Ordner selbst
  frei. Das Archiv wird nur in die Zwischendatei geschrieben, die das Skript selbst angelegt hat, und bleibt auch in
  einem Ordner mit Default-ACL 0600; liegt unter ihrem Namen etwas anderes (etwa ein Link), oder kann das Ziel keinen
  Unix-Eigentuemer und -Modus halten (wie ein CIFS-, vfat- oder NTFS-Mount in der Regel), bricht das Backup mit einem Hinweis ab: lokal
  sichern und das Archiv danach kopieren. `scripts/backup.sh --help` zeigt nur die Hilfe. Doku: Betrieb (DE+EN).
- **ca-issuer: Zertifikatskette aus den geprueften Zertifikaten (R-0666):** Die Kette eines Zwischenzertifikats, die
  der `ca-issuer` ausliefert (Antworten von `/enroll` und `/renew`, Vertrauensbuendel fuer Gateway und frps), baut er
  jetzt aus Zwischenzertifikat und Root, die er beim Start geprueft hat, statt den Inhalt von `<scope>-chain.pem`
  weiterzugeben. Eine Kettendatei, die nicht genau Zwischenzertifikat und Root enthaelt, bricht den Start weiter ab.
- **Desktop: der Tunnel-Dialog prueft den Visitor-Port vor dem Speichern (R-0585):** Bei einem STCP-Tunnel lehnt der
  Dialog einen Visitor-Port ab, der keine ganze Zahl von 1 bis 65535 ist, und nennt den Bereich; bisher kam erst die
  Ablehnung des Servers (`422`). Ein leeres Feld bleibt erlaubt, dann vergibt der Server einen freien Port. Doku:
  FRP-Tunnel (DE+EN).
- **SSRF-Schutz: ein Ziel unter `NO_PROXY` verbindet auch neben einem Proxy zur geprueften Adresse (Server und
  Monitoring):** Ein Ziel, das wegen `NO_PROXY` nicht ueber den gesetzten Proxy geht, verbindet wie ohne Proxy zu
  einer der geprueften Adressen, im HTTP-Check, im Alert-Webhook und in `http_get`/`http_post` der Hooks; bisher
  verband httpx es direkt ueber den Namen, den es dafuer ein zweites Mal aufloeste. Welche Anfragen ueber den Proxy
  gehen, bleibt gleich. Doku: Monitoring-Administration, Monitoring- und Hook-Entwicklerdoku (DE+EN).
- **Monitoring: Check-Namen ohne Steuerzeichen:** Ein Check-Name mit einem Steuerzeichen (C0 wie Zeilenumbruch oder
  Tab, dazu DEL) ergibt `422` an der Stelle des Namens („must not contain control characters“), in `POST /checks`,
  `PUT /checks/{id}` und in den Check-Definitionen von `POST /templates` und `PUT /templates/{id}`; die Grenze ist
  dieselbe wie bei den FRP-Feldern des Servers. Andere Zeichen, auch C1 und U+2028/U+2029, bleiben erlaubt.
  Gespeicherte Namen bleiben, wie sie sind, und ihre Alerts gehen weiter hinaus. Wer einen solchen Check oder ein
  solches Template bearbeitet und dabei den Namen mitschickt, wie der Desktop bei jedem Speichern, entfernt die
  Steuerzeichen aus dem Namen, sonst kommt `422`.
- **Server: gleichzeitige Refreshes mit demselben Refresh-Token:** Das neue Token-Paar bekommt nur der Aufruf, der
  den alten Refresh-Token sperrt; jeder weitere zaehlt als Wiederverwendung und beendet die Sitzungen des Benutzers,
  wie ein spaeterer Refresh mit einem schon verbrauchten Token. Clients buendeln ihre Refreshes. Doku: Server fuer
  Entwickler (DE+EN).
- **Server: neu angelegte Benutzer:** Ein neu angelegter Benutzer nimmt nur Tokens an, die ab seinem Anlegen
  ausgestellt wurden (`users.tokens_valid_after` steht auf der Anlegezeit, ganze Sekunde), gleich ob er ueber die
  API, den Bootstrap, `ADMIN_PASSWORD` oder die CLI entsteht. Bestehende Benutzer bleiben unveraendert. Doku: Server
  fuer Entwickler (DE+EN).
- **Server: Refresh-Token im Browser nur als Cookie:** Browser-Anfragen (Header `Sec-Fetch-Site`) an Login, Refresh
  und Bootstrap bekommen den Refresh-Token nur noch als HttpOnly-Cookie; `refresh_token` im JSON ist dann leer (`""`),
  das Schema bleibt gleich. Desktop, CLI und Skripte bekommen ihn unveraendert im JSON. Doku: API-Referenz und Server
  fuer Entwickler (DE+EN).
- **Diagnose-Bundle: `SMTP_USER` immer maskiert wie die Passwoerter:** Bei manchen Mail-Anbietern ist der
  SMTP-Benutzer selbst ein Zugangs-Token oder eine Key-ID. `scripts/diagnostics.sh` behandelt `SMTP_USER` darum wie
  `SMTP_PASSWORD`: mit und ohne `--mask-hosts` steht in `env.sanitized` `SMTP_USER=<redacted>`, und sein Wert wird in
  `report.txt` und den Logs `<redacted>`; kein Schalter stellt das ab. Der Wert wird nur als ganzes Wort ersetzt, ein
  kurzer Benutzer wie `admin` laesst `adminhelper` stehen. Doku: Troubleshooting (DE+EN), README.
- **Diagnose-Bundle: von Anfang an nur fuer den ausfuehrenden Nutzer lesbar und erst vollstaendig unter seinem
  Namen:** `scripts/diagnostics.sh` schreibt das Bundle in eine versteckte Zwischendatei im Zielordner, die von Anfang
  an den Modus 0600 hat, und benennt sie erst danach in `adminhelper-diagnostics-<ts>.tar.gz` um; auch die Dateien
  darin sind nur fuer diesen Nutzer lesbar. Ein Lauf, der vorher scheitert, hinterlaesst weder ein Bundle noch eine
  Zwischendatei. Eine Datei, die schon unter dem Namen liegt, wird ersetzt, statt mit ihren Rechten ueberschrieben zu
  werden. Mit `sudo` gestartet gehoert das Bundle root. Die Namen und Adressen fuer `--mask-hosts` stehen waehrend des
  Laufs nicht mehr in der Prozessliste. Wie beim Backup wird das Bundle nur in die Zwischendatei geschrieben, die das
  Skript selbst im Zielordner angelegt hat, und bleibt auch in einem Ordner mit Default-ACL 0600; liegt unter ihrem
  Namen etwas anderes, oder haelt das Ziel keinen Unix-Eigentuemer und -Modus (wie ein CIFS-, vfat- oder NTFS-Mount in
  der Regel), bricht der Lauf mit einem Hinweis ab. Doku: Troubleshooting (DE+EN).
- **Server liest `MTLS_ENFORCE` wie das Gateway:** `true`, `1`, `yes` und `on` erzwingen, `false`, `0`, `no` und `off`
  schalten permissiv (Gross-/Kleinschreibung egal), ungesetzt oder leer gilt der Default (erzwungen); jeder andere
  Wert erzwingt die Scope-Pruefung je Route ebenfalls und loggt eine Warnung. Bisher lief der Server bei `on`, einem
  leeren oder einem unbekannten Wert still permissiv, waehrend das Gateway am Handshake ein Zertifikat verlangte. Wer
  `MTLS_ENFORCE=on` gesetzt hat, bekommt fuer Zertifikate mit falschem Scope jetzt 403 statt nur einer Log-Zeile. Ein
  Test haelt die Tabelle des Servers und die des Gateways gleich. Doku: Betrieb (DE+EN), `.env.example`.
- **Server wertet die Zertifikats-Header nur noch aus, wenn die Anfrage direkt vom Gateway kommt:** `X-Client-Verify`
  und `X-Client-Cert` zaehlen nur, wenn die Gegenstelle eine aktuelle Adresse des Compose-Dienstes `gateway` ist. Von
  jeder anderen Gegenstelle gilt die Anfrage als ohne Client-Zertifikat, und der Server loggt eine Warnung mit der
  Adresse (hoechstens einmal je Adresse und Minute). Kommt eine Anfrage mit Zertifikat von einer Adresse, die der
  Server nicht kennt, loest er den Namen `gateway` sofort neu auf (hoechstens einmal je Sekunde; eine Anfrage wartet
  darauf hoechstens 1 s), damit ein neu angelegtes Gateway gleich wieder zaehlt. Ohne den Namen `gateway`, also
  ausserhalb von Compose, gibt es keine Zertifikats-Identitaet. Doku: Entwickler-Handbuch (DE+EN).

### Removed

- **Agent: kein PKI-Bundle aus der Aktivierungsantwort:** `provision` entpackt kein PKI-Bundle mehr; ein mitgeschicktes
  Feld `pkiBundle` ignoriert der Agent. Der Server schickt es seit 0.28.0 leer, und dieser Agent aktiviert nur ueber
  Port 8444, wo der Server die Aktivierung seit 0.39.0 annimmt. `provision` legt auch kein Verzeichnis `frp/pki` mehr
  an; ein vorhandenes bleibt unberuehrt, und die Pakete legen `/etc/frp/pki` weiter leer an. Doku: Agent-Entwicklerseite
  (DE+EN).

### Fixed

- **Monitoring: ein gescheitertes Loeschen laesst den Check eingeplant (R-0695):** Scheitert beim Loeschen eines
  Checks oder Templates das Speichern, bleibt der Check eingeplant; vorher lief er bis zum Neustart des Dienstes
  nicht mehr. Der Scheduler aendert sich erst nach dem Speichern.
- **Server: zwei gleichzeitige Hochstufungen desselben Benutzers zum Admin (R-0768):** Sie legen nur noch eine
  Standard-Benachrichtigungsregel an und loesen `user.promoted` einmal aus.
- **Server: ohne gesetztes `SECRET_KEY` erzeugen Server-Worker und Scheduler beim ersten Start nur noch einen
  gemeinsamen Schluessel (R-0761):** Wer ihn nicht zuerst schreibt, uebernimmt den des anderen Prozesses. Vorher konnte
  jeder Prozess einen eigenen erzeugen, und JWTs galten nicht prozessuebergreifend.
- **Server: mit `WEB_CONCURRENCY` > 1 erzeugt nur noch ein Worker das einmalige Setup-Token (R-0762):** Bisher
  schrieb jeder Worker ein eigenes Token und einen eigenen Hash; danach passten `.bootstrap_setup` und
  `.bootstrap_token` oft nicht zusammen, und das Token aus der Datei wurde abgewiesen. Jetzt passen beide immer
  zusammen, und der Hinweis steht einmal im Log. Neu ist die leere Datei `data/.bootstrap.lock`.
- **Desktop: Anfragen an den Server lesen die Geraete-Identitaet nicht mehr bei jedem Aufruf aus dem
  System-Schluesselbund (R-0644):** Der Prozess liest sie einmal und nach Registrieren, Erneuern und Zuruecksetzen neu;
  ein kurzer Lesefehler des Schluesselbunds schickt nicht mehr dauerhaft Anfragen ohne Geraete-Zertifikat.
- **Desktop: nach der Meldung "Zeitueberschreitung" beim Verbindungsaufbau oeffnet sich kein RDP-, SSH- oder
  Web-Fenster mehr (R-0642):** Bisher lief der Aufbau weiter und startete spaeter doch; die Anmeldepruefung von
  xfreerdp endet mit der Frist von 30 s.
- **Desktop: das Fenster friert nicht mehr ein, solange der System-Schluesselbund oder die Sperre der Einstellungen
  antwortet (R-0643):** Einstellungen laden und speichern, Passwort-Status, Passwort speichern und loeschen,
  Geraete-Identitaet, CA-Fingerprint und das Zuruecksetzen des Zertifikat-Pins laufen nicht mehr auf dem Haupt-Thread.
- **Desktop: eine halb geschriebene Ansible-Datei bleibt nicht im Temp-Verzeichnis (R-0574):** Scheitert das
  Schreiben von Inventory oder Playbook, nachdem die Datei angelegt ist, loescht der Client sie sofort.
- **Desktop: eine Tunnel-Zuordnung mit einem Port ausserhalb von 1-65535 laesst die Tunnel-Liste nicht mehr
  scheitern:** Bisher fehlten dann alle Zuordnungen, und keine Verbindung wurde ueber einen Tunnel aufgeloest; eine
  solche Zuordnung loest jetzt nur selbst keinen Visitor auf.
- **FRP: ein gespeicherter Tunnel mit einer solchen extra_config faellt allein weg:** Der Generator laesst einen
  Tunnel, dessen gespeicherte `extra_config` die neue Pruefung nicht besteht, mit Warnung aus der frpc-Konfiguration
  weg, auch wenn erst zwei Schluessel zusammen kollidieren; die uebrigen Tunnel des Hosts bleiben. Doku:
  Server-Entwicklerseite (DE+EN).
- **FRP: extra_config eines Tunnels nur in der Form, die der Agent annimmt:** `POST` und `PUT /api/frp/tunnels`
  antworten `422` an `extra_config` auf Schluessel mit leeren Segmenten (`.a`, `a.`, `a..b`), auf Ganzzahlen ausserhalb
  64 Bit und auf Schluessel, die ohne Ruecksicht auf Gross-/Kleinschreibung einem Feld des Proxys oder einem anderen
  Schluessel gleichen oder Praefix davon sind; bisher wurden sie gespeichert, und der Agent lehnte daraufhin die
  Konfiguration des ganzen Hosts ab. Doku: API-Referenz fuer Entwickler (DE+EN).
- **FRP: Ein gespeicherter Visitor-Port ausserhalb 1-65535 wird beim Aendern ersetzt (R-0570):** Ein `PUT
  /api/frp/tunnels/{id}` ohne `visitor_port` gibt einem STCP-Tunnel mit einem solchen Altwert einen freien Port; die
  automatisch angelegte Verbindung zeigt auf diesen statt auf einen Port, an dem nie ein Visitor lauscht. Doku:
  FRP-Tunnel und API-Referenz fuer Entwickler (DE+EN).
- **FRP: Ein gespeicherter lokaler Port ausserhalb 1-65535 kostet nicht mehr alle Tunnel des Hosts (R-0560):** Der
  Server laesst einen solchen Tunnel aus der frpc-Konfiguration des Agents weg und schreibt eine Warnung ins
  Server-Log; vorher lehnte frpc die ganze Konfiguration ab. Doku: FRP-Tunnel (DE+EN).
- **FRP: Der lokale Port eines Tunnels nimmt nur 1-65535 an (R-0560):** `POST` und `PUT /api/frp/tunnels` mit
  einem `local_port` ausserhalb 1-65535 (im `PUT` auch `null`) antworten `422` an `local_port`; vorher wurde der Wert
  gespeichert, und ein groesserer Wert machte die frpc-Konfiguration des Agents ungueltig, sodass alle Tunnel des
  Hosts ausfielen (`null` ergab 409 mit falscher Meldung). Doku: API-Referenz fuer Entwickler (DE+EN).
- **FRP: Tunnel mit unbekannter Verbindung ergibt 422, ein verlorenes Rennen 409 (R-0656):** Eine `connection_id`,
  zu der es keine Verbindung gibt, ergibt `422` an `connection_id`: bei `POST /api/frp/tunnels` statt 500, bei `PUT`
  statt `409` mit falscher Meldung. Ein verlorenes Rennen um Name oder Visitor-Port ergibt beim Anlegen und beim
  Aendern mit automatischer Verbindung `409` statt 500. Doku: API-Referenz fuer Entwickler (DE+EN).
- **Server: der Monitoring-Proxy antwortet 502 oder 504 statt 500 (R-0655):** Ist der Monitoring-Dienst nicht
  erreichbar, etwa waehrend eines Neustarts, antworten Agent-Report und Admin-Proxy mit `502`, ohne Antwort binnen
  30 s mit `504`; bisher endete jeder Aufruf mit einem unbehandelten Fehler (500). Das Log nennt nur den Fehlertyp.
  Doku: API-Referenz fuer Entwickler (DE+EN).
- **Server: ein offener Benachrichtigungs-Stream haelt keine Datenbank-Verbindung mehr (R-0618):** Mit
  Client-Zertifikat hielt jeder Desktop fuer seine ganze Sitzung eine Verbindung aus dem Pool; die Scope-Pruefung des
  Streams laeuft jetzt auf der kurzen Session der Anmeldung. Ohne passendes Zertifikat antwortet er im erzwungenen
  Modus wie bisher mit 403.
- **Hooks: eine geleerte Beschreibung wird gespeichert (R-0651):** `PUT /api/hooks/{id}` mit `"description": null`
  loescht die Beschreibung; bisher meldete der Dialog "gespeichert" und zeigte wieder den alten Text. Ein fehlendes
  Feld laesst sie unveraendert. Doku: API-Referenz fuer Entwickler (DE+EN).
- **Hooks: Schedule-Hooks mit festem Intervall laufen wieder (R-0617):** Hooks mit einem Intervall von 1m bis 24h
  liefen nie, weil der Abgleich des Schedulers alle 30 s ihren naechsten Lauf neu setzte. Ein unveraenderter Job
  behaelt jetzt seinen naechsten Lauf; Cron-Hooks waren nicht betroffen.
- **Agent: jeder Lauf hat ein Budget von 240 s mit Reserve fuer den Monitor-Push:** Erneuerung und FRP-Abgleich
  haben je hoechstens 60 s, die Erhebung des Reports endet 45 s vor dem Ende des Laufs, der Push hat diese 45 s. Ein
  haengendes `systemctl`, ein haengender Sync oder ein langsames Werkzeug kostet damit seine Phase statt des Reports;
  bisher konnten die Einzeldeckel zusammen ueber 500 s dauern, waehrend systemd den Lauf nach 270 s beendet. Das
  Ende eines Laufs reicht bis in die Sperre, die Erneuerung, den Sync und jeden Werkzeug-Aufruf. Doku: Agent fuer
  Entwickler (DE+EN).
- **Monitoring: ein waehrend des manuellen Laufs geloeschter Check antwortet 404:** `POST /checks/{id}/run` auf einen
  Check, der waehrend des Laufs geloescht wird, antwortet 404 „Check not found“ statt 500; das Ergebnis des Laufs
  wird wie bisher verworfen.
- **Desktop: der Zertifikat-Pin gilt erst, wenn er im Schluesselbund gespeichert ist:** Mit „Selbstsignierte
  Zertifikate erlauben“ pinnt der Desktop beim ersten Verbinden das Server-Zertifikat im Schluesselbund des Systems.
  Laesst sich der Pin dort nicht speichern oder nicht lesen, lehnt der Desktop die Verbindung jetzt mit einem eigenen
  Text ab, der den Schluesselbund nennt („… could not be read from or stored in the system keyring …“), statt den Pin
  nur bis zum Prozessende zu halten bzw. einen Zertifikatswechsel zu melden. Abhilfe: den Schluesselbund entsperren
  und neu verbinden. Doku: Desktop fuer Entwickler, Troubleshooting (DE+EN).
- **Desktop unter Windows: ein Lesefehler des Credential Managers gilt als Fehler:** Scheitert das Lesen aus dem
  Windows Credential Manager mit einem anderen Fehler als „nicht gefunden“, behandelt der Desktop das beim
  Zertifikat-Pin, bei gespeicherten RDP-Passwoertern und bei der Pruefung, ob ein Workspace eine Geraete-Identitaet
  haelt, jetzt als Fehler statt als fehlenden Eintrag, wie schon unter Linux und macOS.
- **Server: gescheiterte Event- und Schedule-Hooks stehen im Log (R-0558):** Endete ein Event- oder Schedule-Hook mit
  `success: false` (etwa Exit-Code ungleich 0, Timeout, Ausgabe-Limit oder Hook-Limit), schrieb der Server nichts ins
  Log, obwohl die Doku es beschreibt; dort landete nur ein Fehler, den der Runner selbst warf. Jetzt schreibt er je
  gescheitertem Lauf eine Zeile auf WARNING mit dem Namen des Hooks, bei Event-Hooks dem Event, und dem `error`-Text
  (auf einer Zeile, bei mehr als 1000 Zeichen dessen Ende): Event-Hooks unter `app.core.events` im Log des
  `server`-Dienstes, Schedule-Hooks unter `app.modules.hooks.scheduler` im Log des `scheduler`-Dienstes. Ein
  Webhook-Trigger und ein Lauf ueber `POST /api/hooks/{id}/run` melden den Fehler weiter in der Antwort.
- **Web-Panel startet auch bei gesperrtem Seitenspeicher (R-0654):** Sperrt der Browser die Website-Daten (Cookies
  und Website-Daten blockiert), wirft schon der Zugriff auf `localStorage` einen `SecurityError`. Das Web-Panel las
  und loeschte dort beim Laden ungeschuetzt und blieb eine leere Seite, ohne Login-Maske. Jetzt geht jeder Zugriff auf
  den Seitenspeicher durch einen Helfer, der nie wirft: das Panel zeigt die Login-Maske, die Sprache kommt aus dem
  Browser, und eine Sprachwahl gilt bis zum Neuladen.
- **Web-Panel: helles Design uebersteht einen Reload (R-0647):** Das Skript, das das gespeicherte Design vor dem
  ersten Zeichnen setzt, stand inline in `index.html`; die CSP des Servers (`script-src 'self'`) blockierte es, mit
  CSP-Fehler in der Konsole. Nach einem Neuladen startete das Panel deshalb dunkel und ueberschrieb die gespeicherte
  Wahl. Das Skript liegt jetzt als eigene Datei `theme-init.js` beim Panel und laeuft unter der CSP.
- **Web-Panel: manueller Hook-Lauf endet nicht mehr nach 15 s (R-0648):** Jede Anfrage des Panels gab nach 15 s auf,
  auch „Ausfuehren“ eines Hooks, den der Server bis zu 30 s lang synchron ausfuehrt. Lief ein Hook 15 bis 30 s, zeigte
  das Panel „Request timed out“, das Ergebnis ging verloren, und der Knopf wurde wieder frei, waehrend der Hook noch
  lief. Jetzt wartet das Panel auf den Hook-Lauf 75 s, der Knopf bleibt bis zum Ende gesperrt, und die Meldung bei
  einer Zeitueberschreitung ist uebersetzt.
- **Web-Panel: schnelle Neuanmeldung nach dem Abmelden haelt (R-0653):** Das Panel meldete sofort ab, wartete aber
  nicht auf die Antwort des Servers — und erst diese loescht den Access-Token und das Refresh-Cookie. Meldete sich
  jemand schneller wieder an, als die Abmeldung beantwortet war, beendete die spaete Antwort die neue Sitzung bei der
  naechsten Aktion. Jetzt wartet eine neue Anmeldung, bis die Abmeldung beantwortet ist (hoechstens 15 s), auch nach
  einer abgelaufenen Sitzung. Abmelden leert ausserdem die Benutzer-, Hook-, API-Key- und FRP-Daten im Browser.
- **Web-Panel: eine Anfrage der vorigen Sitzung meldet die neue nicht mehr ab:** Endet eine Anfrage, die vor dem
  Abmelden startete, erst nach erneutem Anmelden mit 401, meldet sie die neue Sitzung nicht mehr ab und wird nicht
  mit deren Token wiederholt; sie endet mit `Session expired`.
- **Web-Panel: eine Aenderung, deren Antwort erst nach dem Abmelden ankommt, aendert keine Liste mehr:** Kommt die
  Antwort auf das Anlegen, Bearbeiten oder Loeschen eines Benutzers, Hooks oder API-Keys erst nach dem Abmelden an,
  erscheint der Eintrag nicht mehr in der geleerten Liste, und die erste Liste der naechsten Sitzung wird nicht mehr
  verworfen.
- **Web-Panel: gespeicherte FRP-Server-Konfiguration bleibt stehen:** Die gespeicherte FRP-Server-Konfiguration wird
  nicht mehr von einem noch laufenden Laden der Seite ueberschrieben, das vor dem Speichern begonnen hatte. Kommt die
  Antwort auf das Speichern erst nach dem Abmelden an, erscheint die Konfiguration nicht mehr in der naechsten Sitzung.
- **Web-Panel: Bearbeiten des eigenen Kontos wirkt sofort (R-0652):** Nahm sich ein Admin im Web-Panel selbst das
  Admin-Recht, zeigte das Panel weiter die Admin-Seiten, und jede Aktion endete mit einem Fehler; jetzt uebernimmt es
  die neuen Rechte sofort. Aenderte er sein eigenes Passwort, beendete der Server alle Sitzungen des Kontos, das Panel
  merkte es aber erst bei der naechsten Aktion („Session expired“); jetzt meldet es sofort ab, mit dem Hinweis, sich
  mit dem neuen Passwort anzumelden.
- **Sammellauf: Schritt-Tabelle und Sekunden je Schritt wieder im Report (R-0603):** Bei einem Sammellauf aus dem
  Haupt-Checkout verwarf `heavy.sh` seit dem 2026-09-18 jedes Artefakt der Box („last-all.json describes another
  tree — ignored“): `run.sh` nahm Kopf und Tree-Hash zuerst vom `git` der Box, und deren Hash, am Ende des Laufs ueber
  einen vom Sync geformten Baum gerechnet, traf den des Clients nie. Der Report hatte deshalb nur die Ebenen-Zeile,
  `steps-all.tsv` blieb leer, und die Historie bekam keine Schritt-Zeilen. Jetzt gehen die Werte, die `iter.sh` vom
  Client mitgibt, vor dem `git` der Box; als Wert zaehlen nur genau 40 Hex-Zeichen. Ein Lauf ohne Sync und ein
  lokaler Lauf ohne diese Variablen fragen weiter das eigene `git`. `task-close.sh` startet sein Verify ohne
  `AH_HEAD`/`AH_TREE_HASH`, damit seine Pruefung, ob sich der Baum waehrend der Suite geaendert hat, weiter den Hash
  vergleicht, den `run.sh` ueber diesen Checkout rechnet. Doku: DEVELOPMENT.
- **Test des Monitoring-Entrypoints: Leck-Probe mit eigenem Zufallspasswort (R-0824):** Der Server-Test
  `test_the_entrypoint_of_monitoring_creates_its_database_once` prueft, dass ein gescheiterter Lauf des Entrypoints
  kein Passwort ausgibt. Er suchte dazu das Passwort der Test-Datenbank in der Ausgabe; ohne `DATABASE_URL`
  (testcontainers, Passwort `test`) steht es im Datenbanknamen der Fehlermeldung, und die Probe schlug an, ohne dass
  ein Passwort ausgegeben wurde (Sammellauf rot). Jetzt bekommt der gescheiterte Lauf ein eigenes Zufallspasswort,
  und die Probe sucht dieses.
- **Web-Panel: der Vite-Dev-Server proxied nur `/api`, auf `http://127.0.0.1:8080` (R-0669):** Der Dev-Server
  leitete `/auth`, `/api` und `/health` an `http://localhost:8000` weiter. Der Server hat nur Routen unter `/api`, und
  DEVELOPMENT.md und die Entwickler-Doku starten ihn auf `127.0.0.1:8080`. Jetzt geht nur `/api` dorthin; ein Test
  prueft die Praefixe gegen den OpenAPI-Snapshot des Servers. Doku: Web-UI fuer Entwickler (DE+EN).
- **Troubleshooting nennt nur Agent-Befehle, die es gibt (R-0731):** Fuer einen Durchlauf von Hand mit
  Debug-Ausgabe steht dort jetzt `sudo adminhelper-agent run --once --log-level debug` statt `run --verbose` und
  `monitor run --dry-run`. Zum Client-Zertifikat des Agents steht dort, wie der Agent es erneuert (bei jedem Lauf,
  sobald die Haelfte der Laufzeit um ist), statt `frpc rotate`, 30 Tagen Restlaufzeit und CRL. Ein Test im Agent
  prueft jeden Aufruf in der Doku, der `adminhelper-agent` als eigenes Wort nennt, gegen die CLI;
  Aufrufe ueber die `.exe` oder einen Pfad liest er nicht. Doku: Troubleshooting (DE+EN).
- **Agent: `agent.log` auch als Windows-Dienst (R-0619):** Der Agent schreibt jede Log-Zeile nach stdout und in die
  rotierende Datei `agent.log`. Bisher brach die Ausgabe ab, sobald stdout scheiterte, bevor die Datei die Zeile
  bekam; ein Windows-Dienst hat kein schreibbares stdout, und `agent.log` unter `%ProgramData%\AdminHelper\logs`
  blieb so leer. Jetzt bekommt jedes Ziel jede Zeile, auch wenn das andere scheitert; ein nicht schreibbares
  Log-Verzeichnis haelt die Ausgabe nach stdout weiter nicht auf.
- **Agent: Ctrl-C, SIGTERM und Dienst-Stopp brechen einen laufenden Durchlauf ab (R-0640):** Im Dauerbetrieb
  (`run` ohne `--once`) wirkte SIGINT/SIGTERM erst, wenn der laufende Durchlauf (Erneuerung, FRP-Sync, Monitor-Push)
  von selbst fertig war. Der Windows-Dienst endete beim Stopp dagegen sofort, auch mitten in einem Durchlauf. Jetzt
  erreichen das Signal und Stop/Shutdown des Dienstes den laufenden Durchlauf und brechen ihn ab; der Agent endet,
  sobald der Durchlauf zurueck ist, hoechstens nach 10 s, und der Dienst meldet bis dahin `StopPending`. Ein zweites
  Ctrl-C beendet den Dauerbetrieb sofort.
- **Agent: Provisionierung und Agent-Lauf aendern frpc nicht mehr gleichzeitig (R-0641):** `frpc.toml`, die
  Hash-Dateien, `admin.conf`, `adminhelper.conf` und den frpc-Dienst aendern Provisionierung und FRP-Abgleich jetzt
  nur unter der Sperre `/etc/frp/frpc.lock` (Windows `%ProgramData%\AdminHelper\frp\frpc.lock`); bisher konnten ein
  Timer-Lauf und eine Provisionierung dieselben Dateien zugleich schreiben. Ein zweiter Aufruf wartet hoechstens
  60 s, ein Lauf zudem nur, bis er endet, und bricht dann mit einem Fehler ab, der die Sperrdatei nennt; ein Lauf
  ohne Aenderung sperrt nichts. Doku: Agent fuer Entwickler (DE+EN).
- **Server: ein einzelnes Surrogat in einem Request-Body ergibt `422` wie ein NUL-Byte:** Ein einzelnes Surrogat
  (U+D800 bis U+DFFF, in JSON nur als Escape geschrieben) in irgendeinem String eines Request-Bodies, als Wert oder
  Schluessel und beliebig tief, ergibt `422` an seiner Stelle; nichts wird gespeichert. Bisher endeten solche Eingaben
  ausserhalb der frp-Felder und der Felder mit Laengengrenze mit `500`, in Tags wurden sie gespeichert, und jede Antwort
  mit der Zeile endete danach mit `500`. In `extra_config` der FRP-Server-Konfiguration nennt der Fehler jetzt den
  Schluessel, unter dem der Wert steht.
- **Desktop unter Windows: Windows Terminal bekommt jedes Argument unveraendert:** Oeffnet der Desktop SSH oder einen
  Ansible-Lauf in Windows Terminal, kommen Benutzer, Schluesselpfad und Ansible-Pfade als je ein Argument an, auch
  mit `;` (Windows Terminal las ein `;` als Trenner seiner eigenen Befehle). Ein Wert, den Windows Terminal nicht
  unveraendert weitergeben kann (leer, mit `"`, mit `%` — Windows Terminal setzt `%NAME%` ein —, mit Steuerzeichen
  oder mit Leerzeichen und abschliessendem `\`), oeffnet nicht, und der Desktop meldet das („Windows Terminal cannot
  pass … unchanged“).
- **Desktop unter Windows ohne Windows Terminal: die Konsole bekommt jedes Argument unveraendert:** Ist Windows
  Terminal nicht installiert, oeffnet der Desktop SSH oder einen Ansible-Lauf in einer neuen Konsole mit genau einer
  cmd-Ebene statt ueber `cmd /C start`. Argumente mit `&`, `|`, `<`, `>`, `^`, `!`, `;`, Klammern oder Leerzeichen
  kommen unveraendert an (vorher konnte etwa `a&b` als `a^&b` ankommen). Ein Wert mit `"`, `%` oder Steuerzeichen
  oeffnet nicht, und der Desktop meldet das („The Windows console (cmd) cannot pass … unchanged“). Der Fenstertitel
  der Konsole kann sich dadurch aendern.
- **Desktop: ein frpc, der nach einem abgebrochenen Programmlauf weiterlief, endet beim naechsten Start:** Lief frpc
  nach einem abgebrochenen Programmlauf (Task beenden, Absturz) weiter, endet er beim ersten Tunnel-Abgleich des
  naechsten Starts desselben Workspace; seine Tunnel und Ports werden frei. Der Desktop beendet ihn ueber
  `POST /api/stop` seiner Admin-API mit den Zugangsdaten aus der `visitor.toml`, die der abgebrochene Lauf
  zurueckliess, und nur, wenn deren `webServer` genau der des Desktops ist; antwortet dort kein frpc, geht der Abgleich
  weiter wie bisher. Unter Windows endet frpc schon mit dem Programm, auch nach Task beenden oder einem Absturz: Der
  Desktop legt ihn gleich nach dem Start in ein Job Object mit `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; gelingt das nicht,
  steht eine Warnung im Log, und der naechste Start beendet ihn wie oben. Doku: Desktop fuer Entwickler (DE+EN).
- **Desktop: RDP mit Anmeldung von Hand haelt nur noch das Ende der xfreerdp-Ausgabe (R-0646):** Startet der Desktop
  xfreerdp ohne Passwort (die Anmeldung geschieht in xfreerdp), haelt er von dessen Ausgabe nur noch die letzten
  8 KiB je Strom (stdout, stderr) statt der ganzen Sitzung, wie schon der Start mit Passwort. Die Meldungen beim Ende
  bleiben: Eine Fehlerzeile im gehaltenen Ende ergibt dieselbe Meldung wie bisher, und „RDP Verbindung
  fehlgeschlagen“ kommt beim Ende von xfreerdp nur, wenn im gehaltenen Ende keine Fehlerzeile steht und nie eine
  Verbindung gemeldet wurde. Eine Fehlerzeile, die frueh in einer langen,
  danach laufenden Sitzung stand, ergibt am Ende keine Meldung mehr.
- **Desktop, Provisionierungs-Tab: Backslash im erzeugten Befehl auch fuer fish woertlich:** Ein Backslash in der
  Server-URL steht im angezeigten Installationsbefehl jetzt ausserhalb der einfachen Anfuehrungszeichen als `\\`, so
  dass POSIX-Shells (sh, bash, zsh) und fish denselben Wert lesen; fish las `\\` und `\'` innerhalb einfacher
  Anfuehrungszeichen als Escape. Werte ohne Backslash sehen aus wie bisher.
- **Desktop: Gepinntes Zertifikat zuruecksetzen meldet einen Fehler des Schluesselbunds (R-0748):** Kann der
  Schluesselbund des Systems den Pin nicht loeschen, melden „Gepinntes Zertifikat zuruecksetzen“ (Anmeldebildschirm
  und Einstellungen) und „Geraete-Identitaet zuruecksetzen“ jetzt einen Fehler („the pinned certificate could not be
  removed from the keyring: …“), statt den Reset als erfolgreich zu melden; bisher blieb der alte Pin stehen, und beim
  naechsten Verbinden lehnte der Desktop die Verbindung wieder ab. Abhilfe: den Schluesselbund entsperren und dasselbe
  Zuruecksetzen wiederholen. Doku: Troubleshooting (DE+EN).
- **Monitoring: keine Datenbankverbindung waehrend Messung und Metrik-Abfrage (R-0615):** Ein Check, ein manueller
  Lauf (`POST /checks/{id}/run`) und ein Metrik-Abruf (`GET /checks/{id}/metrics`) halten waehrend der Messung bzw.
  der VictoriaMetrics-Abfrage keine Datenbankverbindung mehr; ein haengendes Ziel kann den Verbindungs-Pool des
  Monitorings nicht mehr erschoepfen, Agent-Reports und API-Anfragen bekommen weiter eine Verbindung. Wird ein Check
  waehrend seines Laufs geloescht, verwirft das Monitoring dessen Ergebnis ohne Fehlerprotokoll.
- **Monitoring: Schreiben nach VictoriaMetrics blockiert weder Checks noch Agent-Reports (R-0615, R-0636):** Die
  Metriken gehen in einen Puffer (bis 100 000 Zeilen und hoechstens 64 MiB), den ein eigener Thread in Stapeln bis
  10 000 Zeilen nach VictoriaMetrics schreibt; ein haengendes VictoriaMetrics haelt keinen Check und keinen
  Agent-Report mehr bis zu rund 30 s bzw. 60 s auf. Eine von VictoriaMetrics abgelehnte Zeile (HTTP 4xx) wird nicht
  mehr dreimal gesendet, sondern einmal mit Status und Anfang der Antwort geloggt; Timeout, Verbindungsfehler und 5xx
  werden weiter bis zu dreimal versucht. Ist der Puffer voll, verwirft das Monitoring neue Zeilen und meldet die Zahl
  beim Verwerfen hoechstens einmal je Minute, spaetestens aber, sobald der Puffer wieder leer ist; beim Herunterfahren
  leert es den Puffer bis zu 5 s. Doku: Monitoring fuer Entwickler (DE+EN).
- **Monitoring: ein nicht erreichbares VictoriaMetrics erscheint als Fehler (R-0636):** Scheitert eine Abfrage an
  VictoriaMetrics, antwortet der Metrik-Abruf (`GET /checks/{id}/metrics`) mit HTTP 502 „Metrics store unavailable“
  statt mit leeren Reihen, und die aufgeklappte Grafik eines Checks zeigt im Desktop „Fehler beim Laden“ statt
  „keine Daten“. Der
  Check `disk_forecast` steht dann auf `unknown` mit „Metrics store unavailable“ statt „No disk history yet“. Doku:
  Monitoring fuer Administratoren (DE+EN).
- **Monitoring: CPU- und RAM-Verlauf eines Servers kommt einmal statt doppelt (R-0633):** Der Check
  `agent_resources` schreibt CPU und RAM nicht mehr zusaetzlich mit seinen Check-Labels nach VictoriaMetrics, sondern
  nur noch seinen Status; die Werte schreibt allein der Agent-Push je Server. Der Metrik-Abruf eines
  `agent_resources`-Checks (`GET /checks/{id}/metrics`) liest fuer CPU, RAM, Platten und Temperaturen nur diese
  Serien ohne `check_id` und liefert je Wert eine Serie statt zwei gleich beschrifteter; die Liste der aktuellen
  Werte im Desktop brach daran ab. Die bisherigen Serien mit Check-Labels bleiben bis zum Ende der Retention in
  VictoriaMetrics, werden aber nicht mehr gelesen. Doku: Monitoring fuer Entwickler (DE+EN).
- **Monitoring: der Metrik-Abruf zeigt je Check nur dessen Reihen (R-0749):** Der Metrik-Abruf
  (`GET /checks/{id}/metrics`) von `agent_ping`, `service_process`, `docker_health`, `proxmox_backup` und
  `zfs_health` las die Werte nach Server statt nach Check; zwei Checks desselben Typs auf einem Server zeigten deshalb
  beide dieselben Reihen, jede doppelt. Jetzt liest er sie ueber die `check_id` des Checks; nur `agent_resources`
  liest CPU, RAM, Platten und Temperaturen weiter je Server. Die Reihen trugen die `check_id` schon bisher, der
  Verlauf bleibt erhalten. Doku: Monitoring fuer Entwickler (DE+EN).
- **Monitoring: eine Platte ohne lesbaren Mountpoint bekommt eine eigene Reihe (R-0753):** Der Agent-Push schreibt
  eine Platte ohne `mount` (oder mit einem `mount`, der kein String ist) als `mount=?`, wie der Check
  `agent_resources` sie schon nennt. Bisher landete sie mit `mount=/` in der Reihe der Root-Platte und verfaelschte
  deren Prognose in `disk_forecast`. Bisherige Werte solcher Platten bleiben bis zum Ende der Retention in der Reihe
  von `/`. Doku: Monitoring fuer Entwickler (DE+EN).
- **Monitoring: ein einzelnes Surrogat in einem Request-Body oder Agent-Report ergibt `422` wie ein NUL-Byte
  (R-0774):** Ein einzelnes Surrogat (U+D800 bis U+DFFF, in JSON nur als Escape geschrieben, etwa `\ud800`) in
  irgendeinem String eines Request-Bodys, als Wert oder Schluessel und beliebig tief, ergibt `422` an seiner Stelle;
  nichts wird gespeichert. Ein Agent-Report damit ergibt ebenso `422`, die Liveness des Servers zaehlt trotzdem.
  Bisher endete das Speichern mit `500`, oder der Wert landete in der `config` eines Checks, und jede Antwort mit
  diesem Check endete danach mit `500`; im Agent-Report ging der ganze Schreibstapel nach VictoriaMetrics verloren,
  samt den Zeilen anderer Server im selben Stapel. Doku: Monitoring fuer Entwickler (DE+EN).
- **Monitoring: der Betreff einer Alert-Meldung ist einzeilig:** Eine Alert-Mail fuer einen Check mit Zeilenumbruch
  im Namen ging nicht raus, das Alert-Log zeigte `SMTP error (HeaderWriteError)`. Jetzt stehen Steuerzeichen (C0,
  DEL, C1) und die Zeilen- und Absatztrenner U+2028/U+2029 des Check-Namens im Betreff, und damit im Titel der
  Glocke, als Leerzeichen; der Text der Meldung und das Feld `check_name` des Webhooks tragen den Namen unveraendert.
  Doku: Monitoring fuer Administratoren (DE+EN).
- **Monitoring: ein kaputter Eintrag im Agent-Report kostet nur sich selbst (R-0632):** Ein Eintrag in `disks` oder
  `temperatures`, der kein Objekt ist, oder eine Liste als `fstype` liess bisher alle Metriken des Reports wegfallen.
  Jetzt wird ein Eintrag, der kein Objekt ist, uebersprungen; eine Liste als `fstype` zaehlt wie ein fehlender
  `fstype`, die Platte wird geschrieben. Wie bei den Checkern zaehlen `fstype`, `mount` und `sensor` nur als
  String (sonst wie ohne das Feld) und Messwerte nur als JSON-Zahl: einen Zahl-String wie `"97"` schreibt der
  Agent-Push nicht mehr als Messwert. Doku: Monitoring fuer Entwickler (DE+EN).
- **Monitoring: ein Datenbankfehler bei einem Check eines Agent-Reports kostet nur diesen Check (R-0635):** Jeder
  Push-Check eines Agent-Reports wird in einem eigenen Savepoint ausgewertet. Scheitert ein Check an der Datenbank
  (Deadlock, Abbruch beim Sperren seines Zustands, gescheitertes Schreiben), verwirft das Monitoring nur dessen
  Ergebnis samt Status-Punkt und Alert; bisher scheiterten alle folgenden Checks und das Speichern, der Report endete
  mit HTTP 500 oder speicherte still nichts, und die Ergebnisse des ganzen Reports gingen verloren.
- **Monitoring: eine Alert-Regel mit sehr grossem oder leerem Cooldown bricht den Versand nicht mehr ab (R-0631):**
  Eine Regel mit `cooldown_minutes` ueber rund 1 065 000 000 (etwa 2000 Jahre, das Schema erlaubt bis 2 147 483 647)
  oder ohne Wert (`null`, etwa nach `PUT /alerts/{id}` mit `"cooldown_minutes": null`) brach beim Pruefen ihres
  Cooldowns den Versand ab: Die folgenden Regeln sendeten nicht, die Glocke bekam kein Ereignis, die Meldung war
  verloren. Jetzt zaehlt ein leerer Cooldown als der Default 30 Minuten, und ein Cooldown, der vor den
  Kalenderanfang reicht, zaehlt jeden frueheren erfolgreichen Versand der Regel fuer den Check.
- **Monitoring: ein Check mit sehr langem Namen erreicht die Glocke wieder (R-0637):** Der Titel des
  Glocken-Ereignisses ist der Betreff der Meldung (`[AdminHelper Monitor] <STUFE>: <Check-Name>`); ab rund 480 Zeichen
  Check-Name war er laenger als die 512 Zeichen, die der Server annimmt, der Server lehnte das Ereignis mit HTTP 422
  ab, und Glocke, Hub-Mail und Event-Hook blieben aus. Jetzt wird der Titel auf 512 Zeichen gekuerzt (die ersten 511
  und `…`); der Betreff von Mail und Webhook der Alert-Regeln bleibt ungekuerzt.
- **Monitoring: der HTTP-Check liest hoechstens 1 MiB, und `timeout` gilt fuer den ganzen Check (R-0616):** Der
  Check liest den Body nur noch mit `search_string` und davon hoechstens die ersten 1 MiB; eine komprimierte Antwort
  (gzip, deflate) entpackt er dafuer schrittweise und hoechstens bis 1 MiB. Ohne `search_string` liest er den Body
  gar nicht, auch bei Redirects nicht. Bisher holte er jede Antwort samt ganzem Body. `timeout` gilt fuer den ganzen
  Check statt je Anfrage und Phase: jede Anfrage, auch nach einem Redirect, bekommt die verbleibende Zeit, und das
  Lesen des Bodys endet mit der Frist; ein einzelner Lesevorgang, auch der der Kopfzeilen, wartet bis zur
  verbleibenden Zeit, eine Antwort, die stueckweise kommt, kann den Check also ueber `timeout` hinaus halten. Ein
  Server, der den Body troepfeln liess, hielt den Check bisher unbegrenzt. Fehlt `search_string` in einer laengeren Antwort, lautet die Meldung „Text '…' not found
  in the first 1 MiB of the response“. Die Antwortzeit (`http_response_ms`) enthaelt ohne `search_string` keinen
  Body-Download mehr. Doku: Monitoring fuer Administratoren (DE+EN).
  Check liest den Body nur noch mit `search_string` und davon hoechstens die ersten 1 MiB; ohne `search_string` liest
  er ihn gar nicht, auch bei Redirects nicht. Bisher holte er jede Antwort samt ganzem Body. `timeout` gilt fuer den
  ganzen Check samt Redirects und Lesen statt je Anfrage und Phase; ein Server, der den Body troepfeln liess, hielt
  den Check bisher unbegrenzt. Fehlt `search_string` in einer laengeren Antwort, lautet die Meldung „Text '…' not
  found in the first 1 MiB of the response“. Die Antwortzeit (`http_response_ms`) enthaelt ohne `search_string`
  keinen Body-Download mehr. Doku: Monitoring fuer Administratoren (DE+EN).
- **Server: Steuerzeichen U+0080 bis U+009F in FRP-Feldern und im Servernamen ergeben `422` (R-0786):** Ein
  Steuerzeichen U+0080 bis U+009F in einem Textfeld eines FRP-Tunnels (auch einem `extra_config`-Wert) oder der
  FRP-Server-Konfiguration oder im Servernamen ergibt bei `POST` und `PUT` jetzt `422`, wie die uebrigen
  Steuerzeichen; bisher speicherte der Server es. TOML erlaubt diese Zeichen in einem String, der Agent verweigert
  aber eine frpc.toml mit einem solchen Zeichen, und der Host bekaeme keine Konfiguration. Gespeicherte Werte bleiben,
  wie sie sind. Doku: API-Referenz (DE+EN).
- **Hooks: Cron-Ausdruecke von Schedule-Hooks gelten in UTC (R-0756):** wie in der Betriebsdoku beschrieben; bisher
  galt `TZ` des Containers (Voreinstellung `Europe/Berlin`). Bestehende Cron-Hooks laufen dort nach dem Update 1 h
  (Winter) bzw. 2 h (Sommer) spaeter als bisher; wer die Ortszeit will, schreibt den Ausdruck in UTC um. `next_run`
  zeigte bei `TZ` ungleich UTC die Ortszeit als UTC, auch bei Intervall-Hooks; jetzt steht dort der naechste Lauf in
  UTC. Doku: Server-Entwicklerdoku (DE+EN).
- **Hooks: Hintergrundprozess eines Skripts verzoegert die Antwort nicht mehr ueber 60 s (R-0778):** Startete ein
  Hook einen Hintergrundprozess, der stdout oder stderr des Workers erbte, kam die Antwort von `/api/hooks/trigger`
  (auch `/api/hooks/trigger/{token}`) und `/api/hooks/{id}/run` erst nach mehr als 60 s, am Gateway also als 504.
  Nach dem Ende des Workers wartet der Runner jetzt hoechstens 2 s auf den Rest der Ausgabe, killt dann die
  Prozessgruppe und wartet noch einmal hoechstens 2 s; ein Lauf dauert so hoechstens 34 s. Doku:
  Hook-Entwicklerdoku (DE+EN).
- **Desktop: Tunnel fuer Benutzer ohne Admin-Rechte (R-0484):** Der Desktop loest fuer Benutzer ohne
  Admin-Rechte auch Verbindungen auf, die ein Admin von Hand mit einem Tunnel verknuepft hat, und zeigt an ihren
  Verbindungen den Tunnel. Dafuer liefert `GET /api/frp/tunnels` einem Nicht-Admin statt `403` die freigegebenen
  Tunnel seiner zugewiesenen Server, je nur mit den Feldern, die der Desktop liest (ohne Secret, ohne
  `localIp`, `frpConfigId`, `extraConfig`, `tags`, `createdAt`); ohne zugewiesenen Server eine leere Liste.
  Admins bekommen die Liste wie bisher; die uebrigen Tunnel-Routen bleiben Admins vorbehalten. Doku:
  API-Referenz (DE+EN).
- **Monitoring: E-Mail-Alert-Regeln ohne eigenen `smtp_host` nutzen den Relay aus `SMTP_HOST` (R-0634):** Compose
  reicht `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` und `SMTP_FROM` jetzt auch an den Dienst
  `monitoring`, wie an `server` und `scheduler`. Bisher fehlten sie dort, und jede E-Mail-Regel ohne eigenen
  `smtp_host` scheiterte mit `SMTP not configured (SMTP_HOST missing)`, obwohl die Doku den Relay aus der Umgebung
  nennt. Ist `SMTP_HOST` gesetzt, verschicken diese Regeln danach ueber den globalen Relay, mit derselben Pruefung von
  Zertifikat und Hostnamen wie der Notification-Hub. Doku: Betrieb & Konfiguration (DE+EN).
- **Backup: `env.sanitized` verliert keine Zeilen mehr bei Bytes ausserhalb UTF-8 oder einem NUL-Byte (R-0559):**
  `scripts/backup.sh` filterte die `.env` unter der Locale des Aufrufers. `grep` haelt eine Zeile mit einem Byte, das
  diese Locale nicht dekodieren kann (etwa ein Latin-1-Umlaut unter einer UTF-8-Locale), fuer binaer und liess sie aus,
  bei einem NUL-Byte alle Zeilen; ein Fehler von `grep` blieb unbemerkt, und das Backup lief mit einer gekuerzten oder
  leeren `env.sanitized` durch. Jetzt liest `backup.sh` die `.env` Byte fuer Byte (`LC_ALL=C awk`):
  `env.sanitized` ist die `.env` ohne die `CA_ROOT_PASSPHRASE`-Zeilen, und ein Fehler beim Filtern bricht das Backup
  ab, ohne ein Archiv zu hinterlassen. Den Schluessel erkennt es wie das Diagnose-Bundle auch mit vorangestelltem
  `export`, mit Leerraum um den Trenner und mit `:` statt `=` als Trenner (`export CA_ROOT_PASSPHRASE=...`,
  `CA_ROOT_PASSPHRASE = ...`, `CA_ROOT_PASSPHRASE: ...`); ein anderer Schluessel wie `CA_ROOT_PASSPHRASE_OLD` bleibt
  stehen. Entfernt werden auch auskommentierte Zeilen (`#CA_ROOT_PASSPHRASE=...`), Zeilen mit BOM oder
  Unicode-Leerraum (etwa NBSP) vor dem Schluessel oder NBSP vor dem Trenner, die compose ebenso liest, und die
  Folgezeilen eines Werts in Anfuehrungszeichen ueber mehrere Zeilen bis zum schliessenden Anfuehrungszeichen, ohne
  eines bis zum Dateiende.
- **Diagnose-Bundle: Maskierung kennt die Token-Formen der Access-Logs und weitere Schreibweisen der `.env`:**
  `scripts/diagnostics.sh` maskiert jetzt auch API-Keys und Token als Query-Parameter (`api_key`, `token`,
  `access_token`, Gross-/Kleinschreibung egal), das Token im Pfad `/hooks/trigger/<token>` und
  Provisionierungs-Token `adminhelper_prov_...`; die Regel fuer `ah_...` entfaellt, kein Token des Projekts traegt
  dieses Praefix. Die Secrets der `.env` erkennt es in diesen Schreibweisen: Schluessel auch als `export KEY=...`,
  `KEY = ...` oder `KEY: ...` (in `env.sanitized` wie in den Logs), Werte in einfachen oder doppelten
  Anfuehrungszeichen, mit `$$` (auch als `$` gesucht, wie compose es einsetzt) oder einem Kommentar hinter ` #`; steht
  ein Schluessel mehrfach da, wird jeder Wert maskiert. Es liest die `.env` Byte fuer Byte und maskiert einen Wert
  auch hinter einem Byte ausserhalb UTF-8 ganz. Einen Schluessel findet es wie compose auch hinter einem BOM oder
  Unicode-Leerraum (etwa NBSP oder EM SPACE) und mit NBSP vor dem Trenner. Auskommentierte Zeilen dieser Schluessel
  (`#KEY=...`, auch `# export KEY = ...`) stehen in `env.sanitized` als `#KEY=<redacted>`, die der Host-Schluessel mit
  `--mask-hosts` als `#KEY=<masked>`; in den Logs sucht es ihre Werte nicht, eine auskommentierte Zeile ist keine
  Konfiguration. Die Werte liest es so, wie compose sie liest: Escape-Sequenzen in doppelten
  Anfuehrungszeichen (`\"`, `\\`, `\n`, `\t`, `\$`, Oktal `\0nnn` und weitere) und `\'` in einfachen, Leerraum
  zwischen Trenner und Wert (auch NBSP) und am Ende eines Werts ohne Anfuehrungszeichen (auch Unicode-Leerraum), Werte
  in Anfuehrungszeichen ueber mehrere Zeilen. Jede Zeile eines solchen Werts, die nicht nur aus Leerraum besteht,
  wird in den Logs maskiert, in `env.sanitized` steht `KEY=<redacted>` ohne die Folgezeilen. `report.txt` laeuft jetzt
  wie die Logs durch die Maskierung.
- **ca-issuer: kein Zertifikat ueberlebt mehr sein Zwischenzertifikat (R-0666):** Der `ca-issuer` stellte Zertifikate
  mit voller Laufzeit aus, auch wenn das signierende Zwischenzertifikat frueher ablief, und signierte mit einem
  abgelaufenen Zwischenzertifikat still weiter Zertifikate, die kein Client mehr annimmt. Jetzt endet jedes
  Zertifikat spaetestens mit seinem Aussteller (Client- und Server-Zertifikate mit dem Zwischenzertifikat,
  Zwischenzertifikate mit der Root); kurz vor dem Ablauf eines Zwischenzertifikats werden neue Zertifikate also
  kuerzer. Ist das Zwischenzertifikat eines Scopes abgelaufen oder noch nicht gueltig, antworten `/enroll` und
  `/renew` mit HTTP 503 („the issuing intermediate certificate of scope '…' is expired or not yet valid; see the
  ca-issuer log“) und schreiben eine Zeile auf ERROR ins Log; der Einmal-Token bleibt unverbraucht. Eine Erneuerung
  bekommt die volle Laufzeit ihrer Zielgruppe (90 Tage, Browser 365 Tage), auch wenn das alte Zertifikat gekuerzt
  war. Ab 180 Tagen vor dem Ablauf eines Zwischenzertifikats warnt der `ca-issuer` beim Signieren einmal je Tag und
  Scope im Log (Logger `ca-issuer.issuer`, „intermediate '…' expires on … (N days left)“). Doku: Betrieb (DE+EN).
- **ca-issuer: prueft die PKI beim Start (R-0666):** Der `ca-issuer` lud Root und Zwischenzertifikate beim Start ohne
  jede Pruefung, auch ein abgelaufenes, ein von einer fremden Root signiertes oder eines neben fremdem Schluessel oder
  fremder Kette. Jetzt prueft er bei jedem Start, auch direkt nach dem ersten: `root.crt` selbstsigniert und gueltig,
  je Scope `<scope>.crt` von `root.crt` signiert und gueltig, `<scope>.key` der passende Schluessel und
  `<scope>-chain.pem` genau Zwischenzertifikat und Root (geparst verglichen, Zeilenenden zaehlen nicht). Bei einem
  Verstoss startet er nicht und nennt Datei, Scope und Grund („PKI hierarchy invalid — …“); das gilt auch fuer eine
  Host-Uhr vor dem `notBefore` der Root oder eines Zwischenzertifikats. Root und Zwischenzertifikate mit weniger als
  180 Tagen Restlaufzeit stehen bei jedem Start als WARNING im Log (Logger `ca-issuer.storage`, „intermediate '…'
  expires on … (N days left)“, „root expires on …“ mit dem Hinweis, dass eine neue Root ein neues Enrollment aller
  Clients bedeutet). Doku: Betrieb (DE+EN).
- **Desktop: ein gescheiterter Abruf der Verbindungen leert die Liste nicht mehr (R-0658):** Scheitert in einem
  Server- oder Sync-Workspace der Abruf der Verbindungen, etwa beim Seitenwechsel oder im Sync-Takt waehrend eines
  Netzausfalls, bleibt die zuletzt geladene Liste stehen, wenn sie aus derselben Quelle stammt (derselbe Server und
  Benutzer, dieselbe Sync-URL), statt zu verschwinden. Die Liste einer anderen Quelle bleibt nie stehen.
  „Verbindungen“ zeigt den Fehler mit „Erneut versuchen“ und bei stehen gebliebener Liste den Hinweis, dass es die
  zuletzt geladene ist; waehrend des Ladens zeigt die Seite „Lade…“ statt „Noch keine Verbindungen angelegt“. Auch
  das Dashboard zeigt den Fehler mit „Erneut versuchen“ und unter „Zuletzt genutzt“ waehrend des Ladens „Lade…“ statt
  „Noch keine Verbindungen genutzt“.
- **Desktop: der RDP-Start gibt Bildschirmgroesse und Skalierungsfaktor mit (R-0659):** Unter Linux nimmt der
  Fenstermodus „Eingepasst“ 85 % der Bildschirmbreite und 85 % der Hoehe abzueglich 80 Pixel, mindestens 1024x720,
  statt immer 1088x720, die Skalierung „Automatisch“ erkennt einen HiDPI-Bildschirm, und „HiDPI“ waehlt den Faktor
  nach dem Bildschirm (`/scale:140` oder `/scale:180`) statt immer `/scale:180`. Auf einem HiDPI-Bildschirm nicht
  verifiziert.
- **Desktop: ohne gespeicherte Sprache gilt die Systemsprache (R-0660):** Ist noch keine Sprache gespeichert, etwa
  nach einer frischen Installation, laeuft die Desktop-UI in der Systemsprache: Deutsch auf einem deutschen System,
  sonst Englisch. Bisher lief sie nach dem Laden der Einstellungen immer englisch. Der Einstellungsdialog zeigt diese
  Sprache; bisher zeigte er „Deutsch“, und Speichern einer beliebigen Einstellung schaltete ungewollt auf Deutsch.
  Dieselbe Regel gilt schon vor dem Laden der Einstellungen („Lade…“) und fuer die ganze UI, wenn das Laden
  scheitert; auf einem System in einer anderen Sprache als Deutsch oder Englisch lief die UI dort bisher deutsch.
- **Desktop: „Loeschen“ im Verbindungs-Editor fragt nach (R-0661):** Bevor der Editor eine Verbindung entfernt, im
  Server-Modus auf dem Server, und bei RDP ein gespeichertes Passwort, fragt er mit dem Namen der Verbindung nach;
  „Abbrechen“ oder Escape laesst sie stehen und den Editor offen. Bisher loeschte der Knopf sofort.
- **Desktop: Speichern der Einstellungen startet die Benachrichtigungen nicht mehr neu (R-0663):** Bisher stoppte
  jedes Speichern der Einstellungen in einem Server-Workspace den Benachrichtigungs-Stream, leerte den Feed und
  startete beides neu; der Feed flackerte, und Meldungen aus dieser Luecke kamen ohne OS-Benachrichtigung. Neu
  gestartet wird nur, wenn Server oder Benutzer wechseln.
- **SSRF-Schutz: eine URL mit einem einzelnen Surrogat wird abgelehnt (Server und Monitoring, R-0606):** Eine URL
  mit einem einzelnen Surrogat, etwa aus einem JSON-Payload, wird als unlesbar abgelehnt, statt eine Exception zu
  werfen; HTTP-Check, Alert-Webhook und `http_get`/`http_post` der Hooks melden ihre gewoehnliche Ablehnung.
- **Web-Panel: mehrere Tabs erneuern die Sitzung nacheinander (R-0649):** Alle Tabs teilen das Refresh-Cookie, das
  Panel buendelte Erneuerungen aber nur innerhalb eines Tabs. Erneuerten zwei Tabs die Sitzung gleichzeitig, etwa
  beim Wiederherstellen des Browsers, schickten beide denselben Refresh-Token; der Server wertete den zweiten als
  Wiederverwendung und beendete alle Sitzungen des Benutzers, auch die des Desktops. Jetzt laufen die Erneuerungen
  aller Tabs nacheinander (Web Locks), und ein spaeterer Tab schickt schon das neue Cookie. Auch die Abmeldung laeuft
  unter dieser Web Lock: Sie macht das gemeinsame Cookie ungueltig, und eine Erneuerung, die ein anderer Tab zugleich
  mit ihm schickte, galt ebenso als Wiederverwendung, etwa wenn der Browser nach Ablauf der Inaktivitaetszeit mehrere
  Tabs wiederherstellt und jeder sich abmeldet. Ohne Web Locks, etwa ausserhalb von HTTPS, buendelt das Panel weiter
  nur im Tab, und die Abmeldung geht sofort hinaus. Doku: Web-UI fuer Entwickler (DE+EN).

## [0.46.0] - 2026-10-22

### Added

- **Desktop: Workspaces — mehrere Server, Sync-Quellen und lokale Verbindungen nebeneinander (R-0431):** Ein Workspace
  hat eine feste Art (Server, Sync oder Lokal), einen Namen, eine Farbe und bei Server und Sync eine URL; mehrere je
  Art sind erlaubt. Jeder laeuft in einem eigenen Fenster und Prozess mit eigener Anmeldung, eigenem Tunnel, eigener
  Geraete-Identitaet, eigenen gespeicherten RDP-Passwoertern, eigenen Verbindungen und eigener Logdatei (die
  migrierten Workspaces teilen sich die Eintraege im System-Schluesselbund von vorher); derselbe Workspace laeuft nie
  zweimal. `adminhelper` startet den Launcher: Der Picker listet die Workspaces mit Farbe, Art, Host und „geoeffnet“,
  waehlt den zuletzt genutzten vor (Enter oeffnet ihn), legt Workspaces an und bearbeitet oder loescht geschlossene;
  sobald der geoeffnete laeuft, schliesst er sich, und „Workspaces…“ im Fenster holt ihn zurueck. Loeschen widerruft
  bei einem Server-Workspace zuerst das Geraet am Server und nimmt dann die Daten, RDP-Passwoerter und
  Portkarten-Eintraege des Workspace mit; bei Lokal nennt die Bestaetigung den Datenverlust. Kenntlich ist ein
  Workspace am Fenstertitel „<Name> — AdminHelper“, am Chip oben in der Sidebar, an einem Farbstreifen am Fensterrand,
  an Rueckfragen, an OS-Benachrichtigungen („[<Name>] …“) und unter Linux am Titel des RDP-Fensters. Eine Verbindung
  an eine Loopback-Adresse (`127.0.0.1`, `localhost`, …), deren Port die Portkarte dem Tunnel eines anderen Workspace
  gibt, lehnt der Desktop ab; die Meldung kommt vor jeder Passwortabfrage und sagt, den Tunnel dieses Workspace zu
  starten. Die Grenzen dieser Pruefung nennt die Entwickler-Doku. Neue Tauri-Commands `workspace_context`,
  `list_workspaces`, `save_workspace`, `delete_workspace`, `open_workspace` und `open_launcher`. Doku: Desktop fuer
  Entwickler (DE+EN), README, DEVELOPMENT.
- **Desktop: gespeicherte RDP-Passwoerter unter Windows auch fuer Tunnelziele (R-0431):** Unter Windows liegt ein
  gespeichertes RDP-Passwort jetzt im Credential Manager im Namensraum der App, je Workspace und Verbindung, statt
  dauerhaft unter `TERMSRV/<Adresse>`. Fuer einen Start schreibt der Desktop `TERMSRV/<Adresse>` fuer die Adresse, die
  mstsc oeffnet, bei einem Tunnel also `127.0.0.1:<lokaler Port>`, nur fuer diese Anmeldesitzung, und loescht den
  Eintrag 60 s nach dem Start wieder. Einen eigenen Eintrag ohne Kennzeichen der App (etwa per `cmdkey`) laesst er
  stehen, und mstsc nimmt ihn; vor einem Start auf diesen Rechner loescht er die Eintraege dieser Adresse. Ein zweiter
  Start einer anderen Verbindung, der denselben Eintrag braeuchte, wird in dieser Zeit mit der Restzeit abgelehnt. Ein
  migrierter Workspace uebernimmt das Passwort einer frueheren Version aus `TERMSRV/<Adresse>` beim ersten Start einer
  Verbindung ohne Tunnel und loescht den alten Eintrag; ein mstsc-Start von Hand auf diese Adresse fragt danach nach
  dem Passwort. „Passwort merken“ im Passwort-Dialog startet ueber das gespeicherte Passwort, ein nur getipptes fragt
  mstsc wie bisher selbst ab. Mit mstsc unter Windows noch nicht verifiziert; die Entwickler-Doku hat dafuer eine
  Pruefanleitung. Doku: Desktop fuer Entwickler (DE+EN), README.
- **Monitoring: Standard-Template „Host Ping“ (R-0424):** Ein sechstes mitgeliefertes Standard-Template pingt den
  Hostnamen des Servers jede Minute (`ping`, Timeout 3 s, `critical` nach 3 Fehlschlaegen in Folge, etwa 3 Minuten)
  und meldet den Ausfall eines Hosts damit auch ohne Agent. Es gehoert zu keinem der beiden „— Standard“-Templates,
  wird nie vorgeschlagen und nur von Hand zugewiesen; bestehende Installationen bekommen es beim naechsten Start des
  Monitoring-Dienstes. Gedacht ist es fuer Hosts, die der Monitoring-Dienst per ICMP erreicht, nicht nur ueber FRP;
  ein IPv6-Literal als Hostname nimmt der `ping`-Check nicht an. Steht der Host Ping auf `critical`, bleiben alle
  uebrigen Alarme des Servers stumm, auch der Heartbeat (`agent_ping`); ein `critical` Heartbeat schaltet den Host
  Ping dagegen nicht stumm. Faellt der Host aus, meldet also nur der Host Ping; ist er zurueck und der Agent weiter
  stumm, meldet der Heartbeat seinen Ausfall nach seiner naechsten Pruefung. Meldet sich der Agent bis zu dieser
  Pruefung wieder, entwarnt der nie gemeldete Ausfall still; der Status aus der Zeit des Ausfalls wird nicht gemeldet.
  Als Host Ping zaehlt nur der Check aus diesem Template: Ein von Hand angelegter `ping`-Check, etwa auf ein Gateway,
  schaltet nichts stumm. Doku: Admin- und Entwickler-Doku Monitoring (DE+EN).
- **Monitoring: Sammelmeldung, wenn mehrere Agents zugleich stumm werden (R-0424):** Werden 3 oder mehr Agents stumm
  (`agent_ping` auf `critical`), bekommt jeder Kanal eine Meldung statt einer je Server, sobald der dritte stumm ist;
  ihre Rueckkehr wird ebenso gesammelt. Weniger als drei werden wie bisher einzeln gemeldet, aber erst, wenn ihr
  Statuswechsel 5 Minuten zurueckliegt, hoechstens bis eine Minute vor der naechsten Pruefung: beim Standard-Heartbeat
  (Intervall 5 Minuten) nach 4 Minuten, bei einem Intervall von 1 Minute sofort, dazu bis zu 30 s Takt. So ist ein
  Ausfall gemeldet, bevor die naechste Pruefung den Agent wieder auf `ok` setzen kann. Die Heartbeats meldet dafuer ein
  Hintergrund-Job (`system:agent-alert-bundle`, alle 30 s), nicht mehr der `agent_ping` selbst. Gesammelt wird je
  Kanal: Eine Alert-Regel, die drei oder mehr der Agents trifft, sendet eine Nachricht
  (`[AdminHelper Monitor] CRITICAL: <n> agents not reporting` bzw.
  `[AdminHelper Monitor] RECOVERY: <n> agents reporting again`, eine Zeile je Agent, hoechstens 50) und schreibt je
  Agent eine Zeile ins Alert-Log; im Webhook sind `check_name` und `server_id` dann `null`, die Agents stehen im neuen
  Feld `members`. Die Glocke bekommt je Stufe einen Eintrag „Agents not reporting (n)“ bzw. „Agents reporting again
  (n)“ mit einer Zeile je Server, die der Nutzer sehen darf und die eine seiner Regeln erfasst. Der Server nimmt dafuer
  in `POST /api/internal/events` das Feld `source_ids` (bis 500 Server-IDs, nicht zusammen mit `source_id`) und feuert
  `alert.triggered` bei einer solchen Meldung einmal je Server. Die E-Mail einer persoenlichen Regel nennt nur die
  Server, die eine Regel mit E-Mail erfasst, und zaehlt nur diese (Telegram ebenso); erfasst keine solche Regel einen
  der Server, geht keine Mail (neue Spalten `title`/`body` in `notification_outbox`, Migration `a7c9e1b3d5f2`).
  Wartungsfenster und Host-down-Unterdrueckung gelten weiter; nach ihrem Ende zaehlt ein Heartbeat erst nach seiner
  naechsten Pruefung wieder mit, sein Status aus der Zeit davor wird nicht gemeldet. Weil die Heartbeats nicht alle
  zugleich geprueft werden, koennen danach mehrere Meldungen kommen statt einer. Monitoring und Server kommen im
  selben Release; ein aelterer Server stellt die Sammel-Eintraege der Glocke nur Admins zu. Doku: Admin- und
  Entwickler-Doku Monitoring, Entwickler-Doku Server, Hooks und API-Referenz (DE+EN).
- **Monitoring: Check-Typ `system_state` fuer den Systemzustand eines Linux-Hosts (R-0423):** Der Agent schickt ab
  Report-Version 3 unter Linux den Block `system_state`: Neustart noetig (`/var/run/reboot-required` bzw.
  `needs-restarting -r`), Uhr synchronisiert (`timedatectl show`), offene Sicherheits-Updates
  (`apt-get -s dist-upgrade` bzw. `dnf -C -q updateinfo list --security`, nur aus den lokalen Paketlisten, ohne Netz,
  hoechstens einmal je Stunde) und OOM-Kills seit dem letzten erfolgreich gesendeten Report (`/proc/vmstat`; in
  einem Container, der dort die Kills des ganzen Hosts saehe, der Zaehler des eigenen cgroup aus
  `/sys/fs/cgroup/memory.events`, ohne cgroup v2 dort kein Wert). Der neue Push-Check `system_state` ist `warning`, sobald ein Punkt ein Problem zeigt, nie `critical`; die Uhr bewertet
  er erst ab 15 Minuten Uptime. Je Punkt schaltet ein Schalter (`check_reboot`, `check_time_sync`,
  `check_security_updates`, `check_oom`, je Default `true`, nur `true` oder `false`) die Bewertung ab. Ohne den Block
  (aeltere Agents, Windows) oder ohne einen einzigen brauchbaren Punkt darin bleibt der Check `ok` mit „Not evaluated:
  no system state in report“. Ein OOM-Kill steht nur in einem Report und meldet deshalb nur mit `consecutive_fails` 1.
  Im Check-Formular und im Template-Editor des Desktops stehen die vier Schalter als Kontrollkaestchen, und die Wahl
  des Typs schlaegt `consecutive_fails` 1 vor (aenderbar; verlaesst man den Typ mit der 1, kehrt der Wert von vorher
  zurueck). Das Server-Dashboard des Desktops zeigt den Check in der neuen Sektion
  „Systemzustand“: je Problem eine Pille, ausgeklappt die vier Punkte mit Wert oder „nicht ermittelt“, ohne den Block
  „Nicht bewertet“. Nicht verifiziert: ob Debian und Proxmox VE `/var/run/reboot-required` bei
  einem Kernel-Update anlegen, der Weg der RPM-Distributionen und der OOM-Zaehler im LXC unter Proxmox VE (in
  Docker geprueft). Doku: Monitoring-Administration, Entwickler-Doku Agent und Monitoring (DE+EN).
- **Monitoring: `agent_resources` bewertet Swap, Inodes und Load je CPU (R-0423):** Neben CPU, RAM, Platten und
  Temperaturen bewertet der Check die Swap-Belegung (`swap_warn`/`swap_crit`, Default 80/95 %, nur mit Swap-Geraet),
  die Inode-Belegung je Platte (`inode_warn`/`inode_crit`, 80/90 %) und die Load je CPU, `load_5m` geteilt durch die
  Zahl der logischen CPUs (`load_warn`/`load_crit`, 1.5/3.0). Swap und Inodes haben die Hysterese der uebrigen
  Prozentwerte, die Load hat keine. Die Defaults gelten auch fuer bestehende Checks ohne diese Schluessel. Die Werte
  meldet der Agent ab Report-Version 3 und nur unter Linux; fuer aeltere Agents und Windows-Hosts bleiben die drei
  unbewertet, ohne `unknown`. In einem Container (`host.virtualization` mit der Rolle `guest` und `lxc`, `docker`,
  `openvz` oder `rkt`, dieselbe Erkennung wie beim OOM-Zaehler) bleibt die Load je CPU unbewertet: `load_5m` ist
  dort die Load des Hosts, die Zahl der CPUs kann die des Containers sein; die Check-Details tragen dann
  `load_rated: false`. Ein Host, eine VM und ein Report ohne `host` werden wie bisher bewertet. Die Check-Details
  tragen dazu `swap`, `swap_total_mb`, `swap_used_mb`, `cpu_count`, `load_per_cpu` und je Platte `inodes_percent`.
  Der Desktop zeigt die Werte in der Live-Sektion: Swap als Ring (nur mit Swap-Geraet), die Load je CPU als Pille
  „Load 0.42/CPU“ (im Container grau mit „im Container nicht bewertet“), je Platte die freien GB und die
  Inode-Belegung, eine Platte aus `ignore_mounts` grau mit „ignoriert“. Die Farben von Ringen, Pillen und Balken
  kommen jetzt aus der Bewertung des Checks (`problems` in den Details, also mit Mindest-GB, Schwellen je Mount und
  Hysterese; volle Inodes faerben die Platte mit), nicht mehr aus den Schwellen der Konfiguration; nur Details ohne
  `problems` rechnet er wie bisher aus der Konfiguration. Doku: Monitoring-Administration, Entwickler-Doku Agent und
  Monitoring (DE+EN).
- **Monitoring: Standard-Template „Linux Server — Standard“ in Version 3 (R-0423):** Der Check System Resources
  bewertet darin zusaetzlich Swap (80/95 %), Inodes (80/90 %) und die Load je CPU (1.5/3) und die Belegung einer
  Platte erst unter 20 GB frei (`disk_min_free_gb`); neu ist der Check System State (`system_state`, `warning`,
  `consecutive_fails` 1, weil ein OOM-Kill nur in einem Report steht); Service Health beschreibt die neue Aufteilung
  (fehlgeschlagene Dienste `critical`, andere fehlgeschlagene sowie enabled, aber inaktive Units `warning`). Ein
  unveraendertes Template folgt der neuen Version beim Start automatisch, auch eines von vor den Template-Versionen:
  Jeder zugewiesene Server bekommt den Check System State und sein Check System Resources die neuen Schwellen,
  angepasste Felder einzelner Checks bleiben. Eine angepasste Konfiguration von System Resources bekommt die neuen
  Schluessel nicht; fehlen sie, nimmt der Check dieselben Werte. Ein angepasstes Template bietet die Version als
  Update an. „Windows Server — Standard“ bekommt diese Aenderungen nicht. Doku: Monitoring-Administration (DE+EN),
  README.
- **Monitoring: Vorschlag passender Standard-Templates im Monitoring-Tab (R-0421):** Der Agent meldet im Report den
  Block `host`: Betriebssystem, Plattform, Virtualisierung und die Subsysteme Docker, ZFS und Proxmox, deren Programm
  `docker`, `zpool` bzw. `pvesh` im Suchpfad liegt. Daraus zeigt der Monitoring-Tab eines Servers unter
  „Vorgeschlagen:“ passende Standard-Templates (Linux: „Linux Server — Standard“, Windows: „Windows Server —
  Standard“, dazu „Docker Host“, „ZFS Storage“, „Proxmox Host“), je mit Kontrollkaestchen. „Zuweisen“ weist die
  ausgewaehlten zu, „Ignorieren“ merkt sich die Ablehnung je Server und Template; das ist vorerst nicht rueckgaengig
  zu machen, von Hand zuweisen laesst sich das Template weiter. Vorgeschlagen wird nur ein vorhandenes, dem Server
  nicht zugewiesenes und nicht ignoriertes Standard-Template; automatisch zugewiesen wird nichts. Agents vor dieser
  Version liefern keinen Vorschlag. Neu: `GET /templates/suggestions/{server_id}` und
  `POST /templates/suggestions/{server_id}/dismiss` (204), Tabellen `monitor_host_facts` und
  `monitor_template_suggestion_dismissals` (Migration `b9d1f3a5c7e9`). Doku: Admin- und Entwickler-Doku Monitoring
  (DE+EN).
- **Desktop: Template-Checks zuruecksetzen und wiederherstellen, Updates der Standard-Templates (R-0420):** Im
  Dashboard eines Servers traegt ein angepasster Template-Check das Badge „angepasst“ (Tooltip: die Felder) und die
  Aktion „Auf Template zuruecksetzen“, die nach einer Rueckfrage alle Felder auf die Template-Werte setzt
  (`POST /checks/{id}/reset`). Der Monitoring-Tab des Servers zeigt je Zuweisung „N geloeschte Checks
  wiederherstellen“ und legt sie auf Klick neu an (`POST /templates/{id}/assign/{server_id}/restore`, Zaehler
  `removedChecks` in `GET /templates/assignments/{server_id}`). Bringt ein Release eine neuere Version eines
  Standard-Templates mit, dessen Definitionen angepasst sind, zeigt die Template-Liste dort „Update verfuegbar“
  (in diesem Release fuer „Linux Server — Standard“ in Version 3, „Windows Server — Standard“ und „Proxmox Host“ in
  Version 2); das oeffnet einen Vergleich der aktuellen mit den mitgelieferten Check- und Alert-Definitionen, und
  „Uebernehmen“ ersetzt alle Definitionen des Templates, auch die Alert-Definitionen, waehrend angepasste Felder
  einzelner Checks bleiben (`GET`/`POST` auf `/templates/{id}/builtin-update`, Felder `builtinVersion`,
  `builtinEdited`, `builtinUpdateAvailable`). Doku: Admin- und Entwickler-Doku Monitoring (DE+EN).
- **Web: Registrierungs-Token in der Benutzerliste (R-0396):** Je Benutzer stellt ein Admin mit
  „Registrierungs-Token“ ein Einmal-Token aus: Gueltigkeit waehlen (10 Minuten, 1 Stunde oder 24 Stunden;
  voreingestellt 10 Minuten), dann zeigt der Dialog das Token genau einmal mit Kopieren, seinem Ablauf in
  Ortszeit und dem Hinweis, dass es im Desktop unter „Geraet mit Token registrieren“ eingeloest wird.
  Schliessen verwirft das Token. `POST /api/enrollment/token/for` nimmt dafuer `ttl_minutes` (1 bis 1440,
  Standard 10), beide Token-Routen liefern `expiresAt`.
- **Desktop: Statuszeile der Geraete-Identitaet (R-0240):** Ist das Geraet registriert, zeigen die
  Einstellungen im Modus `server` den Namen und den Ablauf des Geraete-Zertifikats, etwa „Registriert als
  admin bis 13.01.2027“. Bleiben 14 Tage oder weniger, sagt die Zeile dazu, dass die automatische Erneuerung
  beim Anmelden bisher nicht gelungen ist; ein abgelaufenes oder nicht lesbares Zertifikat meldet sie als
  Warnung mit dem Weg ueber Zuruecksetzen und neuen Token. Dafuer liefert der neue Command `device_identity`
  Name (CN) und Ablauf.
- **Geraete einzeln widerrufen (R-0224):** Ein Admin listet die Geraete eines Benutzers mit
  `GET /api/users/{id}/devices` und widerruft eines mit `DELETE /api/users/{id}/devices/{device_id}`; die uebrigen
  Geraete des Benutzers bleiben. Ein Geraet widerruft sich selbst mit `POST /api/enrollment/self/revoke`, ausgewiesen
  durch sein Client-Zertifikat. Jeder Widerruf steht im Audit-Log (`device.revoked`).
- **Builder-Profil des Workers (Team-Plan 4b):** `scripts/dev/builder-home.sh setup|token|status`
  richtet ohne sudo ein eigenes HOME fuer den Loop unter Kevins Benutzer ein (CLI-Pin, Settings des
  Runners mit Deny-Regeln mit absolutem Pfad fuer die privaten Verzeichnisse in Kevins HOME (`~/.ssh`,
  `~/.config/gh`, `~/.claude`, …) und die privaten Dateien jedes Checkouts, Tools-venv, eigene Test-DB,
  Klon ohne Push). `ledger-loop.sh start --profile kevin` startet den Loop darin in tmux mit `env -i`
  und `</dev/null`, `status --profile kevin` liest seinen Stand. Die Sessions duerfen sechs offizielle
  Doku-Domains abrufen (`WebFetch(domain:…)`) und `echo` nutzen (R-0237); `runner-env.sh`
  nimmt das Token nur in der Form `sk-ant-oat01-…` und `pve.env`-Schluessel nur so, wie `vm.py` sie
  nimmt (R-0232).

- **Desktop: Geraet aus den Einstellungen registrieren (R-0212):** Im Modus `server` zeigen die
  Einstellungen einem Geraet ohne Identitaet ein Feld fuer den Einmal-Token vom Admin; nach der
  Registrierung startet der Tunnel. Wer ohne erzwungenes mTLS angemeldet ist, muss sich dafuer nicht
  mehr abmelden. Ein Geraet mit Identitaet sieht dort wie bisher nur das Zuruecksetzen.
- **`Assertion-Aenderung:` im Ledger (R-0206):** eine Task kann eine absichtlich geaenderte
  Assertion in einem bleibenden Test oder Test-Helfer ankuendigen (`<datei>::<test> — <Grund>`).
  `review.sh diff-scan` laesst dann genau diese Aenderung durch, wenn der Test mindestens so viele
  Assertions hinzubekommt, wie er verliert; `task-close.sh` sperrt eine Ankuendigung, die erst mit
  der Task selbst kommt, und `ledger.sh lint` prueft die Form. Als Ledger gelten nur noch
  `tasks/*.md` ohne `tasks/README.md` und `tasks/templates/` — das schliesst auch einen aelteren
  Weg an `Test-Loeschung:` vorbei.

- **commit-msg-Hook (R-0197):** `scripts/dev/hooks/commit-msg` faehrt `review.sh sec --message`
  und sperrt einen Token in der Commit-Nachricht schon beim Commit. Dazu meldet `sec` die Zeile
  nach „\ No newline at end of file“ richtig und erkennt weitere Formen eines Proxmox-Tokens
  (PBS mit Doppelpunkt, URL-kodiert, Secret hinter einem Schluesselnamen; R-0194, R-0196), und
  `ledger.sh lint` meldet auch Huelle und Ausgabe eines Werkzeugaufrufs als Rest (R-0195).

- **`review.sh sec` erkennt Token-Muster (R-0183):** eine hinzugefuegte Zeile mit einem
  Proxmox-API-Token (`USER@REALM!TOKENID=UUID`), einem GitHub-Token (`ghp_`, `gho_`, `ghu_`,
  `ghs_`, `ghr_`, `github_pat_`) oder einem `sk-ant-`-Schluessel sperrt den Commit, den Push und
  den CI-Job „Public repo guard"; genannt wird nur Datei:Zeile, nie der Inhalt. Ueber eine
  Spanne (pre-push, CI) prueft es auch die Commit-Nachrichten und nennt dann nur den Commit.
  Eine Mindestlaenge und ein Rumpf aus hoechstens zwei verschiedenen Zeichen (`xxxx…`) lassen
  die Platzhalter in Code, Doku und Tests durch.

- **`ledger.sh lint` meldet Werkzeug-Reste (R-0165):** Reste eines Werkzeugaufrufs, die ein
  planender Agent in Ledger oder Spec hinterliess, sind ein Lint-Fehler mit Datei:Zeile.

- **Der Worker (Stufe 7a, R-0010, R-0108, R-0164, R-0167, R-0170):** `scripts/dev/ledger-loop.sh`
  baut freigegebene Ledger Task fuer Task als `adminhelper-runner` in dessen Klon, jedes Ledger in
  seiner Lane; Kevin startet ihn in tmux mit einer expliziten Ledger-Liste. Je Task eine frische
  Bau-Session (`claude -p` mit dem Text von `/build-task`, nur die Runner-Settings, `dontAsk`,
  Deckel fuer Zeit, Turns und Budget); geschlossen wird ausserhalb der Session mit
  `task-close.sh --review auto --round <n>`. Der Loop zaehlt die Runden selbst, raeumt nach einem
  Abbruch auf (`aborted.diff`, restore, neue Dateien einzeln), setzt `[?]` mit dem Grund und das
  Ledger auf `blockiert`, haelt an Lauf-Deckeln (`--max-hours`, `--max-tasks`, `--max-budget-usd`
  samt Reviewer-Kosten, `--max-ready`) und am Nutzungslimit an und endet mit einer Stopp-Klasse
  und `summary-<datum>.md`. Ein fertiges Ledger uebergibt er als PR-Text (`review.sh pr-body`) und
  Git-Bundle; Push und PR bleiben Kevins. Neu sind `/build-task`
  (`.claude/skills/build-task/SKILL.md`) und `scripts/dev/scratch.sh`; die Runner-Settings
  verbieten Edits unter `tasks/` und erlauben einen Scratch-Ordner nur ueber `scratch.sh`;
  `task-close.sh` nimmt im autonomen Lauf weder ein eigenes Verdict noch ein frueheres approve an
  und druckt die Kosten des Reviewers; das Red Team prueft die Grenzen der Bau-Session;
  `ledger-loop.sh status` und die Worker-Zeile im AH-STATUS zeigen den Stand. Anleitung:
  `AUTONOMOUS.md`, „Der Worker", und `DEVELOPMENT.md`, „Der Worker".
- **CI-Sperre fuer Privates (R-0123):** Der neue CI-Job „Public repo guard (review.sh sec)" faehrt
  `scripts/dev/review.sh sec --range` ueber jeden Commit eines Pull Requests bzw. Pushs auf `main` —
  dieselbe Sperre wie die lokalen Commit-Hooks (privater Plan, SEC-Ledger, Dedup-Key eines
  Sicherheitsfunds, `.devenv.sh`, `settings.local.json`), fuer alles, was an ihnen vorbeigeht. `sec`
  liest eine Spanne Commit fuer Commit (eine Datei, die kommt und wieder geht, zaehlt), einen Merge nur
  nach dem, was er selbst bringt; der Job braucht kein Secret und nennt nur Pfad bzw. Datei:Zeile.
  Lokal faehrt der neue Hook `scripts/dev/hooks/pre-push` dieselbe Pruefung ueber jeden Commit, den
  ein Push nach draussen bringt, und bricht den Push bei einem Treffer ab. Kevins Handgriff: den
  Check im Ruleset fuer `main` als Pflicht eintragen. Anleitung: `docs/developer/cicd.html`,
  `DEVELOPMENT.md` „pre-commit-Hook".

- **Der Reviewer als eigener Prozess (Stufe 6b, R-0155, R-0147, R-0150):**
  `task-close.sh --review auto` startet den Task-Reviewer selbst: der Runner faehrt die Probe
  (`review-probe.sh`), `scripts/dev/review-run.sh` startet `claude -p` mit dem Reviewer aus
  `scripts/dev/review-agent.md`, ohne Projekt- und Benutzer-Settings, nur mit eigenen Settings
  (`scripts/dev/review-settings.json`: lesend, im Pilot ohne Mutanten, der harness-guard als
  Hook, fail-closed) und dem Schema `scripts/dev/review-output.schema.json`,
  Modell und Deckel nach `review.sh risk`. Das Verdict (Schema-Version 2) liegt unter
  `.ah-out/review/<slug>/` und wird ueber `check-verdict --task` an Task und Tree gebunden;
  hoechstens zwei Runden, ein Prozess ohne Verdict ist Exit 74 ohne Rueckfall. Neu sind
  `review.sh log` (jede Runde mit Kosten, Turns und Dauer, als Tabelle mit Summe) und
  `scripts/dev/review-cli-probe.sh` (misst die Aufrufform gegen die CLI). Opt-in fuer den Pilot
  per Ledger-Kopf `Review: auto`; Anleitung: `DEVELOPMENT.md`, „Reviewer als Prozess".

- **Review-Pruefer ohne Modell (Stufe 6a, R-0009):** `scripts/dev/review.sh` kann jetzt
  `risk` (Risikopfad im Diff nach `scripts/dev/review-risk.txt`, daraus das Reviewer-Modell),
  `docs-pairs` (eine Doku-Seite ohne ihre andere Sprache), `contracts` (Pruefungen je
  geaendertem Pfad nach `scripts/dev/review-contracts.txt`: ein Komponenten-Test oder ein
  Wertpaar wie die FRP-Pins), `check-verdict` (ein Reviewer-Urteil gegen
  `scripts/dev/review-verdict.schema.json` und den Tree-Hash) und `pr-body` (der PR-Text als
  Checkliste aus dem Ledger). Neu ist `scripts/dev/review-probe.sh`: in einer eigenen Worktree
  prueft es, ob der neue Test ohne die Aenderung rot waere, und mit `--mutate`, ob ein Mutant die
  Tests uebersteht. `task-close.sh` faehrt `docs-pairs` und `contracts` bei jedem Abschluss und
  prueft ein Verdict ueber `check-verdict`. Anleitung: `DEVELOPMENT.md`, „Review-Pruefer
  (Ebene 0)".

- **AH-STATUS nennt die geplanten Workflows (R-0120):** Der SessionStart-Hook
  `scripts/dev/hooks/session-status.sh` druckt je Workflow mit `schedule:` eine Zeile
  `Geplant: <name> <Tag> (<n> d): <conclusion>` fuer den neuesten abgeschlossenen Lauf auf `main`
  und warnt bei einem roten Lauf (mit `gh run view <id> --log-failed`) oder einem Lauf aelter als
  8 Tage. Bisher sah zwischen zwei Wochenlaeufen keine Session, dass der Dependency Audit rot war.
  Ohne `gh` steht dort `?`, ohne Warnung. Anleitung: `DEVELOPMENT.md` „Session-Status-Hook".
- **CI prueft den Lock-Stand der Images (R-0115):** Die Test-Jobs installieren das lose
  `requirements.in`, die Images den gehashten Lock — der lose Stand laeuft dem Lock voraus, und
  ein Bruch wie der von fastapi 0.138 im Auth-Gate-Test zeigte sich nur dort. Neu fahren die Jobs
  `python-lock-server`, `python-lock-monitoring` und `python-lock-ca-issuer` die Suiten auf dem
  Python der Images gegen den Lock (`--require-hashes`, danach die Dev-Dependencies), und
  `scripts/dev/lock-pins.py` macht den Job rot, sobald ein Pin nicht in der Lock-Version
  installiert ist. Ein Lockstep-Test haelt die Python-Version jedes Jobs beim `FROM` seines
  Dockerfiles. Anleitung: `DEVELOPMENT.md` „Python-Dependencies & Lockfiles".
- **Harness-Schutz fuer /tmp und Commits (R-0098, R-0102):** Der PreToolUse-Waechter
  `scripts/dev/hooks/harness-guard.sh` verweigert in jedem Modus, auch mit gesetztem Kill-Switch,
  das Loeschen per Glob in einem geteilten Temp-Verzeichnis (`/tmp`, `/var/tmp`, `/dev/shm`,
  `$TMPDIR` und die Session-Verzeichnisse von Claude Code darin; auch ueber `find … -delete`,
  Schleifen und Pipes) — ein Reviewer hatte mit `rm -rf /tmp/tmp.*` die Fixtures aller
  Sessions geloescht. Neu ist `scripts/dev/hooks/pre-commit`: er faehrt `review.sh sec --staged`
  vor jedem Commit, nicht mehr nur in `task-close.sh`; scharf wird er je Klon mit
  `git config core.hooksPath scripts/dev/hooks`, `harness.sh status` zeigt den Stand,
  `runner-setup.sh` setzt ihn im Runner-Klon, und der Waechter verweigert seine Umgehung.
  Shell-Schluesselwoerter wie `do` und `then` verdecken vor dem Waechter keinen Befehl mehr.
  `verify.sh` gibt jedem Lauf ein eigenes `TMPDIR`, Reviewer arbeiten in einem eigenen
  Verzeichnis. Anleitung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".
- **Lane-Isolation (Harness):** eine Lane (`scripts/dev/lane.sh new <slug>`) hat jetzt, was sie
  zum Bauen braucht, und teilt mit dem Haupt-Checkout nichts mehr, woran zwei Laeufe einander
  stoeren: eine eigene `.devenv.sh` mit eigener Test-Datenbank `adminhelper_test_<slug>` und
  eigenem Venv `~/.cache/ah-venv-<slug>`, Links auf das frpc-Sidecar und auf die
  Komponenten-Venvs mit dem CI-`ruff`. `new` bricht ab, wenn der Plan nicht committet ist (auf
  `feature/<slug>`, sonst auf `main`). In `scripts/tests/run.sh` stehen `server-pytest` und
  `schemathesis` je Nutzer ueber alle seine Checkouts Schlange (`flock` auf
  `~/.cache/adminhelper-py.lock`; `AH_PY_LOCK_WAIT`, Default 3600 s, danach SKIP mit Grund;
  `AH_PY_LOCK=0` schaltet ab) — zwei Server-Suiten auf einer Box hatten einander Tabellen und
  Speicher genommen, bis zum OOM-Killer. `lane.sh done` loescht Datenbank und Venv mit und
  verweigert, solange noch ein Prozess in der Lane arbeitet. Hermetisch getestet in
  `scripts/tests/lane_test.sh`. Anleitung: `AUTONOMOUS.md` „Parallel-Betrieb",
  `DEVELOPMENT.md` „Python-Tests lokal".
- **Runner-Isolation und deterministische Gates (Harness Stufe 4):** Ein `[x]` und ein Commit
  entstehen nur noch in `scripts/dev/task-close.sh` — ausserhalb der Modell-Session: es verlangt,
  dass jede Datei der Task vollstaendig gestaged ist, faehrt das `Verify:` der Task als
  `verify.sh <komponente> --strict`, prueft mit `scripts/dev/review.sh` den Diff auf
  stummgeschaltete Tests (`diff-scan`), auf Pfade ausserhalb der Task (`scope`) und auf das, was
  nie ins oeffentliche Repo darf (`sec`), und schreibt die Summary-Zeile des Laufs als `Evidenz:`
  in den Ledger. Geschrieben wird der Ledger von `scripts/dev/ledger.sh` (`start`, `mark-done`,
  `mark-skip`, `mark-question`, `set-files`, `status`, `new-task`, `lint`) aus einer Vorlage
  `tasks/templates/task.md`. Dazu der Harness-Schutz: `scripts/dev/harness-paths.txt` nennt die
  Dateien, die die Regeln bestimmen, ein PreToolUse-Hook verweigert im autonomen Lauf jede
  Aenderung daran (auch ueber `sed -i`, `tee`, Umleitung, `cp`/`mv`, `bash -c`), und
  `scripts/dev/harness.sh off|on|status` ist der Kill-Switch. Neu ausserdem der Unix-User
  `adminhelper-runner` (`scripts/dev/runner-setup.sh`, `runner-env.sh`, `runner-settings.json`,
  `runner-redteam.sh`): eigener Klon ohne Push-Recht, eigene Test-Datenbank, eigenes Abo- und
  Proxmox-Token, `dontAsk` mit Deny-Liste — und ein Red-Team-Skript, das das beweist. Anleitung:
  `DEVELOPMENT.md`, Abschnitte „Task schliessen: `ledger.sh` und `task-close.sh`",
  „Harness-Schutz und Kill-Switch" und
  „Runner-User `adminhelper-runner`".
- **Generatoren statt Beispiele in den Testsuiten (Harness Stufe 8b):** Jeder Python-Dienst
  wird gegen seine eigene OpenAPI gefuzzt (Schemathesis, eigener `run.sh`-Schritt
  `schemathesis` und einem eigenen CI-Job ueber alle drei Dienste, Beispielzahl
  5 lokal und im PR-CI, 100 im Wochenlauf ueber `AH_SCHEMATHESIS_EXAMPLES`),
  einmal je Authentifizierungs-Kontext. Dazu drei
  Hypothesis-Ziele — FRP-TOML-Round-Trip, VictoriaMetrics-Line-Protocol und der
  SSRF-Guard gegen ein Orakel aus dem `ipaddress`-Modul —, ein Postgres-Concurrency-
  Test fuer `execute_check` (der `with_for_update` ist auf SQLite ein No-op und war
  damit nie ausgefuehrt) und pytest-alembic fuer beide Migrationsketten, je mit einem
  Seed-Test, der die Daten-Migration mit Daten prueft statt auf einer leeren Tabelle.
  Ausschluesse stehen mit Grund und Wiedervorlage in `schemathesis_exclude.toml`, und
  eine `operation_id`, die das Schema nicht kennt, ist ein Fehler statt eines stillen
  No-ops. Neu: `requirements-dev.txt` je Dienst als einzige Wahrheit fuer Test-Deps.
- **Ephemere Proxmox-VMs ohne externes Binary (Harness Stufe 2a):** `scripts/vm/vm.py` least,
  verwaltet und zerstoert die VMs, auf denen die schweren Suites laufen — Python-3-Standard-
  bibliothek, keine Abhaengigkeit, nur die REST-API. Verben: `doctor clone wait ssh sync run
  pull snap rollback delsnap destroy reap list bake`. Linked Clones kosten ~2 s statt ~11 min
  Vollklon, Snapshot und Rollback je ein bis drei Sekunden. Der Zustand liegt als **Tag** auf
  dem Hypervisor (`ah`, `role-`, `lane-`, `sc-`, `ttl-`, `tpl-`), nicht in einer lokalen Datei:
  jeder Checkout sieht jede Lease samt Frist, jedes Verb ausser `list`/`doctor` raeumt am Ende
  die abgelaufenen VMs der eigenen Lane weg (kein Timer, kein Cron), und bei einer VM **ohne**
  `ah`-Tag verweigert `vm.py` jedes zerstoerende Verb, damit ein Tippfehler keine Homelab-VM
  frisst. Exit-Codes trennen „der Test ist rot" (1) von „die
  Infrastruktur hat nein gesagt" (74). `bake` baut aus dem Basis-Cloud-Image ein neues
  Template. Dazu `scripts/vm/lib.sh` als Shell-Seite und zwei hermetische Suiten: `vm.py`
  gegen aufgezeichnete Proxmox-Antworten (`scripts/vm/tests/`), `lib.sh` gegen einen
  Temp-Zustand (`scripts/tests/lib_vm_test.sh`); beide haengen an `verify.sh scripts --strict`
  und an CI. Anleitung: `DEVELOPMENT.md`, Abschnitt „VMs mit vm.py".

- **Paritaets- und Contract-Gates (Harness Stufe 8a):** Die APIs von Server und Monitoring
  haben jetzt einen eingecheckten OpenAPI-Snapshot (`apps/<dienst>/tests/openapi.snapshot.json`),
  den ein Test bei jeder Aenderung einfordert — neu aufgezeichnet wird er mit
  `pytest tests/test_openapi_snapshot.py --update-openapi-snapshot`, im selben Commit wie die
  API-Aenderung. Der neue CI-Job `openapi-compat` vergleicht den Snapshot des Basis-Branch per
  `oasdiff breaking --fail-on ERR` mit dem des PR: neue Pfade und Felder sind gruen, ein
  entfernter Pfad, ein entferntes Response-Feld oder ein neu verpflichtendes Request-Feld
  sind rot. `oasdiff` kommt als gepinnter Release-Tarball (v1.32.0, SHA-256 im Workflow), nicht
  per `go install` — jede Version ab v1.24.0 verlangt `go 1.26`, die Workflows pinnen aber Go
  1.25 mit `GOTOOLCHAIN=local`. Dazu Guards, die zwei getrennt gepflegte Wahrheiten aneinander
  pinnen: Proxy-Allowlist gegen die Monitoring-Routen, die mTLS-Identity-Header ueber Gateway,
  Server und CA-Issuer, der Enrollment-Token-Hash zwischen Server und CA-Issuer, und die
  Gleichheit der beiden SSRF-Guards. Dazu `scripts/dev/doc-smoke.py` (CI-Step im Job `ops-scripts`): jedes `<code>`-Fragment in
  `docs/**/*.html`, das einen Repo-Pfad nennt, muss eine existierende Datei benennen — zwei
  veraltete Pfade in der Entwickler-Doku sind damit schon aufgefallen und korrigiert.
  Und `sync-from-web.sh --check` (CI-Step im Job `desktop-ui`) haelt die vier API-Typen zusammen,
  die Web- und Desktop-Frontend doppelt fuehren.
  Details: `docs/developer/cicd.html` (DE + EN), Abschnitt „Paritaets- und Contract-Gates".

### Security

- **Agent und Audit auf Go 1.26 (R-0348):** CI (`agent`, `agent-windows`), Release und der woechentliche
  Audit bauen mit Go 1.26 und `check-latest`, also mit 1.26.9 oder neuer, solange setup-go sein
  Versions-Manifest erreicht (sonst nimmt es den Patch aus dem Toolcache des Runners). Das schliesst neun stdlib-Funde aus
  go1.25.14, die erst go1.26.9 behebt: GO-2026-6603, -6605, -6607, -6608, -6610, -6611, -6612, -6613 und
  -6617 (`net/http`, `net/textproto`, `crypto/tls`). `govulncheck` steht auf v1.9.0. Die `go`-Direktive in
  `apps/agent/go.mod` bleibt `1.25.0`. `scripts/dev/toolchain-lockstep.sh` verlangt neben jeder `go-version`
  `check-latest: true`. Die Test-Boxen (`scripts/vm/bootstrap_linux.sh`) installieren go1.26.9 statt 1.25.0.

- **Server-gebundene API-Keys schreiben nur fuer ihren Server (Server):** `POST /api/connections` und
  `PUT /api/connections/{id}` nehmen von einem an einen Server gebundenen API-Key nur eine `serverId`
  gleich diesem Server an; eine andere oder eine leere `serverId` ergibt `403` „Kein Zugriff auf diesen
  Server". Ein solcher Key darf Verbindungen also nur fuer seinen eigenen Server anlegen oder dorthin
  verschieben. Ungebundene Keys und Benutzer sind nicht betroffen. Eine Test-Matrix
  (`tests/test_api_key_server_binding.py`) haelt fest, was jede Key-Art auf jeder Route darf, die einen
  API-Key annimmt.

- **npm-Abhaengigkeiten (dev) ohne Audit-Befund (R-0038):** `vitest` und die `@vitest/*`-Pakete
  stehen in `apps/web` und `apps/desktop/ui` auf 4.1.11 (GHSA-82fw-gwwq-j7x9; Ranges `^4.1.11`).
  Die Lockfiles dort und in `apps/desktop/e2e` heben `brace-expansion` (GHSA-qhr7-859c-m2p7,
  GHSA-6j4f-fj2g-mc7p; high), `undici` (GHSA-rfgv-xxqx-mfg5, GHSA-w293-vg96-wgc3; high),
  `devalue` (GHSA-9rgm-9g3h-6x36) und in e2e `ip-address` (GHSA-j6r3-76f7-8jcv,
  GHSA-h3mg-xc3c-68pw) auf gefixte Versionen, alles `dev`-Abhaengigkeiten. Vorher meldete
  `npm audit --audit-level=high`, mit dem der woechentliche Dependency Audit gated, in allen drei
  Verzeichnissen zwei high-Funde; jetzt ist `--audit-level=moderate` ueberall ohne Befund. Die
  Lockfiles von web und desktop-ui schreibt einmalig `npx -y npm@11 … --package-lock-only`, weil
  npm 10.9.8 dabei in arborist abbricht; `npm ci` laeuft mit npm 10 unveraendert.

- **SSRF-Guard (Server und Monitoring):** Die DNS-Aufloesung des Guards lief ueber einen
  geteilten Vier-Worker-Pool. Vier haengende Aufloesungen belegten ihn vollstaendig, jeder
  weitere `is_private_url`-Aufruf lief in seine 5-Sekunden-Frist und meldete fail-closed
  „privat". Durch den Guard laufen nur HTTP-Checks und Alert-Webhooks — im Monitoring hiess
  das also: ein toter Nameserver, und keiner von beiden erreichte mehr ein Ziel. Aufgeloest
  wird jetzt je Aufruf in einem eigenen Daemon-Thread mit derselben Frist, gedeckelt auf 64
  gleichzeitige Aufloesungen; ueber dem Deckel wird sofort fail-closed abgelehnt und
  hoechstens einmal pro Minute gewarnt. Eine leere Adressliste gilt jetzt ebenfalls als
  „privat". Nach aussen aendert sich nichts, ausser dass haengende Aufloesungen einander
  nicht mehr blockieren und der Dienst trotz haengender Aufloesung beendet werden kann.

- **Desktop-Backend:** `rustls` 0.23.40 → 0.23.45 (RUSTSEC-2026-0285, TLS-1.3-Handshake-
  Nachrichten wurden ueber Encryption-Level-Grenzen hinweg akzeptiert; medium) samt
  `rustls-webpki` 0.103.13 → 0.103.15 — nur der Lockfile-Stand, keine Verhaltensaenderung.
  Gefunden vom gepinnten `cargo audit` des Audit-Sweeps. Cargo 1.96 haengt beim Update
  zusaetzlich fuenf `windows-sys`-Kanten (errno, os_pipe, rustix, tempfile, winapi-util)
  auf bereits gelockte Versionen um — Windows-only, vom CI-Job `rust-windows` gebaut.

- **Desktop-Backend: `rustls` 0.23.45 → 0.23.46 (R-0547):** schliesst RUSTSEC-2026-0346 (die `Debug`-Ausgabe
  der Client-Session-Werte enthielt das TLS-1.2-Master-Secret bzw. den TLS-1.3-Resumption-PSK; medium),
  -0347 (nach abgelehntem ECH gingen gepufferte Anwendungsdaten an den aeusseren Server; low), -0348 (die
  Brotli-Dekompression von Zertifikaten konnte vor der Authentisierung bis zu 1 GiB allokieren; low) und -0349
  (ein nicht authentisierter ServerHello konnte spaetere Verbindungen auf klassischen Schluesselaustausch
  herabstufen; low) — nur der Lockfile-Stand, `Cargo.toml` und alle anderen Pakete bleiben. Das Desktop-Backend
  schaltet das `rustls`-Feature `brotli` nicht ein und nutzt weder ECH noch einen eigenen `ClientSessionStore`.
  Gefunden vom woechentlichen Dependency-Audit; `cargo audit` meldet jetzt nur noch die erlaubten Warnungen.

- **Desktop-Backend:** `quinn-proto` 0.11.15 → 0.11.18 (RUSTSEC-2026-0338, -0339, -0340, -0341,
  -0342: ein QUIC-Peer konnte quinn-proto in einen Panic treiben oder Speicher unbegrenzt wachsen
  lassen; zwei davon high) — nur der Lockfile-Stand, keine Verhaltensaenderung. Das Paket haengt
  ueber `quinn` 0.11.9 an `reqwest` 0.12.28 und steht nur wegen dessen schwacher Feature-Kante
  `quinn?/ring` im Lockfile; gebaut wird es fuer kein Ziel (`cargo tree --target all --all-features
  -i quinn-proto` ist leer). Mit 0.11.18 kommen `chacha20` 0.10.2, `cpufeatures` 0.3.1, `rand`
  0.10.3, `rand_core` 0.10.1 und `rand_pcg` 0.10.2 neu ins Lockfile; die wasm-only-Kanten
  `js-sys`/`wasm-bindgen` wandern von `getrandom` 0.3.4 zu 0.4.2. Gefunden vom gepinnten
  `cargo audit` des Audit-Sweeps.

- **anyio 4.13.0 → 4.14.2** in server, monitoring und ca-issuer (gehashte Locks neu generiert):
  behebt CVE-2026-63374 und CVE-2026-64847. Vom woechentlichen Dependency-Audit (`pip-audit`)
  erkannt. Die Locks von server und monitoring ziehen dabei `sqlalchemy[asyncio]` nach, faellig
  seit der `.in`-Aenderung (gleiche Version, gleiche Hashes). `pytest` gegen die exakten neuen
  Locks unter Python 3.12 gruen — server 968, monitoring 599, ca-issuer 74 —, `pip-audit` ohne Befund.

- **pyjwt 2.13.0 → 2.14.0** im Server (gehashte Lock neu generiert, Untergrenze in `requirements.in`
  auf `>=2.14.0`): behebt CVE-2026-101917, CVE-2026-102265 bis -102269 und CVE-2026-102271 bis -102274.
  Vom Dependency-Audit (`pip-audit`) erkannt. Der Changelog 2.13.0 → 2.14.0 enthaelt keine inkompatible Aenderung; `pytest`
  gegen den exakten neuen Lock unter Python 3.12 gruen (server 682), `pip-audit` ohne Befund.

- **pyjwt 2.14.0 → 2.15.1** im Server (gehashte Lock neu generiert, Untergrenze in `requirements.in`
  auf `>=2.15.0`, R-0193): behebt PYSEC-2026-4141 (behoben ab 2.15.0). Vom Dependency-Audit (`pip-audit`)
  erkannt. Der Changelog 2.14.0 → 2.15.1 enthaelt keine inkompatible Aenderung fuer `jwt.encode`/`jwt.decode`
  mit HS256: 2.15.0 meldet zu tief verschachtelte Payloads als `DecodeError` (der Server faengt
  `InvalidTokenError`), 2.15.1 nimmt ein angehaengtes `=`-Padding in JWS-Segmenten an (gesperrte Tokens
  erkennt der Server an der `jti`, nicht am Token-String). `pytest` gegen den exakten neuen Lock unter
  Python 3.12 gruen (server 824), `pip-audit` ohne Befund.

- **e2e-Lockfile: `basic-ftp` 5.3.1 → 6.2.2, `braces` entfernt (R-0198):** zwei `overrides` in
  `apps/desktop/e2e/package.json`, beide unter WebdriverIO und vom Dependency-Audit (`npm audit`, Schritt „Audit e2e
  lockfile") erkannt; nur `dev`-Abhaengigkeiten, nichts davon wird ausgeliefert.
  - `basic-ftp` auf `^6.2.1` (transitiv ueber `@wdio/utils` → `@puppeteer/browsers` → `proxy-agent` →
    `pac-proxy-agent` → `get-uri`, das `^5.3.1` verlangt): behebt GHSA-c475-qrg2-pj4r (high, CPU-Last beim Parsen von
    Verzeichnislisten), 6.2.2 zusaetzlich GHSA-5rfr-xx34-2xxv. Der Changelog 5.3.1 → 6.2.2 aendert keine API, die
    `get-uri` nutzt; der Bruch in 6.0.0 (kein getrennter Transfer-Host ohne `allowSeparateTransferHost`) betrifft nur
    FTP-Downloads, die der Testbaum nicht macht.
  - `chokidar` unter `mocha` auf `^4.0.3`: fuer `braces` (GHSA-vfj7-8cjw-p6xm, high, bis 3.0.3, ohne gepatchte
    Version) gibt es keinen Fix, es hing nur an mochas `chokidar` 3.6.0. Mit chokidar 4, das schon im Baum liegt, faellt
    es samt elf weiteren Paketen weg. Grenze: Der Watch-Modus der mocha-CLI verliert die Glob-Unterstuetzung; die
    E2E-Tests nutzen ihn nicht, WebdriverIO ruft mocha programmatisch.
  - `npm audit --audit-level=high` in `apps/desktop/e2e` vorher 18 high, nachher 0; `apps/web` und `apps/desktop/ui`
    unveraendert ohne Befund.

- **`source-map-js` 1.2.1 → 1.2.2 in den Lockfiles von `apps/web` und `apps/desktop/ui` (R-0199):** behebt GHSA-68fv-2mgg-jv7q
  (CVE-2026-93749, high, Event-Loop-Blockade durch indizierte Source-Map-Abschnitte). Vom Dependency-Audit (`npm audit`)
  erkannt. Reiner Lockfile-Bump (`npm update source-map-js --package-lock-only`), `package.json` unveraendert: alle
  Abnehmer (`postcss`, `css-tree`, `magicast`) erlauben `^1.2.1`. Der Changelog 1.2.1 → 1.2.2 enthaelt nur diesen Fix
  und einen CSP-Fix fuer den Browser. Nur Dev-Werkzeug, nicht im ausgelieferten Bundle; `npm audit --audit-level=high`
  vorher je 1 high, nachher 0 in beiden Projekten und in `apps/desktop/e2e`.

- **certifi 2026.5.20 → 2026.10.19** in server und monitoring (gehashte Locks neu generiert, R-0657): behebt
  PYSEC-2026-4320 (GHSA-6q48-6c7w-9gw2). Das gebuendelte CA-Paket enthielt die Wurzel `emSign ECC Root CA - G3`, unter
  der acht widerrufene eMudhra-Zwischenzertifikate mit kompromittierten privaten Schluesseln haengen; wer einen davon
  hat und im Netzweg sitzt, kann TLS-Verbindungen abfangen. 2026.10.19 nimmt diese Wurzel heraus, die uebrigen
  emSign-Wurzeln bleiben. Mit den Mozilla-Staenden dazwischen entfallen ausserdem `Atos TrustedRoot 2011` und
  `SecureSign Root CA12`, neu sind je zwei Wurzeln von SECOM (2024) und Telia (v3). `certifi` kommt transitiv ueber
  `httpx`/`httpcore` und ist deren Vertrauensanker, wenn ausgehendes HTTPS das Zertifikat prueft (etwa die HTTP-Checks
  des Monitorings mit `verify_ssl`). Vom woechentlichen Dependency-Audit (`pip-audit`) erkannt. Nur der Lock-Stand: im
  Diff aendern sich Version und Hashes von `certifi`, `requirements.in` bleibt; beide Locks installieren mit
  `--require-hashes` unter Python 3.12, `pip-audit` ohne Befund.

- **Desktop-Backend: `rustls-webpki` 0.103.15 → 0.103.16 und `webpki-roots` 1.0.7 → 1.0.10 (R-0657):** schliesst
  RUSTSEC-2026-0382 und RUSTSEC-2026-0381 (beide CVE-2026-111943) zu denselben acht widerrufenen
  eMudhra-Zwischenzertifikaten wie bei certifi oben. `webpki-roots` 1.0.10 entzieht ihnen das Vertrauen, indem es die
  Wurzel `emSign ECC Root CA - G3` herausnimmt; mit den Mozilla-Staenden dazwischen wechseln dieselben Wurzeln wie bei
  certifi (`Atos TrustedRoot 2011` und `SecureSign Root CA12` entfallen, je zwei von SECOM (2024) und Telia (v3) kommen
  dazu). `rustls-webpki` 0.103.16 lehnt jeden Zertifikatspfad ab, der den oeffentlichen Schluessel eines dieser
  Zwischenzertifikate enthaelt, gleich unter welcher Wurzel. Wirksam ist das auf dem Weg mit oeffentlicher CA, den der
  Desktop nimmt, wenn er weder mit Geraete-Identitaet (mTLS) noch mit TOFU verbindet, und bei der Probe, ob ein
  Server-Zertifikat oeffentlich vertraut ist: Dort ist `webpki-roots` ueber das reqwest-Feature `rustls-tls` der
  Vertrauensanker, und `rustls-webpki` prueft die Kette. Ein enrolltes Geraet prueft gegen die bei der Registrierung
  gepinnte CA, der TOFU-Weg pinnt das Blattzertifikat ohne Kettenpruefung; beide vertrauen keiner Wurzel aus
  `webpki-roots`. Gefunden vom woechentlichen Dependency-Audit; nur der Lockfile-Stand, im Diff aendern sich Version und
  Checksumme der zwei Pakete, `Cargo.toml` bleibt. `cargo audit` meldet jetzt nur noch die erlaubten Warnungen.

- **Web und Desktop-UI: `vite` 8.0.16 → 8.1.6 (R-0657):** schliesst GHSA-587h-7wmj-h5pm (high), GHSA-698v-4r3x-3vcv
  und GHSA-r825-w8mm-5pxw im eingebauten `launch-editor` (jetzt 2.14.2), mit dem der Vite-Dev-Server ueber
  `/__open-in-editor` eine Quelldatei im Editor oeffnet. Unter Windows konnte ein praeparierter Dateipfad dabei Befehle
  ausfuehren, unter WSL mit Vim oder Emacs ein Pfad, der mit `-` oder `+` beginnt. Betroffen ist nur der Dev-Server
  (`npm run dev`, `tauri dev`); die ausgelieferten Bundles von Web-Panel und Desktop enthalten weder Vite noch
  `launch-editor`. Die Untergrenze in beiden `package.json` steht jetzt auf `^8.1.6`. Mit Vite 8.1 baut `rolldown`
  1.1.5 statt 1.0.3 die Bundles; im Lockfile ziehen ausserdem `picomatch` 4.0.7, `@oxc-project/types` 0.139.0 und die
  nur unter WebAssembly geladenen `@emnapi/*`, `@napi-rs/wasm-runtime` und `@tybys/wasm-util` nach, alles
  Abhaengigkeiten von Vite selbst. `npm run build` laeuft in beiden Projekten, die erzeugte `index.html` ist bis auf den
  Hash des Skripts gleich. Gefunden vom woechentlichen Dependency-Audit; `npm audit --audit-level=high` meldete vorher
  in beiden Projekten 1 high (vite) und meldet jetzt nichts mehr.

### Fixed

- **SSRF-Schutz prueft internationalisierte Hostnamen in der Form der Anfrage (Server und Monitoring):** Der Guard vor
  dem HTTP-Check und dem Alert-Webhook des Monitorings sowie vor den Hook-Helfern `http_get`/`http_post` des Servers
  prueft einen internationalisierten Hostnamen jetzt in der Form, die die Anfrage als Host-Header und TLS-Name traegt
  (IDNA 2008, etwa `xn--strae-oqa.example`). Bisher loeste er bei scharfem s oder finalem Sigma einen anderen Namen auf
  (IDNA 2003) und verband zu dessen Adressen, und die Anfrage konnte am Zertifikat oder am vhost scheitern. Ein
  Hostname, den httpx nicht kodieren kann, wird schon vom Guard abgelehnt wie eine unlesbare URL, ebenso eine URL, die
  httpx sonst nicht liest (etwa ein Port, der keine Zahl ist): Die Hook-Helfer werfen dafuer wie dokumentiert einen
  `ValueError` statt `httpx.InvalidURL`, HTTP-Check und Alert-Webhook melden ein privates/reserviertes Ziel.
- **Ops-Skripte: eine `.env` mit einem NUL-Byte oder mit Bytes ausserhalb von UTF-8 verliert keine Zeilen mehr
  (R-0530):** `grep` haelt eine Datei mit einem NUL-Byte oder mit einem Byte, das die Locale des Aufrufers nicht
  dekodieren kann (etwa ein Latin-1-Umlaut unter einer UTF-8-Locale), fuer binaer und laesst Zeilen aus: die Zeilen
  mit einem solchen Byte, bei einem NUL-Byte alle. Setzten `install.sh`, `update.sh` oder `init-secrets.sh` einen
  Schluessel, fehlten diese Zeilen danach in der `.env`. `init-secrets.sh`, das `install.sh` und `update.sh` aufrufen,
  hielt ein gesetztes Secret in einer solchen Zeile fuer leer und erzeugte es neu, bei einem NUL-Byte alle vier, auch
  `POSTGRES_PASSWORD` und `CA_ROOT_PASSPHRASE`, die dann nicht mehr zu den Volumes passten. Bei einem NUL-Byte nannte
  `update.sh` die Installation ausserdem `:latest`, und der Rollback nach einem gescheiterten Neustart oder
  Healthcheck hinterliess eine `.env` ohne Image-Pins. Jetzt lesen die Skripte die `.env` in jeder Locale Byte fuer
  Byte (`LC_ALL=C grep -a`).
- **Ops-Skripte: eine schreibgeschuetzte `.env` haelt `install.sh`, `update.sh` und `init-secrets.sh` an einem
  Terminal nicht mehr an (R-0538):** `mv` fragt vor dem Ersetzen einer Datei ohne Schreibrecht nach, wenn die Eingabe
  ein Terminal ist, und wartet auf die Antwort. War die `.env` schreibgeschuetzt, blieben so `install.sh` und
  `init-secrets.sh` beim Setzen eines Schluessels stehen und `update.sh` beim Pinnen der Images und in beiden
  Rollbacks; ein Update endete dann weder fertig noch zurueckgerollt, und unter einem Wrapper, der die Ausgabe
  einsammelt, war die Frage nicht zu sehen. Jetzt ersetzen die Skripte jede Datei der Installation ohne Rueckfrage
  (`mv -f`), wie schon bisher ohne Terminal.
- **Server: der Visitor-Port eines FRP-Tunnels ist ein Port von 1 bis 65535 (R-0533):**
  `POST`/`PUT /api/frp/tunnels` nahmen als `visitor_port` jeden INTEGER-Wert an und speicherten ihn; der Server schrieb
  ihn als `bindPort` in die Visitor-TOML, und der Desktop wies die ganze Visitor-TOML ab. `0` vergab still einen freien
  Port. Jetzt lehnt der Server einen `visitor_port` ausserhalb 1–65535, auch `0`, mit `422` ab, und nichts wird
  gespeichert. Ist das Feld `null` oder fehlt es beim Anlegen, vergibt der Server einem STCP-Tunnel wie bisher einen
  freien Port. Ein schon gespeicherter Wert ausserhalb 1–65535 und ein STCP-Tunnel ohne Visitor-Port (`NULL` aus einer
  frueheren Migration) bleiben in der Datenbank; statt den Wert als `bindPort` zu schreiben (bei `NULL`
  `bindPort = None`, kein gueltiges TOML), laesst der Server diesen Visitor jetzt aus der Visitor-TOML weg
  (`/api/frp/generate/visitor-toml`, `visitor-bundle`, `bulk-zip`) und schreibt eine Warnung ins Server-Log. Sind alle sichtbaren STCP-Tunnel eines Nutzers so, antworten `visitor-toml` und
  `visitor-bundle` mit `404`. Die frpc-Konfiguration der Agents behaelt den Tunnel. Doku: FRP-Tunnel und API-Referenz
  (DE+EN).
- **Agent: nach `dnf upgrade` laufen Timer und frpc weiter (R-0527):** Beim Upgrade des RPM stoppte das `%preun` des
  alten Pakets `adminhelper-agent.timer` und `frpc.service`, nachdem das `%post` des neuen sie gestartet hatte; beide
  blieben aktiviert, liefen aber bis zum naechsten Neustart nicht. Jetzt stoppt und deaktiviert `%preun` sie nur bei
  der Deinstallation, und das neue Paket aktiviert sie erst am Ende der Transaktion (`%posttrans`): den Timer immer,
  `frpc.service` nur mit `/etc/frp/frpc.toml`, und frpc startet dabei neu, damit es auf dem neuen Binary laeuft. Das
  gilt auch fuer ein Upgrade von einem bisherigen Paket. Das deb war nicht betroffen.
- **Agent: `provision` loest den Einmal-Token erst nach dem Sichern des Datenverzeichnisses ein (R-0557):** Bisher
  loeste `provision` den Token ein, bevor es das Datenverzeichnis zum ersten Mal sicherte; liess sich das Verzeichnis
  danach nicht sichern, brach es ab, und der Token war verbraucht. Jetzt sichert `provision` zuerst die Datenwurzel
  (Windows: `%ProgramData%\AdminHelper` samt Baum; Linux: `/etc/adminhelper` mit `0700`, auch ohne Monitor);
  scheitert das, bricht es mit dem Verzeichnis im Fehler ab, und der Token bleibt gueltig. Doku: Entwickler-Doku
  Agent (DE+EN).
- **Agent: der FRP-Sync aendert Dateien nur in einem gesicherten Verzeichnis (R-0556):** Bisher schrieb und loeschte
  der Sync (`run`, `frpc sync`) `frpc.toml`, `admin.conf` und die Hash-Dateien im FRP-Verzeichnis, ohne es im selben
  Lauf zu sichern; der Windows-Dienst laeuft auch weiter, wenn er die Datenwurzel beim Start nicht sichern konnte.
  Jetzt sichert der Sync vor seiner ersten Aenderung, Schreiben wie Loeschen, das FRP-Verzeichnis (Windows: zuerst
  `%ProgramData%\AdminHelper` samt Baum; Linux: `/etc/frp` mit `0700`); scheitert das, bricht er mit dem Verzeichnis
  im Fehler ab und schreibt, loescht, startet und stoppt nichts. Ein Lauf ohne Aenderung sichert nichts. Doku:
  Entwickler-Doku Agent (DE+EN).
- **Desktop: „Passwort merken“ im Server-Workspace nur fuer Verbindungen, die der Server fuehrt (R-0551):** Wer im
  Editor eine neue RDP-Verbindung vor dem Speichern verband und das Passwort merken liess, legte es im
  Schluesselbund unter einer `id` des Clients ab, die der Server beim Speichern durch eine eigene ersetzt; der Eintrag
  gehoerte danach zu keiner Verbindung. Im Server-Workspace bietet der Passwort-Dialog das Merken jetzt nur fuer eine
  Verbindung an, die schon in der Liste steht; fuer eine noch nicht gespeicherte gilt das getippte Passwort nur fuer
  diesen Start (unter Windows verwirft der Desktop es, und mstsc fragt selbst). Lokal und Sync bleiben
  unveraendert. Doku: Desktop fuer Entwickler (DE+EN).
- **Desktop: ein abgebrochenes Schreiben laesst keine Temp-Datei dauerhaft im Datenordner liegen (R-0553):** Endete
  der Desktop, waehrend er eine Datei auf einmal ersetzte (`prefs.json`, `workspaces.json`, eine `workspace.json`,
  `secrets.json`), blieb deren Temp-Datei `<Dateiname>.<pid>.tmp` im Datenordner der App liegen. Jetzt loescht das
  naechste Schreiben derselben Datei sie, sobald sie mindestens zehn Minuten alt ist; eine juengere kann einem anderen
  Prozess gehoeren, der gerade schreibt, und bleibt. Doku: Desktop fuer Entwickler (DE+EN).
- **Desktop: ein Ansible-Lauf laesst Playbook und Inventory nicht mehr im Temp-Verzeichnis liegen (R-0549):** Jeder
  Lauf hinterliess beide Dateien im Temp-Verzeichnis des Systems. Unter Linux loescht das Terminal sie jetzt, sobald
  `ansible-playbook` endet, gleich mit welchem Ergebnis und auch dann, wenn das Terminal waehrend des Laufs geschlossen
  wird; scheitert der Start (kein `ansible-playbook`, kein Terminal), loescht der Desktop sie sofort. Unter Windows
  bleiben sie nach einem gestarteten Lauf liegen. Doku: Admin-Doku Ansible, Desktop fuer Entwickler (DE+EN).
- **Monitoring: die Status-Zeitleiste eines Push-Checks bleibt ohne Messwerte nicht leer:** Ein vom Agent-Report
  ausgewerteter Check, dessen Ergebnis keine Messwerte traegt, schrieb nichts nach VictoriaMetrics, und seine
  Status-Zeitleiste im Desktop blieb leer, etwa bei Docker, ZFS und Proxmox, wenn der Agent sie nicht lesen konnte oder
  keinen Block schickte, bei Proxmox ohne VMs, bei `smart_health` ohne SMART-Daten, bei `agent_resources` ohne
  Ressourcen-Block und beim neuen Check `system_state` immer. Jetzt schreibt der Push-Pfad fuer jeden ausgewerteten
  Check den Status (`monitor_check_status`); eine neue Messreihe entsteht nicht, und ohne Messwerte auch keine Dauer.
  Doku: Entwickler-Doku Monitoring (DE+EN).
- **Monitoring: doppelte Mounts und Platten ohne Mount in der Live-Ansicht:** Meldete ein Agent zwei Dateisysteme am
  selben Mount-Pfad, brach die Live-Ansicht des Servers im Desktop ab; jetzt zeigt sie beide Eintraege. Eine Platte, die
  der Agent ohne Mount meldet, heisst in Bewertung, `ignore_mounts` und Anzeige einheitlich „?“; bisher bewertete der
  Check sie als „?“, die Check-Details nannten sie aber „/“, und neben der echten Platte „/“ brach damit die
  Live-Ansicht ab. Doku: Entwickler-Doku Monitoring (DE+EN).
- **Monitoring: die Listen bleiben lesbar, wenn ein gespeicherter Wert keine endliche Zahl ist:** Stand in einer
  Check-Konfiguration, in den Details eines Check-Zustands, in der Kanal-Konfiguration einer Alert-Regel oder in einer
  Definition eines Templates `NaN`, `Infinity` oder eine Zahl ausserhalb des Gleitkomma-Bereichs, scheiterte die ganze
  Antwort von `GET /status`, `GET /checks`, `GET /alerts`, `GET /templates` bzw. des Update-Vergleichs eines
  Standard-Templates (`GET /templates/{id}/builtin-update`) mit einem Serverfehler, oder der Desktop konnte sie nicht
  lesen. Jetzt erscheint ein solcher Wert dort als `null`; gespeichert bleibt er, wie er ist.
  Doku: Entwickler-Doku Monitoring (DE+EN).
- **Desktop: die Sitzung haelt laenger als acht Stunden, und eine abgelaufene fuehrt zum Login (R-0430):** Nach
  Ablauf des Access-Tokens (acht Stunden) scheiterten Infrastruktur, Monitoring, Ansible und die Glocke, weil nur ein
  Teil der Anfragen die Sitzung erneuerte. Jetzt erneuert der Desktop sie fuer alle Anfragen an einer Stelle und nur
  einmal zur Zeit; trafen bisher mehrere Erneuerungen zusammen, meldete der Server den Benutzer ueberall ab. Der
  Benachrichtigungs-Stream nimmt nach einer Erneuerung das neue Token, statt zu verstummen. Laesst sich die Sitzung
  nicht mehr erneuern, meldet der Desktop ab und zeigt den Login-Bildschirm mit dem Hinweis „Sitzung abgelaufen —
  bitte neu anmelden.“ Doku: Desktop fuer Entwickler (DE+EN), README.
- **Desktop: die automatische Web-Verbindung eines STCP-Tunnels oeffnet sich (R-0430):** Der Server legt sie ohne
  URL an, und der Desktop pruefte die Verbindung vor der Tunnel-Aufloesung: Sie brach fuer alle Benutzer mit „URL
  darf nicht leer sein“ ab. Jetzt prueft er die aufgeloeste Verbindung; solange der Tunnel laeuft, oeffnet sie
  `http://127.0.0.1:<lokaler Port>`. Ohne laufenden Tunnel meldet sie weiter die fehlende URL. Doku: Desktop fuer
  Entwickler (DE+EN).
- **Desktop: die Paketbeschreibung nennt kein VNC mehr (R-0523):** Die lange Beschreibung des Desktop-Pakets, die
  etwa `apt show` zeigt, nannte VNC unter den Verbindungsarten. Der Client oeffnet SSH-, RDP- und Web-Verbindungen;
  die Beschreibung nennt jetzt nur diese.
- **Agent: eine Platte, die smartctl nicht oeffnen kann, meldet kein „SMART FAILED“ mehr (R-0493):** Endete die
  Abfrage einer Platte mit Exit-Bit 0 oder 1 von smartctl (Befehlszeile nicht gelesen, Geraet nicht geoeffnet), kam
  sie ohne Modell und SMART-Status in den Report, und der Check `smart_health` meldete sie als „SMART FAILED“,
  critical. Jetzt faellt sie aus dem Report; liefert keine Platte lesbare Daten, meldet der Agent wie bei einem
  gescheiterten Scan `scan_failed`. Bei den Bits 2 bis 7 bleibt die Platte wie bisher im Report, `smartctl_status`
  traegt den vollen Exit-Code. Doku: Agent-Entwicklerseite, Monitoring-Administration (DE+EN).
- **Agent: Platten hinter einem MegaRAID- oder sssraid-Controller tragen eigene Namen (R-0491):** Der Agent meldete
  alle Platten eines solchen Controllers unter dessen Geraetenamen, etwa `/dev/bus/0` bzw. `/dev/bsg/sssraid0`: Der
  Check `smart_health` nannte sie gleich, ihre Werte landeten in derselben Messreihe, und ein Eintrag in
  `ignore_devices` nahm alle zugleich aus. Jetzt heissen sie wie bei smartctl, etwa `/dev/bus/0 [megaraid_disk_00]`
  oder `/dev/bsg/sssraid0 [sssraid_disk_00_01]`; andere Platten behalten ihren Namen. Nach dem Update des Agents
  greift ein `ignore_devices`-Eintrag `/dev/bus/N` nicht mehr, dort gehoeren die neuen Namen hin, und die Metriken
  dieser Platten bekommen neue Namen, etwa `monitor_smart_temp_dev_bus_0__megaraid_disk_00_value` statt
  `monitor_smart_temp_dev_bus_0_value`. Doku: Agent-Entwicklerseite, Monitoring-Administration (DE+EN).
- **Agent: ein nicht lesbarer Backup-Storage meldet unter Proxmox kein „No backup“ mehr (R-0494):** Scheiterte die
  Liste der Storages oder der Inhaltsaufruf eines Backup-Storages (etwa ein nicht erreichbares NFS-Ziel), fehlten
  dessen Backups still im Index, und der Check `proxmox_backup` meldete jede betroffene VM als „No backup“,
  critical. Jetzt fehlt dann der Proxmox-Block, der Check steht auf `unknown`, und der Grund steht als Warnung im
  Agent-Log; ebenso, wenn ein Backup-Storage nicht aktiv ist. Die Backup-Storages liest der Agent neu aus
  `/nodes/<node>/storage --content backup` statt aus `/storage`, das auch abgeschaltete und anderen Nodes
  zugeordnete Storages listet. Doku: Agent-Entwicklerseite, Monitoring-Administration (DE+EN).
- **Desktop: nach dem Abmelden bleiben keine Daten des vorigen Benutzers stehen (R-0429):** Abmelden ueber die
  Kopfzeile und ueber die Einstellungen beendet jetzt den Tunnel, meldet ab und laedt das Fenster neu. Bisher
  zeigten Infrastruktur, Monitoring und Ansible bis zum naechsten Laden die Daten des vorigen Benutzers, auch nach
  einem Login unter anderem Benutzer. Die Server-URL aendert seit den Workspaces nur der Picker, solange der
  Workspace geschlossen ist (siehe Changed).
- **Desktop: Speichern der Einstellungen vergisst den Benutzernamen nicht mehr (R-0429):** Bisher loeschte jedes
  Speichern im Einstellungsdialog den gemerkten Benutzernamen, und der Login-Bildschirm fuellte beim naechsten
  Start nur noch die Server-URL vor. Felder, die der Dialog nicht bearbeitet, bleiben jetzt erhalten.
- **Desktop: gespeichertes RDP-Passwort auch bei Tunnelzielen (Linux/macOS, R-0429):** Bisher startete der
  RDP-Client bei einer Verbindung hinter einem FRP-Tunnel ohne das gespeicherte Passwort, weil der Desktop es unter
  der lokalen Tunnel-Adresse (`127.0.0.1:<Port>`) suchte statt unter der Verbindung aus der Liste, unter der es
  gespeichert ist. Unter Windows gilt das seit den Workspaces ebenfalls (siehe Added).
- **Desktop: Sync von einer fremden URL auch auf einem registrierten Geraet (R-0429):** Bisher scheiterte auf einem
  registrierten Geraet jeder Sync von einer URL ausserhalb des eigenen Servers mit `ERR_CA_PIN_MISMATCH`, weil der
  Desktop auch dort die Geraete-Identitaet nahm und das Server-Zertifikat gegen die bei der Registrierung gepinnte CA
  pruefte. Die Geraete-Identitaet nimmt er jetzt nur, wenn die Sync-URL dieselbe Origin (Schema, Host, Port) hat wie
  die gespeicherte Server-URL; jede andere Sync-URL laedt er wie ein nicht registriertes Geraet. Ein zweiter
  Hostname des eigenen Servers zaehlt dabei als andere Origin.
- **Desktop: ein zweiter Start laesst die laufende App nicht mehr abstuerzen (Linux, R-0429):** Bisher beendete ein
  zweiter Start unter Linux die laufende App samt Sitzung und Tunnel, und auch der zweite Start blieb nicht offen.
  Jetzt laesst ein zweiter Start die laufende App in Ruhe; seit den Workspaces holt er den Launcher nach vorn oder
  oeffnet ihn (siehe Changed).
- **Server: Die Tunnel-Statusansicht zeigt wieder die Proxies von frps (R-0408):** Seit v0.40.0 haengt frps in
  Compose allein im Netz `frpedge`, das der Server nicht erreicht; `GET /api/frp/status` fragte weiter
  `http://frps:<Port>` und meldete deshalb immer „frps-Dashboard: nicht erreichbar“. Jetzt fragt der frps-Supervisor
  das Dashboard im frps-Container ueber Loopback ab, alle 5 s, solange frps laeuft, und legt die Proxy-Listen je Typ
  im Volume `frps-state` ab (`proxy-<typ>.json`, hoechstens 1 MiB). Der Server liest sie dort und nimmt nur aktuelle
  (hoechstens 60 s alte), gueltige Listen; ohne eine solche antwortet die Route mit dem `error` „frps dashboard: no
  current data from the frps supervisor“. Die Adressen `http://frps:<Port>` und `http://127.0.0.1:<Port>` entfallen.
  Mit `FRPS_DASHBOARD_URL` fragt der Server das Dashboard weiter selbst; die Variable wirkt nur in der Umgebung des
  Dienstes `server` (etwa ueber eine `docker-compose.override.yml`), nicht ueber die `.env`. Doku: Admin-Doku
  FRP-Tunnel (DE+EN).
- **Server: Hook-Skripte speichern Verbindungen mit `save_connections` (R-0469):** Jeder Hook, der
  `save_connections` aufrief, endete mit `success: false` und dem Fehler „Foreign key associated with column
  'connections.server_id' could not find table 'servers' …“ und schrieb nichts, etwa die Beispiele
  `webhook_add_connection.py`, `webhook_http_import.py` und `schedule_hook_cleanup.py` unter `docs/examples/`. Der
  Worker-Prozess der Hooks lud nur das Modell der Verbindungen; jetzt laedt er wie Web- und Scheduler-Prozess alle
  Modelle aus `apps/server/app/model_registry.py`. Nach dem Update schreiben solche Hooks bei ihrem naechsten Lauf;
  einen, der das nicht mehr soll, vorher deaktivieren oder loeschen.
- **Monitoring: Schalter der Check-Konfiguration nehmen nur `true` oder `false` (R-0456):** `verify_ssl` (`http`),
  `exclude_stopped` (`proxmox_backup`) und `check_restarts` (`docker_health`) nahmen auch `"false"`, `"no"`, `0` oder
  `1` an und speicherten sie so. Der Check-Editor zeigte dann den Default, der Checker las den Wert anders: Ein
  `verify_ssl: 0` schaltete die TLS-Pruefung ab, ein `exclude_stopped: 0` nahm gestoppte VMs mit. Jetzt lehnen
  `POST /checks`, `PUT /checks/{id}` mit geaenderter Konfiguration und Template-Definitionen solche Werte mit 422 ab,
  wie schon bei `alert_on_unavailable`. Keine Migration: Ein gespeicherter Nicht-Bool-Wert gilt als Default, wie ihn
  der Check-Editor zeigt, nur ein echtes `false` schaltet ab; ein altes `verify_ssl: 0` prueft TLS also wieder. Doku:
  Monitoring-Administration (DE+EN).
- **Monitoring: Zahlenfelder der Check-Konfiguration nehmen nur Zahlen (R-0487):** Schwellwerte, Timeouts, Ports und
  die uebrigen Zahlenfelder nahmen auch Zahl-Strings wie `"85"` oder `"8.5e1"` und `true` an und speicherten sie so.
  Der Check-Editor zeigte das Feld dann leer, der Checker las den Wert anders: An einem Zahl-String scheiterten
  `agent_resources`, `smart_health`, `zfs_health` und `proxmox_backup`, und der Check blieb auf seinem letzten Zustand
  stehen; ein `true` galt als 1, ein `cpu_warn: true` warnte also schon ab 1 % CPU. Jetzt lehnen `POST /checks`,
  `PUT /checks/{id}` mit geaenderter Konfiguration und Template-Definitionen solche Werte mit 422 ab; eine ganze Zahl
  bleibt fuer ein Feld mit Nachkommastellen gueltig, Ganzzahl-Felder wie `port` und `expected_status` nehmen nur ganze
  Zahlen ohne Nachkommastelle (`22`, nicht `22.0`). Keine Migration: Ein gespeicherter Zahl-String bleibt, bis die
  Konfiguration mit einer Zahl an seiner Stelle gespeichert wird. Doku: Monitoring-Administration (DE+EN).

- **Agent: scheitert der VM-Aufruf von `pvesh`, fehlt der Proxmox-Block (R-0471):** Scheiterte
  `pvesh get /cluster/resources`, hing es oder lieferte es kein JSON-Array, schickte der Agent den Proxmox-Block mit
  dem Node und ohne VMs, und der Check `proxmox_backup` las ihn als „Keine VMs/CTs gefunden“ = ok. Jetzt fehlt der Block,
  `proxmox_backup` bleibt ohne Daten, und das Log nennt den Grund (etwa
  `pvesh get /cluster/resources failed: timed out after 15s`, nie stderr). Eine leere VM-Liste bleibt „keine VMs“.
  Doku: Agent-Entwicklerseite (DE+EN).
- **Agent: SMART liest Platten hinter einem MegaRAID-Controller (R-0455):** Der Agent fragte jede Platte aus
  `smartctl --scan` ohne ihren Geraetetyp ab. Eine Platte hinter einem MegaRAID-Controller (Scan: `/dev/bus/N` mit
  Typ `megaraid,N`) kann smartctl so nicht erkennen: Sie kam ohne Modell und SMART-Status in den Report, und der
  Check `smart_health` meldete sie als „SMART FAILED“. Jetzt gibt der Agent den Typ aus dem Scan als `-d` weiter,
  ausser `scsi`, damit eine SATA-Platte an `/dev/sdX` ihre ATA-Attribute behaelt. Doku: Agent-Entwicklerseite
  (DE+EN).
- **Agent: ein Timeout von `systemctl` und `sc` heisst „timed out after 15s“ (R-0454):** Beendete das 15-s-Timeout
  einen haengenden Aufruf, las sich der Grund im Dienste-Block wie ein gescheiterter Aufruf: unter Linux
  `systemctl list-units failed: signal: killed`, unter Windows `sc query failed: exit status 1`. Jetzt lautet er
  `systemctl list-units failed: timed out after 15s` bzw. `sc query failed: timed out after 15s`; ein von aussen
  beendeter Aufruf behaelt sein Signal. Auch ein `pvesh`-Aufruf, den das Timeout beendet, gilt intern als Timeout.
  Doku: Agent-Entwicklerseite (DE+EN).
- **Server: FRP-Tunnel lehnen einen `extra_config`-Schluessel mit Zeilenumbruch am Ende ab (R-0468):**
  `POST /api/frp/tunnels` und `PUT /api/frp/tunnels/{id}` nahmen einen `extra_config`-Schluessel wie `"abc\n"` an,
  weil die Pruefung einen abschliessenden Zeilenumbruch uebersah. Der Generator schreibt die Schluessel ungequotet in
  die frpc-Config, die danach kein gueltiges TOML mehr war. Jetzt muss der ganze Schluessel aus `A-Z a-z 0-9 _ . -`
  bestehen, sonst `422`. Doku: API-Referenz (DE+EN).
- **Server: Scheduler-Jobs mit Datenbankzugriff laufen wieder (R-0411):** Der `scheduler`-Dienst (seit v0.38.0 der
  eigene Prozess fuer die periodischen Jobs) lud nur die Module seiner Jobs, nicht alle Datenbank-Modelle. Damit
  scheiterte seit v0.38.0 jeder seiner Jobs mit Datenbankzugriff, und APScheduler schrieb das nur ins Log:
  E-Mail-Benachrichtigungen gingen nicht raus, geplante Hooks liefen nicht, und die Aufbewahrungs- und Aufraeum-Jobs
  (etwa fuer Audit-Log und Glocke) blieben aus. Jetzt laden Web- und Scheduler-Prozess alle Modelle aus
  `apps/server/app/model_registry.py`. **Vor dem Update pruefen:** Nach dem Update laufen geplante Hooks wieder nach
  Plan; Hooks, die nicht mehr laufen sollen, vorher deaktivieren oder loeschen. Die Aufbewahrungs-Jobs holen beim ersten
  Lauf nach. Ausstehende E-Mails, die aelter als 7 Tage sind, verfallen beim Update (Alembic-Revision `c3e5a7b9d1f2`:
  Status `failed`, `last_error` „expired before delivery“); juengere gehen normal raus, die Glocke bleibt unberuehrt.
  E-Mail-Hinweise auf neu angelegte Admin-Konten wurden seit v0.38.0 nicht zugestellt: Admins pruefen Benutzerliste und
  Audit-Log (Aktion `user.created`) fuer diese Zeit. Doku: Betrieb (DE+EN) nennt die Logs des `scheduler`-Dienstes.
- **Update: Rollback bei Pull-, Paket-Repo- und Stack-Neustart-Fehlern (R-0411):** Scheitert das Ziehen der Images
  (Netz, Rate-Limit, nicht veroeffentlichtes Image), das Aktualisieren des Agent-Paket-Repos, `docker compose up -d`
  oder der Healthcheck danach, rollt `update.sh` Laufzeit-Dateien und Image-Pins auf den installierten Stand zurueck,
  auch bei einem Floating-Tag (`:latest`, `:main`): Die Pins kommen aus einer Kopie der alten `.env`, sodass der
  naechste Lauf das Update erneut versucht. Scheitert es vor dem Neustart, kommt die alte `.env` ganz zurueck, und die
  Container bleiben unveraendert. `--no-rollback` nennt den Weg zurueck (`--redeploy` bzw. `--ref`). Fehlt die `.env`,
  bricht `update.sh` vor Backup und Snapshot ab; scheitert das Ziehen bei `--redeploy`, endet es mit eigener Meldung,
  und die Container bleiben unveraendert. Doku: Installation (DE+EN).
- **Update: Rollback stellt den installierten Stand vollstaendig her, die `.env` wird vorab geprueft (R-0470):**
  Scheiterte beim Neu-Pinnen der Images das Schreiben der `.env` (etwa bei voller Platte), ersetzte `update.sh` die
  `.env` durch eine gekuerzte Datei mit nur den Image-Pins und meldete das Update als fertig. Jetzt schreibt es die
  neue `.env` in eine Kopie daneben und tauscht sie erst, wenn alles geschrieben ist. Scheitert ein Teil der
  `.env`-Migration (neue Keys, neue Secrets, Image-Pins), rollt `update.sh` wie bei einem Pull-Fehler zurueck:
  Laufzeit-Dateien und die ganze alte `.env` kommen zurueck, die Container bleiben unveraendert; mit `--no-rollback`
  nennt die Meldung `--ref` als Weg weiter. Ein Rollback entfernt jetzt auch die Dateien, die erst das neue Release
  mitgebracht hat, und stellt `./repo` genau auf den Stand vor dem Update; ein Verzeichnis `.env.ah-new` im Weg nimmt
  keine Kopie der alten `.env` mehr auf. Bei einem Floating-Tag nennen `--check`, `--redeploy`, die Update-Meldung und
  die Rollbacks den Tag (etwa `:main`, ohne `SERVER_IMAGE` `:latest`) statt `unknown`. Scheitert mit `--no-rollback`
  der Neustart oder der Healthcheck, sagt die Meldung jetzt auch, dass Alembic die Datenbank beim Start schon migriert
  haben kann, und nennt `restore.sh`. Nach einem Selbst-Update entfernt die neue `update.sh` auch das temporaere
  Verzeichnis des abgebenden Laufs; ist dieser noch eine `update.sh` vor diesem Stand, bleibt es beim ersten Update
  noch liegen. Vor dem ersten `docker compose`-Aufruf prueft `update.sh` jetzt die `.env`: Enthaelt ein unquotierter
  oder doppelt gequoteter Wert ein `${` ohne gueltigen Platzhalter, an dem Compose jeden Aufruf mit „Invalid template“
  abbricht, endet `update.sh` mit dem Namen des Schluessels (ohne den Wert), bevor es etwas aendert, auch bei
  `--check` und `--redeploy`. Bisher scheiterte das Update daran erst nach Backup, Tausch und Neu-Pinnen. Doku:
  Installation und Betrieb (DE+EN) beschreiben, wie ein `$` in einem `.env`-Wert zu schreiben ist.
- **Update: Rollback auch bei einem gescheiterten Tausch der Laufzeit-Dateien (R-0495):** Scheiterte beim Tausch
  ein Schritt (etwa eine Kopie bei voller Platte, ein Verzeichnis `<datei>.ah-new` im Weg oder das Entfernen eines
  nicht mehr ausgelieferten Skripts), endete `update.sh` mit der rohen Meldung des Werkzeugs und liess halb
  getauschte Dateien neben der alten `.env` stehen. Jetzt meldet es „Tausch der Laufzeit-Dateien fehlgeschlagen“
  und rollt wie bei einer gescheiterten `.env`-Migration zurueck: Die Laufzeit-Dateien kommen aus dem Snapshot,
  Dateien, die erst das neue Release mitgebracht hat, verschwinden, keine halbe Kopie bleibt liegen, `.env` und
  Container bleiben unveraendert. Mit `--no-rollback` bleiben die Dateien stehen, und die Meldung nennt
  `--ref <Ziel>` als Weg weiter. Doku: Installation (DE+EN).
- **Install: Die `.env` wird nur durch eine vollstaendig geschriebene ersetzt (R-0496, R-0516):** Scheiterte beim
  Setzen von `DOMAIN`, `MTLS_ENFORCE` oder den Image-Pins das Schreiben der `.env` (etwa bei voller Platte), ersetzte
  `install.sh` die `.env` durch eine gekuerzte Datei ohne die Secrets, startete den Stack trotzdem und meldete die
  Installation als fertig. Jetzt schreibt es wie `update.sh` in eine Kopie neben der `.env` und tauscht sie erst,
  wenn alles geschrieben ist. Scheitert ein Schritt, bricht `install.sh` mit dem Namen des Schluessels (ohne den
  Wert) ab, die Kopie verschwindet, die `.env` bleibt beim letzten vollstaendigen Stand, und Stack, Admin und
  Enroll-Token werden nicht angelegt. Dasselbe galt fuer `init-secrets.sh`, das `install.sh` und `update.sh`
  aufrufen: Nach einem solchen Schreibfehler hielt es die verlorenen Secrets fuer leer, erzeugte sie still neu und
  endete erfolgreich, sodass Postgres-Passwort und CA-Passphrase nicht mehr zu den Volumes passten. Es schreibt
  jetzt ebenso ueber eine Kopie und endet bei einem Fehler mit dem Namen des Schluessels; `install.sh` bricht dann
  ab, `update.sh` rollt wie bei einer gescheiterten `.env`-Migration zurueck.
- **Monitoring: Ausfaelle von Docker, ZFS und SMART werden sichtbar, Container nach ihrem Ende bewertet (R-0419):**
  Ein gestoppter Docker-Daemon und ein haengendes oder scheiterndes `zpool list` blieben stumm: Der Agent liess den
  Block weg, der Check stand auf `unknown`, das nie benachrichtigt, und die Anzeige behielt die alte Container- bzw.
  Pool-Liste. Jetzt schickt der Agent den Docker- und den ZFS-Block, sobald `docker` bzw.
  `zpool` installiert ist, bei einem Ausfall mit `available: false`, einem Fehler-Code (`daemon_unreachable`,
  `timeout`, `cli_failed`, `parse_failed`) und einem kurzen Text ohne stderr; `docker_health` und `zfs_health` stehen
  dann auf `warning` und benachrichtigen. Fehlt der Block, leert der Check die gespeicherte Liste. `docker_health`
  bewertete nach der Restart-Policy: Ein abgestuerzter Container (`Exited (3)`) ohne Policy, `paused` und `created`
  galten als ok, ein von Hand gestoppter mit `always` als critical. Jetzt entscheidet das Ende: Exit ≠ 0, OOM, ein
  gescheiterter Start (`created` mit Exit ≠ 0), `restarting` und `dead` sind critical, ein steigender
  Neustart-Zaehler, `unhealthy` und `paused` warning; ein gewollter Stopp (Exit 0, Exit 143 oder 137 ohne OOM,
  `exited` mit `always`/`unless-stopped`, nie gestartet) gilt als gestoppt und zaehlt als ok. Exit-Code, OOM,
  Neustart-Zaehler, Healthcheck und Restart-Policy holt der Agent aus einem gebuendelten `docker inspect` als JSON. Im
  Standard-Template „Docker Host“ (`consecutive_fails` 2) ist ein einzelner Neustart nur in der Container-Liste zu
  sehen (Grund `restarted`); Status und Alarm folgen erst bei wiederholten Neustarts. Ein neuer Check, dessen erstes
  Ergebnis `unknown` ist, stand gruen; jetzt steht er auf `unknown`. `smart_health` liess einen Host ohne `smartctl`
  wie eine VM ohne Platten aussehen; jetzt nennt die Meldung den Grund (`smart_absent`: `not_installed` „No SMART
  data: smartctl is not installed“, `scan_failed` „No SMART data: the SMART query failed“, `no_devices` „No SMART
  data: no SMART-capable devices found“), der Status bleibt ok. Der Desktop zeigt einen Docker- oder ZFS-Ausfall mit
  uebersetztem Fehler statt „—“, zaehlt gestoppte Container getrennt („3 laufen · 1 gestoppt“) und nennt je Container
  den Grund (Exit-Code, OOM, Neustarts, Healthcheck, pausiert, gestoppt). Der Report traegt dafuer additiv
  `available`, `error`, `error_message`, je Container `exit_code`, `oom_killed`, `restart_count` und `health` sowie
  `smart_absent`; die Check-Details tragen je Container `category` und `reason`.
- **Desktop: der Tunnel mit Geraete-Zertifikat startet unter Windows (R-0425):** Der Desktop setzte den Pfad seiner
  exportierten Geraete-Identitaet (unter `%APPDATA%`) unveraendert in die Tunnel-Config ein. Dort steht er in einem
  TOML-String, in dem ein Backslash ein Escape einleitet: Ein Windows-Pfad wie `C:\Users\…` machte die Config
  unlesbar, und der Tunnel startete nicht. Jetzt setzt der Desktop den Pfad TOML-korrekt ein (Backslash,
  Anfuehrungszeichen und Steuerzeichen escaped), auch mit `'`, `"` oder Leerzeichen im Pfad.
- **Desktop: HTTPS-Tunnel greifen auch ohne STCP-Tunnel (R-0432):** Wer keinen STCP-Tunnel sieht, fuer den stoppt
  der Desktop frpc, und dabei verwarf er auch die Tunnel-Zuordnungen. Verbindungen mit einem HTTPS-Tunnel oeffneten
  dann ihre eigene Adresse statt `https://<Custom-Domain>`. Jetzt laedt der Desktop die Zuordnungen auch ohne
  STCP-Tunnel; scheitert das Laden, bleiben die bisherigen, und nur Abmelden leert sie. Doku:
  Entwickler-Doku Desktop (DE+EN).
- **Desktop: der Tunnel uebernimmt Aenderungen selbst (R-0402, R-0389, R-0390):** Der Desktop lud das
  Tunnel-Bundle nur beim Anmelden. Ein spaeter angelegter, geaenderter oder geloeschter Tunnel und eine Rotation
  des frps-Tokens kamen erst nach einem Neustart der App an, und ein frpc, der endete (etwa weil frps beim
  Anmelden nicht erreichbar war), blieb weg. Jetzt gleicht der Desktop im Modus `server` alle 60 s ab, nach dem
  Speichern im eigenen Tunnel-Dialog sofort. Aendern sich nur Tunnel, laedt frpc sie nach, ohne die uebrigen
  Tunnel und ihre offenen Verbindungen zu trennen; nur ein neues Token oder eine neue Adresse des FRP-Servers
  startet frpc neu, offene Sitzungen brechen dann ab. Ist frps nicht erreichbar, versucht frpc es weiter; endet
  frpc unerwartet, verbindet sich der Desktop selbst wieder (nach 5 s, dann mit wachsender Pause bis 60 s); der
  Knopf „Neu verbinden“ an der Tunnel-Anzeige stoesst das sofort an. Wer keinen STCP-Tunnel sieht, bekommt beim
  Anmelden keine Fehlermeldung mehr. Ein gestoppter Tunnel (etwa nach dem Abmelden) meldet sich nicht mehr
  nachtraeglich als „Tunnel getrennt“, und Abmelden ueber die Kopfzeile beendet jetzt auch den Tunnel.
- **Agent: ein spaeter angelegter Tunnel greift ohne Neu-Provisionieren (R-0398):** Ein Agent-Host, der ohne
  FRP-Tunnel provisioniert wurde, bekam einen spaeter angelegten Tunnel nie: Die Provisionierung schrieb die
  Sync-Config `/etc/frp/adminhelper.conf` samt Server-API-Key nur mit FRP-Paket, und der Abgleich endete still.
  Jetzt schreibt jede Provisionierung sie, und der naechste Agent-Lauf (Linux) richtet einen neuen Tunnel ein: Er
  schreibt die `frpc.toml` und aktiviert `frpc.service` dauerhaft (`systemctl enable --now`, also auch ueber einen
  Reboot); ein laufender frpc uebernimmt die neue Config. Aendern sich nur Tunnel, laedt er sie per Reload ueber
  seine lokale Admin-API nach (nur `127.0.0.1`, zufaelliges Passwort in `/etc/frp/admin.conf`, `0600`; der Reload
  geht nur an den eigenen frpc), und offene Sitzungen ueber unveraenderte Tunnel bleiben bestehen; bisher trennte
  jede Tunnel-Aenderung per Neustart alle Sitzungen zum Host. Aendern sich frps-Adresse, Token oder TLS, startet der
  Agent frpc neu, ebenso bei jeder Neu-Provisionierung. Laeuft frpc trotz Tunnel nicht, etwa weil nach einem Reboot
  ein anderer Prozess den Admin-Port belegt, legt der naechste Lauf die Admin-API auf einen neuen Port mit neuem
  Passwort. Einen lokal gestoppten oder deaktivierten frpc startet der naechste Lauf ebenso wieder, solange der Host
  Tunnel hat; dauerhaft aus bleibt er, wenn die Tunnel des Hosts auf dem Server geloescht oder deaktiviert sind. Ohne
  Tunnel laeuft kein frpc mehr: Faellt der letzte Tunnel weg oder hat der Server fuer den Host keine FRP-Config,
  stoppt und deaktiviert der Agent `frpc.service`, loescht die `frpc.toml` (sie enthaelt das frps-Token) und endet
  ohne Fehler. Vor die `frpc.toml` des Servers setzt der Agent `loginFailExit = false`: Ist frps beim Start nicht
  erreichbar, versucht frpc es weiter, statt sich zu beenden und von systemd alle 5 s neu gestartet zu werden. Diesen
  lokalen Kopf setzt der Server nicht; einen Server-Text mit `webServer` oder `loginFailExit` wendet der Agent nicht
  an. Auf Hosts, deren frpc beim Update schon laeuft, kommen der lokale Kopf und der Reload mit der naechsten
  Config-Aenderung, die frpc einmal neu startet. Hat ein aelterer Agent den Host ohne Tunnel provisioniert, fehlt
  dort der Server-API-Key fuer den Abgleich; solche Hosts werden einmal neu provisioniert, bis dahin nennt das
  Agent-Log diesen Weg. Die Admin-Doku (Agent-Deployment, DE+EN) und die Entwickler-Doku (Go-Agent, DE+EN)
  beschreiben es.
- **FRP: die frpc-Config eines Hosts bleibt nach einem Server-Neustart gleich (R-0435):** Bei zwei oder mehr
  berechtigten Nutzern stand `allowUsers` in der frpc-Config nach jedem Neustart des Servers, mit
  `WEB_CONCURRENCY` > 1 auch je Worker, in anderer Reihenfolge. Damit aenderte sich der Config-Hash, ohne dass sich
  etwas geaendert hatte, und der Agent schrieb die frpc-Config neu und startete frpc neu. Jetzt steht `allowUsers`
  aufsteigend sortiert in der Config. Nach dem Update aendert sich der Config-Hash von Hosts mit mehreren
  berechtigten Nutzern einmal, und der Agent holt die Config einmal neu.
- **FRP: die Tunnel stehen in der frpc-Config in fester Reihenfolge (R-0452):** Die `[[proxies]]` standen in der
  Reihenfolge, in der die Datenbank die Tunnel lieferte. Wurde einem Tunnel eine Verbindung zugeordnet oder seine
  Verbindung geloescht, konnte er darin hinter die uebrigen Tunnel rutschen; damit aenderte sich der Config-Hash, ohne
  dass sich die Config geaendert hatte, und der Agent holte die Config neu. Jetzt stehen die `[[proxies]]` ueberall,
  wo der Server eine frpc-Config erzeugt (Sync, Provisionierungs-Paket, Downloads), nach Tunnel-Name sortiert. Nach
  dem Update aendert sich der Config-Hash von Hosts mit mehreren Tunneln einmal, sofern ihre Tunnel bisher anders
  standen, und der Agent laedt frpc einmal neu. Doku: Entwickler-Doku Server (DE+EN).
- **Monitoring: Linux-Dienste werden richtig gezaehlt und gemeldet (R-0418):** Der Check `service_process` im Modus
  `auto` (Standard-Template „Linux Server — Standard“) stand auf einem frisch installierten Host dauerhaft auf
  `warning`, weil er auch regulaer beendete oneshot-Dienste, per Condition uebersprungene und per Timer oder Socket
  gestartete Units als „Inaktiv (autostart)“ meldete. Der Agent prueft diese Kandidaten jetzt mit einem gebuendelten
  `systemctl show` nach und laesst sie weg; der Monitoring-Dienst uebernimmt seine Liste, statt sie bei vollem Inventar
  selbst zu berechnen, sodass volle und gedrosselte Pushes dasselbe Ergebnis geben. Der Modus `list` meldete nach
  normaler Provisionierung jeden Namen als ausgefallen, weil der Agent ohne `monitor init --services` keine Dienste
  schickt. Jetzt wertet der Monitoring-Dienst die Namen selbst aus dem Inventar des Agents aus, mit oder ohne
  `.service` und ueber Aliase (`sshd` fuer `ssh.service`); ein Name ohne Daten zaehlt nicht als ausgefallen und steht
  neutral als „nicht gefunden“ da, ein neu eingetragener hat bis zu einer Stunde noch keine Daten. Der Desktop zeigte
  „Alle 0 OK“ oder „0/N laufen“ und ohne Daten eine rote Pille; jetzt zeigt er die Zahl der Probleme in der Farbe des
  Check-Status, „x/y aktiv“ nur, wenn der Agent Zaehler schickt, ohne Daten „Noch keine Daten“, jeden Dienst einmal
  und uebersetzte Hinweise. `ignore` versteht Glob-Muster (`drkonqi-coredump-processor@*`), und scheitert `systemctl`,
  ist der Check `unknown` mit Grund statt „Alle systemd-Units OK“. Der Check-Editor erklaert die Felder Dienste und
  Ignorieren und entfernt doppelte Eintraege. Der Report traegt dafuer additiv `systemd.counts`, `systemd.error` und
  `alias_of` im Inventar; `all_services` ist nach Unit sortiert und laesst nicht installierte, nur referenzierte Units
  weg. Im Modus `list` traegt `_details.watched` je Name `state` (`running`, `down`, `nodata`) neben `running`.
- **Desktop: der Vertrauensdialog beim ersten Kontakt liegt ueber dem Login-Screen (R-0399):** Praesentiert der
  Server beim ersten Login oder bei der ersten Registrierung ein Zertifikat der internen CA, fragt der Desktop in
  einem Dialog, ob dem Server vertraut werden soll. Dieser Dialog war vom Login-Screen verdeckt: Anmelden und
  Registrieren blieben ohne Rueckmeldung stehen. Jetzt liegt er sichtbar darueber.
- **Agent: Docker-Container werden mit aktueller Docker-CLI wieder erfasst (R-0417):** Ab Docker 28.2 gibt
  `docker ps -a --format '{{json .}}'` das Feld `Platform` als Objekt aus. Der Agent las jede Zeile als reine
  Zeichenketten, verwarf damit jede Zeile und schickte keine Container mehr; `docker_health` stand auf „Keine
  Docker-Daten im Report“. Jetzt liest er nur die genutzten Felder (`ID`, `Names`, `Image`, `State`, `Status`) und
  uebergeht alle anderen; das Report-Format bleibt gleich. Ist Docker installiert, der Daemon aber nicht erreichbar,
  scheitert `docker ps` oder sind Zeilen nicht lesbar, schreibt der Agent eine Warnung ins Log, die auch der Bericht
  von `adminhelper-agent diagnostics` zeigt. Die Docker-Sektion im Desktop sagt „Alle N Container laufen“ nur noch,
  wenn alle laufen, sonst „X von N laufen“, und ohne Docker-Daten im Report „keine Daten“ statt „—“.
- **Agent: Erneuerung und Provisionierung ersetzen die Identitaet nacheinander (R-0384):** Die Erneuerung im
  Dienst und `adminhelper-agent provision` konnten die Identitaet gleichzeitig ersetzen. Verschraenkten sich ihre
  Schreibvorgaenge, lag danach der Schluessel der einen neben dem Zertifikat der anderen. Kam eine Erneuerung vor
  der Provisionierung beim Issuer an und speicherte ihr Zertifikat danach, war es eines, dessen Linie die
  Provisionierung hatte widerrufen lassen. Beides sperrte den Agent aus, bis er neu provisioniert wurde. Jetzt
  haelt jede der beiden die Sperrdatei `agent.lock` im Identitaetsverzeichnis vom ersten Lesen der Identitaet bis
  zum Speichern der neuen: Eine Provisionierung wartet hoechstens eine laufende Erneuerung ab und nennt deren
  Zertifikat als ersetzt, eine wartende Erneuerung findet das frische Zertifikat und erneuert nicht.
- **Desktop: Geraete-Identitaet und Pin lassen sich wieder zuruecksetzen (R-0395):** Die Rueckfragen vor dem
  Zuruecksetzen, auf dem Login-Screen („Geraete-Identitaet zuruecksetzen“, „Gepinntes Server-Zertifikat
  zuruecksetzen“) und in den Einstellungen, liefen ueber den nativen Dialog von `@tauri-apps/plugin-dialog`. Den
  erlaubten die Capabilities nicht (nur `dialog:allow-save`), die Ablehnung ging verloren, und die Knoepfe taten
  nichts. Jetzt fragt der App-eigene Dialog, wie beim Loeschen im Monitoring; sein Bestaetigungsknopf traegt die
  Aktion. Escape schliesst darin nur die Rueckfrage, nicht die Einstellungen darunter. Ein Vertragstest prueft,
  dass jede Funktion, die die Oberflaeche aus dem Dialog-Plugin nutzt, in `capabilities/default.json` erlaubt ist.
  Ein gescheiterter Export des Browser-Zertifikats nennt jetzt hinter der Meldung seine Ursache.
- **Server: die Server-CLI schreibt Audit-Eintraege (R-0397):** `python -m app.cli create-admin`, `reset-admin` und
  `mint-enroll-token` liessen keine Spur im Audit-Log, obwohl derselbe Vorgang ueber die API protokolliert wird. Jetzt
  schreibt jeder erfolgreiche Aufruf einen Eintrag (`user.created`, `user.password_reset`,
  `enrollment.token.minted_for`) mit dem Actor `system` und dem Label `cli`; abgelehnte Aufrufe schreiben keinen.
- **Server: der Agent-Report-Proxy reicht jede Server-ID durch (R-0391):**
  `POST /api/monitoring/agent/{server_id}/report` setzte die dekodierte `server_id` unkodiert in die Ziel-URL zum
  Monitoring-Dienst. Ein Steuerzeichen (`%1F`) endete mit 500, ein `?` oder `#` (`%3F`, `%23`) schnitt die Ziel-URL
  ab und traf eine andere Route des Dienstes. Der Proxy kodiert die `server_id` jetzt wieder; der Monitoring-Dienst
  sieht dieselbe ID wie der Server.
- **Desktop: ein neu gestarteter Tunnel steht nicht mehr auf getrennt (R-0247):** Startete der Tunnel neu (Stop,
  dann Start), endete der alte frpc-Prozess oft erst, als der neue schon lief. Sein Ende ging trotzdem ans Fenster,
  und die Anzeige stand auf „Tunnel getrennt“, obwohl der Tunnel lief. Jetzt meldet nur der laufende frpc-Prozess
  sein Ende.
- **Agent: eine Provisionierung waehrend einer Erneuerung beschaedigt die Identitaet nicht mehr (R-0308):** Die
  Pruefung vor dem Enroll-Antrag (`adminhelper-agent provision`) und die Erneuerung im Dienst schrieben dieselben
  Temp-Dateien `agent.key.tmp`, `agent.crt.tmp` und `ca.crt.tmp`. Lief die Pruefung zwischen dem Schreiben und dem
  Umbenennen einer Erneuerung, aktivierte die Erneuerung die Platzhalter der Pruefung als `agent.key`, `agent.crt`
  und `ca.crt`, und der Agent hatte keine brauchbare Identitaet mehr. Jeder Schreibvorgang legt jetzt eine eigene
  Temp-Datei an (`agent.key.<zufall>.tmp`), und die Pruefung raeumt genau ihre eigenen.
- **Funde des ersten Messlaufs im Worker:** Der Preflight fragt `claude --version` und `auth status`
  mit stdin `/dev/null` und einer Frist (R-0230); ein geerbtes `AH_LOOP_*` lenkt `ledger_loop_test`
  nicht mehr auf den echten Klon (R-0231); was eine Bau-Session oder ein Close an Prozessen
  hinterlaesst, beendet der Loop ueber eine Marke in deren Umgebung (R-0226); fehlende oder unlesbare
  Reviewer-Kosten zaehlen mit ihrem Deckel, nie als 0, und ein Ledger ohne Schluss-Newline gilt nicht
  mehr als Aenderung ausserhalb der Task (R-0190, R-0191); die Review-Probe findet `ruff` auch ohne
  ihn auf dem PATH (R-0234).
- **Hooks: Cron-Intervalle werden wirklich geprueft (R-0235):** `POST /api/hooks` und `PUT /api/hooks/{id}`
  nahmen jedes Intervall aus fuenf Feldern an, auch `a b c d e` oder `61 * * * *`; der Scheduler konnte es nicht
  lesen und uebersprang den Hook bei jedem Abgleich, ohne Meldung. Die Routen pruefen jetzt mit dem Parser des
  Schedulers und antworten auf ein unlesbares Intervall mit 422. Ein schon gespeicherter Hook mit so einem
  Intervall laeuft weiter nicht, der Scheduler meldet ihn aber einmal mit einer Warnung im Log.
- **Desktop-E2E: ein gescheiterter Build macht den Lauf rot (R-0259):** `onPrepare` in
  `apps/desktop/e2e/wdio.conf.js` baut die App mit `cargo tauri build`. Scheiterte der Build, schrieb wdio den
  Fehler nur ins Log und liess die Specs gegen das Binary eines frueheren Laufs laufen; der Lauf meldete PASS.
  `onPrepare` wirft jetzt eine `SevereServiceError`, und der Lauf endet vor dem ersten Spec mit Exit 1. Ein
  Unit-Test unter `test/unit/` prueft das ohne Display und ohne Rust und laeuft in `npm run lint` mit.
- **Desktop: Registrieren und Zuruecksetzen in den Einstellungen nur mit Anmeldung (R-0244):** Stellte man im
  Einstellungs-Dialog nur den Modus auf `server`, ohne angemeldet zu sein, erschien das Token-Feld; eine
  Registrierung lief dann gegen die eingetragene URL und startete keinen Tunnel. Token-Feld und Zuruecksetzen
  erscheinen jetzt nur mit Anmeldung; ohne sie bietet der Login-Screen dieselben Wege.
- **Desktop: Speichern der Einstellungen bei laufendem Tunnel (R-0245):** Im Modus `server` startete jedes
  Speichern den Tunnel erneut, auch bei einer Sprach- oder RDP-Einstellung; neben dem laufenden frpc scheiterte
  das mit „frpc laeuft bereits“, die Anzeige ging auf getrennt, und die Statusleiste meldete einen Fehler. Ein
  laufender Tunnel bleibt jetzt, wie er ist; gestartet wird nur, wenn keiner laeuft.
- **Desktop: Fehleranzeigen im Fenster ohne `ERR_*`-Codes (R-0261):** Wie zuvor die Statusleiste (R-0248) zeigten
  die Benachrichtigungs-Einstellungen einen Fehler beim Laden oder Speichern samt Maschinen-Code, etwa nach einem
  Zertifikatswechsel am Server `… ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: …`; ebenso die Ansible-Seite und die
  Monitoring-Uebersicht ihren Ladefehler. Jetzt erscheint nur der Text.
- **Desktop: Statusleiste ohne `ERR_*`-Codes (R-0248):** Ein Netzwerkfehler aus dem Backend traegt die
  Maschinen-Codes (`ERR_TOFU_PIN_MISMATCH`, `ERR_CA_PIN_MISMATCH`, `ERR_TLS_UNKNOWN_ISSUER`) in seiner Meldung,
  und die Statusleiste zeigte sie mit, etwa nach einem Zertifikatswechsel am Server als `Tunnel: …
  ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: …`. `reportError` nimmt die Codes jetzt fuer alle Meldungen heraus,
  wie R-0243 es fuer die Registrierung in den Einstellungen tat; der Text dahinter bleibt.
- **Desktop: Fehler der Registrierung in den Einstellungen ohne Code (R-0243):** Scheiterte die Registrierung
  in den Einstellungen, stand der rohe Text samt Code da, etwa `ERR_TLS_UNKNOWN_ISSUER: …`. Jetzt erscheint nur
  der Text, wie im Login.
- **Desktop: Login nennt das fehlende Geraete-Zertifikat (R-0222):** Unter erzwungenem mTLS weist das
  Gateway ein Geraet ohne Zertifikat schon vor dem Login mit 400 ab; der Login zeigte bisher nur
  „Login fehlgeschlagen (400 Bad Request)“ samt Fehlerseite. Jetzt sagt er, dass der Server ein
  Geraete-Zertifikat verlangt, und fuehrt per Knopf zum Formular fuer den Einmal-Token. Jede andere
  Login-Meldung bleibt, wie sie war.
- **Desktop: Registrieren ueber eine vorhandene Identitaet ohne unpassendes Paar (R-0220):** Wer sich
  mit einem neuen Einmal-Token registrierte, waehrend noch eine Identitaet im Keyring lag, bekam erst
  den neuen Schluessel und danach das Zertifikat geschrieben; ein Abbruch dazwischen liess den neuen
  Schluessel neben dem alten Zertifikat stehen, und unter erzwungenem mTLS sperrte sich das Geraet aus.
  Jetzt loescht die Registrierung erst die alte Identitaet und schreibt dann die neue, das Zertifikat
  zuletzt. Ein Abbruch hinterlaesst schlimmstenfalls ein Geraet ohne Identitaet, das einen neuen Token
  braucht.
- **Desktop: Meldung nach dem Zuruecksetzen der Geraete-Identitaet (R-0212):** Die Bestaetigung stand in
  dem Teil der Einstellungen, der beim Zuruecksetzen verschwindet, und war deshalb nie zu sehen. Sie
  erscheint jetzt, zusammen mit dem Feld fuer den neuen Token.
- **Review-Probe bei totem Code samt angekuendigtem Test (R-0227):** `scripts/dev/review-probe.sh` probt
  einen Test-Diff, der nur aus Tests besteht, die die Task als `Test-Löschung:` ankuendigt (samt ihren
  Import- und Leerzeilen), nicht mehr: ohne die Aenderung war dort nichts rot, und `check-verdict`
  sperrte das approve des Reviewers. Die Antwort heisst `only-declared-deletion` und steht sichtbar in
  der Review-Zeile; ein Ersatztest oder jede andere Aenderung am Test-Diff wird weiter geprobt. Dazu
  `review.sh declared-only`, und `task-close.sh` gibt der Probe die Task mit.
- **Zeitstempel der Monitoring-Antworten in UTC mit `Z` (R-0202):** Die Antworten unter
  `/api/monitoring/*` schreiben ihre Zeitstempel (`createdAt`, `updatedAt`, `since`, `lastCheck`,
  `sentAt`, `startsAt`, `endsAt`) als RFC 3339 in UTC mit `Z`, wie die Server-API seit R-0064; bisher
  trugen sie keine Zone. Der Desktop las die Zeit der letzten Pruefung und des Alarm-Logs deshalb als
  Ortszeit und zeigte sie um den Abstand zu UTC verschoben; er liest einen Wert ohne Zone jetzt als
  UTC, auch von einem aelteren Monitoring-Dienst. Keine Migration: `createdAt`/`updatedAt` von vor dem
  2026-07-09 (NEU-8.14b) koennen um den Offset abweichen. **Hinweis fuer eigene Skripte** gegen
  `/api/monitoring/*`: Wer die Werte als String vergleicht oder selbst zerlegt, muss das `Z` erwarten;
  `datetime.fromisoformat` liest beide Formen ab Python 3.11, aeltere Versionen ersetzen `Z` vorher durch
  `+00:00`. Doku: API-Referenz, „Zeitstempel".
- **Hooks: ungueltige Eingaben im dokumentierten Fehler-Format (R-0207):** `POST /api/hooks` und
  `PUT /api/hooks/{id}` antworteten bei fehlendem oder ungueltigem `schedule_interval` und bei fehlenden
  oder unbekannten `event_triggers` mit einem 422, dessen `detail` ein String war. Die OpenAPI und die
  API-Referenz versprechen eine Liste von `{loc, msg, type}`; so antworten die Routen jetzt, mit den
  bisherigen Texten als `msg`. Die Web-Oberflaeche zeigt bei jedem 422 mit solcher Liste jetzt die
  `msg`-Texte (mit „; “ verbunden) statt „HTTP 422“ — auch bei den Pydantic-Fehlern der uebrigen Routen.
- **Desktop: Passwort fuer den Browser-Export (R-0219):** Die Einstellungen liessen ein Passwort ab 8
  Zeichen zu, der Export selbst verlangt 12; ein Passwort mit 8 bis 11 Zeichen endete in der
  allgemeinen Meldung „angemeldet und Server erreichbar?“. Die Einstellungen verlangen jetzt die
  dokumentierten 12 Zeichen, gezaehlt wie im Backend, und sagen das.
- **SSRF-Guard nennt den Grund (R-0045):** Der HTTP-Check und der Alert-Webhook des Monitorings sowie die
  Hook-Funktionen `http_get`/`http_post` des Servers melden ein Ziel, dessen Host nicht aufloest
  (DNS-Fehler oder Zeitlimit), jetzt als solches (`could not be resolved … rejected by the SSRF guard`)
  statt als private/reservierte Adresse. Abgelehnt wird es weiter, ohne Request; die Meldung fuer
  private Ziele bleibt unveraendert.
- **Server-Datenbank-Sessions in UTC (R-0209):** Jede Verbindung des Servers setzt ihre Session
  auf `UTC`, unabhaengig von der Zeitzone des Postgres-Clusters (der Stack startet ihn mit
  `TZ=Europe/Berlin`) und von einem `PGTZ` in der Umgebung. Postgres rechnete einen Zeitwert mit
  Offset bisher in die Session-Zeitzone um, bevor er in eine Spalte ohne Zeitzone ging; diese Spalten
  halten aber UTC. Bereits gespeicherte Werte bleiben, wie sie sind (keine Migration), die
  API-Ausgabe auch.
- **Desktop: Tunnel-Hinweis ohne Identitaet (R-0203):** Startet ein Tunnel ohne mTLS-Zertifikat,
  verweist die Meldung jetzt auf die Registrierung des Geraets mit einem Einmal-Token vom Admin
  statt auf eine Anmeldung am Server — seit ADR 0003 enrollt der Login nicht.
- **Zeitstempel der Server-API in UTC mit `Z` (R-0064):** Die Antworten schreiben ihre Zeitstempel
  als RFC 3339 in UTC mit `Z`. Bisher trugen die meisten keinen Offset — auch die vier Felder, fuer
  die das OpenAPI `format: date-time` verspricht (`created_at` der API-Keys, `created_at`, `last_run`
  und `next_run` der Hooks; die uebrigen sind `string` oder untypisiert) —, und Audit und
  Notifications den Offset der Datenbank-Session; Web und Desktop lasen Werte ohne Offset als
  lokale Zeit und zeigten sie um den Abstand zu UTC verschoben. Das OpenAPI bleibt unveraendert,
  die Datenbank auch (keine Migration); die
  Schemathesis-Ausnahmen der API-Key-Routen sind gefallen. **Hinweis fuer Hook-Skripte:** `last_run`
  und `triggered_at` im Kontext eines Hook-Skripts tragen jetzt beide `Z` (`last_run` etwa
  `2026-10-05T12:00:00Z` statt `2026-10-05T12:00:00`, `triggered_at` `…Z` statt `…+00:00`); ein
  Skript, das die Werte als String vergleicht oder selbst zerlegt, muss das `Z` erwarten.
  `datetime.fromisoformat` liest alle drei Formen ab Python 3.11, aeltere Versionen ersetzen `Z` vorher
  durch `+00:00`. Doku: API-Referenz, „Zeitstempel", und Hooks.
- **Server: Zeitstempel in den tz-naiven Spalten durchgehend als naive UTC (Konvention F7):** Vier Schreibstellen
  (`enrollment/service.py`, zweimal `provisioning/router.py`, `core/auth.py`) gaben zeitzonenbehaftete Werte an
  `DateTime`-Spalten ohne Zeitzone; Postgres legte sie dann in der Zeitzone der Datenbank-Session ab statt in UTC wie
  die uebrigen tz-naiven Spalten. Sie schreiben jetzt ueber `utcnow_naive()` aus `app/core/time.py`, und der Abgleich
  in `cleanup_expired_blacklist` liest mit derselben Konvention, mit 12 h Spielraum fuer Zeilen aus der Zeit davor (sie
  tragen die Ortszeit der Session). Ein neuer Test prueft die Spalten unter einer Session-Zeitzone ungleich UTC.

- **Red Team und Waechter unabhaengig vom geprueften Nutzer (R-0156, R-0158 bis R-0163):**
  Die Proben von `scripts/dev/runner-redteam.sh` auf git, Proxmox, D-Bus und Settings fuehren
  keinen Code und keine ausfuehrbare Konfiguration des Runners mehr aus (die Modellproben starten
  bewusst seine CLI, nach Pruefsumme und Settings, die sie bei einem FAIL nicht aufhalten). Die Push-Proben pushen aus einem eigenen Repository ohne Hooks und ohne
  git-Konfiguration des Nutzers an die URLs des Klons und lesen seine Konfiguration auf
  Credential-Helper, Extra-Header und URL-Umschreibungen; Aenderungen am Klon zeigt die ctime statt
  `git status`. Probe 4 misst den Proxmox-Token direkt an der API (`curl -q`, Token ueber stdin)
  gegen ein Ziel, das `runner-setup.sh` root-eigen als `pve-target.env` ablegt, statt `vm.py` aus dem
  Klon zu starten. Die D-Bus-Probe prueft den Socket statt ein `busctl` ohne `XDG_RUNTIME_DIR`, die
  Runner-Settings werden byte-genau mit der geprueften Kopie verglichen, und ein unbekanntes
  Argument endet mit Exit 2 statt im vollen Lauf. `scripts/dev/hooks/harness-guard.sh` zaehlt die
  Ausgabe-Optionen von git als Schreibziel (`--output` jedes Aufrufs, `archive -o`,
  `format-patch -o`, `bundle create`, `grep -O`), und der Runner-Hook ist fail-closed: fehlt der
  Waechter oder haengt er, sperrt der Hook mit Exit 2. Anleitung: `DEVELOPMENT.md` „Runner-User" (Red Team) und
  „Harness-Schutz und Kill-Switch".

- **FRP: Generate-Routen nur mit nutzbaren Tunneln (Server, R-0128):** `visitor-toml`, `visitor-bundle` und
  `frpc-toml` lassen STCP-Tunnel ohne Secret weg, bevor sie pruefen, ob ein Tunnel da ist. Bleibt keiner uebrig,
  antworten sie mit demselben `404` wie ohne Tunnel, und `bulk-zip` schreibt fuer einen solchen Nutzer keine
  `visitors/<user>.toml`. Das `auth.token` von frps steht damit nur in einer Datei, die auch einen Tunnel
  enthaelt. Doku: `docs/developer/api-reference.html`.
- **FRP: Secret und Visitor-Port nur an STCP-Tunneln (Server, R-0129):** Ein HTTPS-Tunnel speichert weder
  `secret_key` noch `visitor_port`; `POST` verwirft mitgeschickte Werte, und der Wechsel per `PUT` auf HTTPS
  loescht beide. Der Wechsel zurueck auf STCP erzeugt ein neues Secret und vergibt einen freien Port, wenn der
  gespeicherte inzwischen einem anderen Tunnel gehoert. Das heilt auch aeltere Zeilen ohne Datenmigration;
  bisher endete dieser Rueckwechsel mit `409`. Doku: `docs/developer/api-reference.html`,
  `docs/admin/frp-tunnel.html`.
- **FRP: bulk-zip nur mit nutzbaren Tunneln (Server, R-0148):** `bulk-zip` laesst STCP-Tunnel ohne Secret
  einmal vorab weg. Ein Server ohne nutzbaren Tunnel bekommt keine `clients/<server>/frpc.toml` mehr (bisher eine
  mit `auth.token` und ohne Proxy), ohne nutzbaren STCP-Tunnel gibt es keine `visitor.toml`; im Extremfall
  enthaelt der ZIP nur `frps.toml`. Das ist dieselbe Regel wie der `404` der Einzelrouten. Je Tunnel ohne Secret
  steht eine Warnung im Log statt einer je Server, Nutzer und Generator-Aufruf. Doku:
  `docs/developer/api-reference.html`.
- **SSE: ein Worker verpasste kurz nach dem Start ein Refresh-Signal (Server, R-0149):** `subscribe()` schickt
  das Abo an Redis nur ab; ein `publish` vor der Bestaetigung ging verloren, Pub/Sub puffert nicht.
  `stream_hub.start()` liest jetzt die Bestaetigung (hoechstens 5 s), bevor es den Reader startet und
  „subscribed" meldet. Bleibt sie aus, warnt es und startet den Reader trotzdem; die Clients fallen wie bisher
  auf Polling zurueck. Das behebt auch den sporadisch roten `test_redis_fanout_only_to_targeted_user`.
- **Verbindungen: nur bekannte Felder gehen in Spalten (Server, R-0136):** Beim Anlegen, Aendern und
  Importieren uebernimmt der Server nur die Felder der API (`name`, `kind`, `host`, …, in camelCase) in
  die Spalten einer Verbindung. Alles andere bleibt Zusatzinformation in `extra_data`, auch ein
  Schluessel, der wie eine Spalte heisst (`extra_data`, `created_at`). Beim Lesen gewinnen die bekannten
  Felder gegen Eintraege aus `extra_data`; ein `extra_data`, das kein JSON-Objekt ist (aeltere Zeilen),
  wird mit einer Warnung im Log ausgelassen, statt die Liste mit `500` abzubrechen.
- **OpenAPI: exakte BIGINT-Grenze (Server):** Das veroeffentlichte Schema (`/openapi.json`) traegt die
  Obergrenze der BIGINT-Felder im Request-Body als Ganzzahl `9223372036854775807`. FastAPI tippt
  `maximum` als Float, dort stand bisher `9.223372036854776e+18`, 193 ueber der echten Grenze. Die
  Pruefung zur Laufzeit war davon nicht betroffen. `app/core/openapi.py` schreibt die Grenze in das
  erzeugte Schema zurueck; der Snapshot aendert genau diese Zahl, oasdiff meldet keine Aenderung.
- **FRP: U+007F in Konfigurationswerten (Server):** Die Felder, die der Server in die erzeugten
  FRP-TOML-Dateien schreibt (FRP-Server-Config, Tunnel, Servername), lehnen neben den anderen
  Steuerzeichen jetzt auch U+007F (DEL) mit 422 ab. TOML verbietet das Zeichen in einem
  String; eine `frps.toml` damit konnte frps nicht lesen.
- **Web-Panel: F5 waehrend eine Liste laedt (R-0107):** `apps/web/src/lib/api/client.ts` gibt
  bei einem 2xx, dessen Body sich nicht lesen laesst (Reload bricht die Uebertragung ab, oder
  kein JSON), nicht mehr still `null` zurueck, sondern wirft `ApiError(status, 'Invalid response
  body')`. Die Seiten Benutzer, API-Keys, Hooks und Audit lasen `.length` auf dem `null` und
  endeten im `pageerror` „Cannot read properties of null (reading 'length')", den der Live-Smoke
  fand; jetzt zeigen sie ihren Fehler-Toast. 204 und ein gueltiges JSON-`null` bleiben `null`.
  `docs/developer/webui.html` (DE+EN) sagt dazu, dass der Access-Token nur im Speicher liegt.
- **Wartungsfenster mit Offset am Kalenderrand (Monitoring):** `POST /maintenance` und
  `PUT /maintenance/{id}` antworten auf ein `starts_at`/`ends_at` mit Zeitzonen-Offset, das in
  UTC umgerechnet vor dem Jahr 1 oder nach dem Jahr 9999 laege (etwa
  `0001-01-01T00:00:00+00:01`), mit 422 und Feldbezug statt mit 500. Die Umrechnung lief als
  ungefangener `OverflowError` durch. Ein naives Datum im Jahr 1 bleibt gueltig.
- **`restore.sh` auf einem frischen Host:** das Skript wartet jetzt ueber TCP auf Postgres
  (`pg_isready -h 127.0.0.1`), ueber denselben Weg, den der DB-Restore danach nimmt. Auf einem
  neuen Volume lauscht der Init-Server des offiziellen Images nur auf dem Unix-Socket; die
  Socket-Probe meldete ihn bereit, und `psql`/`createdb` scheiterten dann mit
  `Connection refused` — je nach Timing brach die Wiederherstellung mittendrin ab. Dieselbe
  Warteschleife in `scripts/tests/sse_push_e2e.sh` ist mit korrigiert.
- **422 statt 500 an den Raendern der API (Server und Monitoring):** Eingaben, die erst in der
  Datenbankschicht scheiterten, werden jetzt am Rand geprueft. Betroffen waren alle drei
  Eingangswege: die int-Pfad- und Query-Parameter (`user_id`, `key_id`, `offset`), die
  Integer-Felder und die Id-Liste im Request-Body (FRP-Ports, `ids` von
  `POST /api/notifications/read`) und Textfelder, in denen ein NUL-Byte stand
  (`POST /api/enrollment/token/for`, die Filter von `GET /api/audit`, die Skript- und
  Namensfelder von `/api/hooks`, `server_ids` von `POST /api/users`, die Textfelder von
  `POST /api/internal/events`, der Name von `POST /api/api-keys`) — jeder davon lief bis
  hierher als ungefangener
  `NumericValueOutOfRange` bzw. `DataError` durch und kam als HTTP 500 zurueck. Die Schranken
  stehen als `minimum`/`maximum` im OpenAPI-Schema und stammen je Feld aus dem Spaltentyp des
  Modells; fuer Clients, die gueltige Werte senden, aendert sich nichts.
- **Tag-Validator und Fremdschluessel am Rand (Server):** ein `tags`-Wert vom falschen Typ
  (dict, int, bool, Liste mit Nicht-Strings) ergibt eine Validierungsmeldung statt
  `AttributeError` bzw. `TypeError` — das betraf sechs Routen. Ein nackter String wird dabei
  jetzt abgelehnt: `tags: "ops"` ergab bisher still die drei Ein-Zeichen-Tags `o`, `p`, `s`
  und ergibt nun 422. Und eine unbekannte `serverId` beim Anlegen, Aendern oder Importieren
  einer Verbindung ergibt 422 mit Feldbezug statt einer durchlaufenden `ForeignKeyViolation`.
- **Schemathesis-Ausschluesse, Bilanz (Server 27 -> 29, Monitoring 4 -> 1):** im Server sind
  zwei Eintraege hinfaellig und entfernt, acht gelten nur noch fuer einen einzelnen Check statt
  fuer die ganze Route — dort laeuft die 500er-Pruefung wieder mit, genau die Pruefung, die
  diese Klasse gefunden hat. Einer (`GET /api/frp/tunnels`) ist umgekehrt verbreitert worden,
  weil dort ein NUL-Pfad zum bestehenden Grund dazukam (im naechsten Punkt wieder verengt).
  Vier sind neu, alle vier fuer die Catch-all-Routen des Monitoring-Proxys, und das ist kein
  Produktfehler, sondern eine Eigenschaft der Testfixture. Im Monitoring fallen die drei
  `offset`-Eintraege weg.
  Die NUL-Klasse, die dieser Lauf nur dort behoben hatte, wo er sie zeigte, ist inzwischen
  flaechig geschlossen (naechster Punkt).
- **NUL-Byte am Rand, flaechig (Server und Monitoring):** ein NUL-Byte (`U+0000`) in einer Eingabe
  ergibt jetzt 422 mit Feldbezug statt HTTP 500 — gleich auf welchem Weg es kommt. Im Pfad und im
  Query-String prueft eine Middleware vor dem Routing (`loc` `["path"]` bzw. `["query", <name>]`),
  in einem Request-Body jedes Request-Schema ueber eine gemeinsame Basisklasse bis in
  verschachtelte Listen und Objekte (`loc` ist der Weg bis zum Wert), und im Monitoring ebenso
  der Agent-Report, dessen Body kein Modell ist. Postgres speichert kein `0x00` in einem Textwert;
  bisher starb jede solche Eingabe im Treiber, ausser an den Feldern, die ein Fuzz-Lauf gezeigt
  hatte. Die Regel ist bewusst flaechig: auch dort, wo ein NUL nie eine Textspalte erreichte —
  Passwoerter, Tokens, Tags und Zusatzfelder einer Verbindung, unbekannte Felder und Query-Namen —
  antwortet die API jetzt 422 statt 200, 201 oder 401. Das OpenAPI-Schema aendert sich nicht.
  Schemathesis-Ausschluesse, gegen den vorigen Stand ausgezaehlt: Server 29 -> 23 — sechs
  NUL-Ausschluesse entfernt, zwei von der ganzen Route auf einen Check verengt
  (`GET /api/frp/tunnels`, dessen Verbreiterung aus dem vorigen Punkt damit zurueckgenommen ist,
  und `POST /api/connections`); Monitoring unveraendert 1.

- **Capstone, Visitor-Rolle:** der frpc-Visitor startete mit `sudo sh -c … &` und hielt damit stdout/stderr
  der ssh-Sitzung — `vm.py run` (ohne pty) sah nie EOF und lief 50 Minuten in den Timeout, obwohl die
  Pruefung acht Sekunden braucht. Jetzt per `setsid` mit `</dev/null` gestartet und am Ende beendet; ein
  hermetischer Guard (`box_scripts_guard_test.sh`) verbietet solche Hintergrundstarts in allen Box-Skripten.

- **VM-Hygiene (R-0048/R-0049):** `.devenv.sh` reist nicht mehr per `vm.py sync` auf die Box
  und damit auch nicht mehr in ein Template — auf der Box bleibt `AH_REQUIRED` ungesetzt und die
  Box-Regel macht alle Schritte eines schweren Layers zur Pflicht. `iter.sh` verlaengert die
  Warm-Box mit der Frist, mit der sie gewaermt wurde (`desktop_ttl` in `.vm/warm.env`), statt
  mit dem eigenen 8h-Default: eine 20-Minuten-Box wurde bisher beim ersten Lauf still zur Nacht-Box.

- **Konfigurations-Stellhebel, die nichts bewirkt haben (Harness Stufe 8a, T6):** `DB_POOL_SIZE` und
  `DB_MAX_OVERFLOW` waren in `.env.example` samt Rechenregel dokumentiert, wurden aber von keinem
  Compose-Dienst durchgereicht — wer sie setzte, aenderte nichts. Sie gehen jetzt an `server` und
  `scheduler`. `CA_FRPS_EXTRA_SANS` (eigene SANs fuers frps-Leaf) war umgekehrt im Compose vorhanden,
  aber nirgends dokumentiert. Entfernt wurden drei tote Keys: `DOMAIN` und `EXTRA_SANS` beim Dienst
  `server` (nichts in `apps/server` liest sie; sie gehoeren dem ca-issuer und dem Gateway) sowie
  `PGPASSWORD` bei `server` und `scheduler` (deren Entrypoints rufen nur `pg_isready`, das sich nicht
  authentifiziert — nur das Monitoring nutzt `psql`). Ein neuer Test haelt die drei Beschreibungen
  ab jetzt zusammen.

- **Wochenlauf (Harness Stufe 3b):** Auf der Box sind unter `--strict` alle Schritte der
  schweren Layer Pflicht (`AH_REQUIRED` ungesetzt ⇒ Layer-Menge; `crabbox_iter.sh` reicht ein
  gesetztes `AH_REQUIRED` durch, `heavy.sh` setzt die Dev-Box-Menge zurueck) — ein Self-SKIP
  von `upgrade-path` oder einer GUI-Suite ist kein gruener Lauf mehr, sondern UNVERIFIED. Der
  Capstone-Report nennt die Ursache, wenn crabbox das Setup einer Rolle abgebrochen hat
  (Folgefehler `infra` je Rolle statt Produktfehler); die Rollen-Setups upgraden die Fat-Box
  nicht mehr (`--no-upgrade`, Zeitgrenzen 3000 s). Ein roter `audit.yml` erzeugt eine
  Roadmap-Zeile je roter Phase statt je Lauf; `history.csv` ist RFC-4180-gequotet; der
  Migrations-Smoke-Teardown droppt ohne `WITH (FORCE)`.

### Removed

- **Worker-Loop, Builder-Profil, Runner-Nutzer, Harness-Waechter-Parser, diff-scan (Dev-Werkzeuge, Team v3):**
  Der Bau laeuft in einer Session mit Sub-Agenten; die Gates, die den autonomen Lauf absichern sollten, entfallen
  mit ihm, ebenso der Reviewer-Prozess (`review-run.sh`, `review-probe.sh`, Schemas, Vertragsliste) und
  `lane.sh`. Den Token-Scan (`review.sh sec`, Git-Hooks, CI-Guard) gibt es weiter.

- **crabbox (Harness Stufe 2b):** Das externe Binary und alles, was nur fuer es da war —
  `.crabbox.yaml`, der Workflow `crabbox.yml`, die Agent-Skill `.agents/skills/crabbox/`,
  `scripts/tests/crabbox_lib.sh` und die Wrapper `crabbox_warm|iter|reap|bake|multibox.sh`.
  Die beiden lokalen Verzeichnisse `.crabbox/` und `.crabbox-out/` bleiben vorerst
  gitignoriert und vom Sync ausgenommen: `.crabbox/captures` enthaelt unredigierte
  Fehler-Bundles, und dieses Repo ist oeffentlich. Loeschen — dann koennen die zwei
  Eintraege mit.

- **Desktop: Tauri-Command `enroll_device` (R-0040):** das Enrollment ueber die Login-Session hatte keinen
  Aufrufer in der UI; die App enrollt seit ADR 0003 mit einem Einmal-Token (`enroll_with_token`). Entfernt sind
  der Command, `enrollment::enroll` und der Zweig in `mint_token`, der nur dafuer ein Access-Token anforderte; der
  Browser-Export (`export_browser_p12`) nach dem Login bleibt. Der IPC-Inventar-Test fuehrt keinen Command ohne
  UI-Aufrufer mehr. `docs/developer` (DE+EN) nennt fuer den Desktop jetzt den Einmal-Token statt „nach Login".

### Changed

- **Deinstallation: der Schritt „Secrets“ entfernt auch die Kopien der `.env`:** `install.sh`, `update.sh` und
  `init-secrets.sh` schreiben die `.env` ueber eine Kopie daneben (`.env.ah-XXXXXX`, `.env.ah-new`), die nach einem
  Abbruch liegen bleiben kann und dieselben Secrets traegt. Beantwortet man in `uninstall.sh` die Frage nach der
  Secrets-Datei mit Ja (auch mit `--yes`), entfernt das Skript neben `.env` und `.env.restored` jetzt auch jede Datei
  und jedes Verzeichnis `.env.ah-*` im Install-Verzeichnis; `.env.example` bleibt. Ohne Ja bleiben alle liegen.
  Doku: Installation (DE+EN); sie nennt bei den Host-Daten jetzt auch `./repo`, das das Skript schon bisher entfernt.
- **Agent: der Windows-Dienst meldet ein nicht gesichertes Log-Verzeichnis im Ereignisprotokoll (R-0556):** Laesst
  sich das Log-Verzeichnis nicht sichern, schreibt der Agent wie bisher nur auf stdout und keine `agent.log`; unter
  dem Dienststeuerungs-Manager sah das niemand. Laeuft er als Windows-Dienst, schreibt er dann beim Start genau eine
  Warnung ins Windows-Ereignisprotokoll (Windows-Protokolle → Anwendung, Quelle `AdminHelper-Agent`, Ereignis-ID 1)
  mit dem Verzeichnis, dem Grund und den Folgen: bis zum Neustart des Dienstes nur stdout, und der FRP-Sync aendert
  nichts, solange sich das Datenverzeichnis nicht sichern laesst. Ein Aufruf von Hand bleibt ohne Hinweis, Linux ist
  unveraendert. `service install` registriert die Quelle, damit der Eintrag eine Beschreibung hat, und
  `service uninstall` entfernt sie wieder; scheitert das, gibt der Befehl eine Warnung aus. Bei einem Dienst, den eine
  fruehere Version eingerichtet hat, fehlt die Beschreibung, der Text steht dann in den Ereignisdaten. Doku:
  Agent-Deployment und Entwickler-Doku Agent (DE+EN).
- **Plaene gibt die Session selbst frei (Entwickler-Werkzeuge, Kevin 2026-10-21):** Nach dem Plan-Commit von
  `/feature-plan` setzt die Session `roadmap.py approve` selbst und baut. Kevin behaelt seine Entscheidungen aus
  `CLAUDE.md` §2 (Roadmap, sichtbares Verhalten, API-Vertraege, Datenmigrationen, Restrisiko, Release); eine offene
  Frage aus seinem Bereich haelt nur die Task, die an ihr haengt (`[?]`). `roadmap.py approve` behaelt die Notiz der
  Zeile. Regeln: `CLAUDE.md` §2, §4, §8, §11 und `tasks/README.md`.

- **SSRF-Schutz verbindet zur geprueften Adresse (Server und Monitoring):** Der Alert-Webhook und der HTTP-Check des
  Monitorings (dieser fuer die erste URL und jeden Redirect-Hop) sowie die Hook-Helfer `http_get`/`http_post` des
  Servers loesen das Ziel einmal auf, pruefen alle Adressen und verbinden zu einer davon (der Reihe nach, bis eine
  annimmt), statt dass httpx den Namen beim Verbinden ein zweites Mal aufloest; Host-Header und TLS-Name (SNI,
  Zertifikatspruefung) bleiben der Hostname. Ist fuer das Schema der URL ein Proxy aus `HTTP_PROXY`, `HTTPS_PROXY`
  oder `ALL_PROXY` gesetzt (bei den Hook-Helfern `HTTP_PROXY` oder `HTTPS_PROXY`, die der Hook-Runner durchreicht),
  geht die Anfrage wie bisher ueber den Proxy. Doku: Monitoring-Administration, Monitoring- und
  Hook-Entwicklerdoku (DE+EN).
- **Desktop: Workspaces statt Moduswechsel (R-0431):** Der Modus in den Einstellungen entfaellt: Die Art legt ein
  Workspace beim Anlegen fest, Name, Farbe und URL aendert der Picker, solange der Workspace geschlossen ist; im
  Fenster stehen sie als Anzeige. Die Einstellungen trennen „Dieser Workspace“ (Abmelden, Zertifikate,
  Geraete-Identitaet, Token, Browser-Zertifikat, Benachrichtigungsregeln, Sync-Intervall) und „Alle Workspaces auf
  diesem Geraet“ (Sprache, Passwoerter, RDP, OS-Benachrichtigungen, Diagnose); Speichern beendet weder Sitzung noch
  Tunnel. Der Login nimmt nur die URL des Workspace (ein URL-Feld gibt es nur, solange er keine hat), „Workspaces…“
  ersetzt „Ohne Server fortfahren“, und ein Benutzer einer Installation meldet sich nur in einem Workspace an.
  Sync-Workspaces laden nie mit dem Geraete-Zertifikat und registrieren kein Geraet; wer gegen die eigene Installation
  unter mTLS synchronisiert, nimmt einen Server-Workspace. Doku: Desktop fuer Entwickler (DE+EN), README, DEVELOPMENT.
- **Desktop: die bisherigen Daten gehen in den Workspace „Standard“ (R-0431):** Der erste Start legt „Standard“ im
  bisherigen Modus mit dessen URL, Einstellungen und Verbindungen an. Nicht leere lokale Verbindungen ausserhalb des
  lokalen Modus ergeben zusaetzlich „Lokal“, eine Sync-URL ausserhalb des Sync-Modus „Sync“, eine Server-URL
  ausserhalb des Server-Modus „Server“. Die Einstellungen fuer alle Workspaces (Sprache, Passwoerter, RDP,
  OS-Benachrichtigungen) gehen nach `prefs.json`, die Portkarten-Eintraege an den migrierten Server-Workspace
  („Standard“ oder „Server“). Die migrierten Workspaces teilen sich die Eintraege im System-Schluesselbund von
  vorher, gespeicherte RDP-Passwoerter und eine Geraete-Identitaet bleiben nutzbar. Die Altdateien (`settings.json`,
  `connections*.json`) bleiben unveraendert liegen; eine aeltere Version liest sie nach einem Downgrade wieder,
  Aenderungen aus der Workspace-Zeit sieht sie nicht. Der Picker nennt die Migration einmal. Ist die bisherige
  `settings.json` nicht lesbar, startet der Desktop trotzdem: Er benennt sie unveraendert in
  `settings.json.unreadable-<UTC-Zeit>` um, legt nur „Standard“ an, lokal, mit den lokalen Verbindungen oder, gab es
  keine lokale Datei, den Verbindungen aus dem bisherigen Cache, setzt die Einstellungen fuer alle Workspaces auf die
  Vorgaben und nennt die Datei einmal im Picker; fuer einen Server legt man dann einen neuen Server-Workspace an und
  registriert das Geraet dort neu. Doku: Desktop fuer Entwickler (DE+EN), README, Troubleshooting (DE+EN).
- **Desktop: ein zweiter Start oeffnet den Launcher (R-0431):** Ein zweiter Programmstart holt den laufenden Launcher
  nach vorn oder oeffnet ihn, statt das Fenster der laufenden App zu zeigen; Workspaces laufen nebeneinander in
  eigenen Prozessen. Logdatei und Diagnose-Bericht gehoeren je einem Prozess (`adminhelper.log` fuer den Launcher,
  `adminhelper-<id>.log` je Workspace). Die Laufzeitdateien des Tunnels (`visitor.toml`, exportierte Identitaet) liegen
  je Workspace und nur, solange der Tunnel laeuft. Doku: Desktop fuer Entwickler (DE+EN), README.
- **Monitoring: Entwarnung erst nach `consecutive_oks` ok in Folge (R-0424):** Ein Check mit gemeldetem Problem
  (`warning`/`critical`) geht erst nach `consecutive_oks` `ok`-Messungen in Folge zurueck auf `ok`, im Scheduler- wie
  im Push-Pfad und auch beim Agent-Heartbeat; bis dahin steht er auf dem gemeldeten Status und zeigt die Meldung mit
  dem Zusatz „(recovery n/m)“. Jede andere Messung dazwischen beginnt die Zaehlung von vorn: Ein Check, der flattert
  oder abwechselnd `ok` und `unknown` liefert, entwarnt erst nach `consecutive_oks` `ok` in Folge. Ein gemeldetes
  Problem, das ueber `unknown` zurueckkommt, wird ebenso gehalten; ein nie gemeldetes, etwa waehrend Wartung oder
  Host-down stumm gebliebenes, entwarnt beim ersten `ok` still wie bisher. Bestehende Checks bekommen mit der
  Migration `3c66308d11a7` den Default 2: Ihre Entwarnung kommt ein Check-Intervall spaeter als bisher, bei einem
  Check mit Intervall `1h` eine Stunde; 1 ist das bisherige Verhalten. Die Host-down-Unterdrueckung faellt
  entsprechend erst nach der Haltezeit des Heartbeats. `consecutive_oks` (1–100) laesst sich je Check und je
  Template-Definition setzen, eine Definition ohne das Feld gilt als 2; an einem Template-Check geaendert gilt es als
  angepasst, der Sync laesst es stehen, und „Auf Template zuruecksetzen“ nimmt den Wert des Templates zurueck. Doku:
  Admin- und Entwickler-Doku Monitoring (DE+EN).
- **Monitoring: Disk Forecast der Standard-Templates entwarnt beim ersten `ok` (R-0424):** „Linux Server — Standard“
  und „Windows Server — Standard“ setzen fuer Disk Forecast (Intervall `1h`) `consecutive_oks` 1, er entwarnt also
  beim ersten `ok` statt eine Stunde spaeter. Alle anderen Checks der Standard-Templates, auch SMART Health
  (Intervall `5m`), behalten den Default 2. „Linux Server — Standard“ steigt dafuer auf Version 3, „Windows Server —
  Standard“ auf Version 2: Ein unveraendertes Template uebernimmt sie beim Start des Monitoring-Dienstes und
  synchronisiert seine Server, ein am Check angepasstes `consecutive_oks` bleibt; ein Template mit angepassten
  Definitionen zeigt „Update verfuegbar“. Doku: Admin-Doku Monitoring (DE+EN).
- **Monitoring: die `severity` eines Checks deckelt Glocke, Betreff und Event-Hook (R-0424):** Ein Check meldet
  hoechstens mit seiner `severity`: Ein Check mit `severity` `warning` meldet ein `critical` des Checkers im Betreff
  von Mail und Webhook als `WARNING`, an die Glocke als `warning`, auch die Entwarnung, und loest den Event-Hook
  `alert.triggered` nicht mehr aus. Das betrifft etwa Disk Forecast aus den Standard-Templates, der damit hoechstens
  `warning` meldet. Ein Check mit `severity` `info` erreicht die Glocke nicht mehr, sein Betreff traegt `INFO`. Der
  Text der Meldung nennt weiter den echten Uebergang und die `severity`; `RECOVERY` im Betreff bleibt. Checks mit
  `severity` `critical` melden wie bisher. Doku: Admin-Doku Monitoring (DE+EN).
- **Monitoring: Glocken-Cooldown von 30 Minuten je Check (R-0424):** Die Glocke (Notification-Hub, auch seine
  persoenlichen E-Mails) erhaelt je Check hoechstens eine Problem-Meldung in 30 Minuten; bisher erhielt sie jede.
  Was in diese Zeit faellt, wird verworfen und nicht nachgeholt, und die Entwarnung eines Problems, das die Glocke so
  nie gezeigt hat, erhaelt sie auch nicht. Die Eskalation von `warning` auf `critical` und die Entwarnung eines
  gezeigten Problems gehen immer durch; die Entwarnung traegt die Stufe, mit der die Glocke das Problem gezeigt hat,
  auch wenn die `severity` des Checks inzwischen geaendert wurde. Der Event-Hook `alert.triggered` folgt der Glocke
  und damit diesem Cooldown: Geht ein Check binnen 30 Minuten erneut auf `critical`, etwa `critical`, `ok`, wieder
  `critical`, feuert der Hook nur beim ersten Mal; ein Agent einer Sammelmeldung, fuer den die Glocke im Cooldown ist,
  loest keinen Aufruf aus. Webhook und Mail der Alert-Regeln behalten ihren eigenen `cooldown_minutes`. Ein vor dem
  Update gemeldetes Problem bekommt seine Entwarnung in der Glocke. Doku: Admin- und Entwickler-Doku Monitoring,
  Entwickler-Doku Hooks (DE+EN).
- **Monitoring: ein nicht lesbares Proxmox ist `warning` mit Benachrichtigung (R-0492):** Liegt `pvesh` auf dem Host,
  schickt der Agent ab Report-Version 3 den Proxmox-Block bei jedem Push, auch wenn er Node-Status, Backup-Storages,
  deren Backups oder die VM-Liste nicht lesen kann: dann mit `available: false` und einem Fehler-Code statt der VMs
  (`timeout`, `cli_failed`, `parse_failed`, `backup_index_incomplete` fuer einen nicht aktiven Backup-Storage).
  Bisher fehlte der Block, und `proxmox_backup` stand ohne Benachrichtigung auf `unknown`. Jetzt meldet der Check den
  Ausfall wie Docker und ZFS als `warning` mit Benachrichtigung, etwa
  „Proxmox unavailable (timeout): pvesh get /cluster/resources timed out after 15s“. `alert_on_unavailable: false`
  (neu in der Konfiguration von `proxmox_backup`, Default `true`, nur `true` oder `false`) laesst einen Ausfall auf
  `unknown` ohne Benachrichtigung stehen; im Check-Formular des Desktops ist das wie bei Docker und ZFS die Checkbox
  „Ausfall melden“. Fehlt der Block (`pvesh` deinstalliert, oder ein aelterer Agent kann
  Proxmox nicht lesen), bleibt der Check `unknown`, leert aber die zuletzt gezeigte VM-Liste; ein lesbares Proxmox
  ohne VMs leert sie ebenso. Die Check-Details tragen dazu `available` und `error`. Die Backup-Zeile im
  Server-Dashboard des Desktops zeigt im Ausfall den Fehler statt der VM-Liste, etwa „Backup-Storage nicht aktiv“,
  gelb bei `warning` und grau bei abgeschaltetem Ausfall; bisher blieb dort die zuletzt gelesene VM-Liste stehen, weil
  der Agent den Block wegliess. Das Standard-Template „Proxmox Host“ steht dafuer in Version 2 auf
  `consecutive_fails` 2 wie Docker und ZFS: ein einzelner Lesefehler von `pvesh` meldet nicht. Ein unveraendertes
  Template folgt der neuen Version beim Start automatisch, auch eines von vor den Template-Versionen; ein angepasstes
  bietet sie als Update an. Doku: Monitoring-Administration, Entwickler-Doku Agent und Monitoring (DE+EN).
- **Monitoring: nur fehlgeschlagene Dienste sind critical (R-0423):** Im Modus `auto` von `service_process` ist eine
  fehlgeschlagene Unit nur noch `critical`, wenn sie ein Dienst ist (`.service` oder ein Windows-Dienst ohne
  Unit-Endung); eine andere fehlgeschlagene Unit wie Mount, Timer oder Socket ist `warning`, wie eine enabled, aber
  inaktive Unit. Die Meldung nennt beide getrennt, etwa
  `Failed: nginx.service; Failed units: data.mount; Inactive (autostart): cron.service`; `ignore` greift wie bisher
  vorher, die Check-Details listen unter `failed` weiter alle fehlgeschlagenen Units. Doku:
  Monitoring-Administration, Entwickler-Doku Monitoring (DE+EN).
- **Monitoring: Platten-Alarm nur unter Mindest-GB frei, je Mount einstellbar (R-0423):** Der Prozent-Alarm einer
  Platte (`disk_warn`/`disk_crit`) in `agent_resources` zaehlt nur noch, wenn zusaetzlich weniger als
  `disk_min_free_gb` frei sind (Default 20 GB, auch fuer bestehende Checks ohne den Schluessel; `0` schaltet den
  Riegel ab); die Meldung nennt dann die freien GB, etwa „Disk / 85%, 15 GB free (>=85%)“. Steigen die freien GB
  ueber den Riegel, ist die Platte frei, auch aus der Hysterese heraus. Die freien GB meldet der Agent ab
  Report-Version 3, unter Linux und Windows; fuer aeltere Agents zaehlt wie bisher nur der Prozentwert. Je Mount setzt
  `disk_overrides` eigene `warn`, `crit` und `min_free_gb`; ein Mount aus `ignore_mounts` wird weder auf Belegung noch
  auf Inodes bewertet und steht in den Check-Details mit `ignored: true`. Beide nehmen exakte Mount-Pfade. Die
  Check-Details tragen je Platte dazu `free_gb`. Im Check-Formular des Desktops lassen sich `disk_min_free_gb`,
  `ignore_mounts` (Feld „Mounts ignorieren“, kommagetrennt) und `disk_overrides` (Tabelle „Schwellen je Mount“: je
  Zeile Mount, Warnung, Kritisch und Mindest-GB frei) bearbeiten, ebenso die Schwellen fuer Swap, Inodes und Load je
  CPU. Doku: Monitoring-Administration, Entwickler-Doku Agent und Monitoring (DE+EN).
- **Agent: CPU als Mittel seit dem letzten Report (R-0423):** `cpu_percent` ist jetzt der Anteil belegter CPU-Zeit
  seit dem letzten erfolgreich gesendeten Report statt einer 1-s-Stichprobe zu Beginn des Laufs; unter Linux mittelt
  der Agent damit ueber die 5 Minuten zwischen zwei Laeufen. Den Zaehlerstand dafuer legt er in `.report-state.json`
  neben `monitor.conf` ab (0600), geschrieben nur nach erfolgreichem Push; ein verlorener Push verlaengert das
  naechste Fenster. Im ersten Lauf, wenn der letzte erfolgreiche Report mehr als 15 Minuten zurueckliegt, nach einem
  Neustart, bei einem Zeitstempel in der Zukunft und beim Test-Push von `monitor init` misst er weiter die
  1-s-Stichprobe. Doku: Entwickler-Doku Agent und Monitoring (DE+EN).
- **Agent: Datenverzeichnis unter Windows mit festen Rechten:** Unter Windows legt der Agent sein Datenverzeichnis
  `%ProgramData%\AdminHelper` samt `frp`, `frp\pki`, `logs` und `identity` vor der ersten Nutzung mit festen Rechten
  an: Eigentuemer Administratoren, Zugriff nur fuer SYSTEM und Administratoren, nichts von `%ProgramData%` geerbt. Ein
  vorhandenes Verzeichnis mit anderem Eigentuemer uebernimmt er nicht, er entfernt es samt Inhalt und legt es neu an;
  eines von SYSTEM oder den Administratoren, etwa aus einer frueheren Version, behaelt er samt Inhalt und setzt seine
  Rechte neu. Eintraege darin mit anderem Eigentuemer entfernt er, ausser der Ordner war schon vorher nur fuer SYSTEM
  und Administratoren beschreibbar; dann uebernimmt er sie. Dateien, die der Agent dort anlegt, gehoeren den
  Administratoren. Bisher verwarf der Agent einen Fehler beim Sichern: Laesst sich die Datenwurzel, `frp` oder
  `frp\pki` nicht sichern, bricht `provision` jetzt mit einem Fehler ab, bei der Datenwurzel auch `monitor init`;
  laesst sich `identity` nicht sichern, ueberspringt `provision` das Enrollment und laeuft mit dem API-Key weiter, und
  eine faellige Erneuerung des Client-Zertifikats im Dienstlauf unterbleibt mit einer Warnung. Laesst sich das
  Log-Verzeichnis nicht sichern, etwa ohne Administratorrechte, schreibt er keine Log-Datei, nur auf stdout. Unter
  Linux bleibt es bei `0700`. Doku: Entwickler-Doku Agent (DE+EN).
- **Release: ein Beta ist ein Tag ohne Suffix (R-0014):** Ein Beta ist jetzt der Tag `vX.Y.Z` ohne Suffix,
  veroeffentlicht als GitHub-Pre-release; schon der Draft entsteht als Pre-release. Stable wird dasselbe Release
  spaeter ohne neuen Tag. Die Images `:latest` setzt `docker.yml` nicht mehr beim Tag-Push, sondern erst, wenn das
  Release von Pre-release auf Release wechselt: Es taggt das schon gebaute `:X.Y.Z` um, ohne neu zu signieren, und
  nur, wenn das Release `releases/latest` ist und jedes Image die Signatur seines Tag-Pushs traegt (`cosign verify`).
  `:latest` zeigt damit wie `releases/latest`, das `install.sh` ohne lokalen Checkout und `update.sh` lesen, nie auf
  ein Beta; wer ein Beta testen will, pinnt dessen Version (`:X.Y.Z`). Doku: Entwickler-Doku CI/CD (DE+EN).
- **Monitoring: die Check-Konfiguration nimmt nur endliche Zahlen und VMIDs aus dem Bereich von Proxmox VE:**
  Zahlenfelder wie `cpu_warn` oder `reallocated_warn` lehnen `Infinity`, `-Infinity` und `NaN` ab; bisher nahmen
  Felder ohne obere Grenze `Infinity` an und speicherten es. Eine Zahl in `exclude_vmids` muss zwischen 100 und
  999999999 liegen. Das gilt fuer Checks und fuer die Check-Definitionen eines Templates; gespeicherte Konfigurationen
  bleiben, wie sie sind. Scheitert eine Anfrage an den Monitoring-Dienst an der Pruefung und traegt ihr Body
  `Infinity` oder `NaN`, antwortet der Dienst jetzt mit einem 422, in dem der Wert als `null` steht, statt mit einem
  Serverfehler. Doku: Monitoring-Administration (DE+EN).
- **Monitoring: Versandfehler im Alert-Log mit festem Grund:** Scheitert der Versand eines Webhooks oder einer Mail,
  speichert das Alert-Log statt des Textes der Ausnahme einen festen englischen Grund je Fehlerart, etwa „Webhook
  request timed out“, „Webhook connection failed“, „SMTP TLS failed“, „SMTP authentication failed (535)“ oder „SMTP
  server refused the message“; andere Fehler nennen nur ihre Klasse, etwa „SMTP error (SMTPServerDisconnected)“ oder
  „Dispatch failed (ValueError)“ fuer eine Regel, die sich nicht verarbeiten laesst. Die Einzelheiten, etwa die
  Antwort des Mail-Servers, stehen weiter im Log des Monitoring-Dienstes; dessen Zeilen zu einem gescheiterten Webhook
  oder einer gescheiterten Mail sind jetzt englisch und nennen den Check, beim Webhook auch den Host des Ziels.
  Gespeicherte Eintraege behalten ihren Text. Doku: Monitoring-Administration (DE+EN).
- **Server: Datenbankfehler eines Hooks nur mit ihrem Typ:** Bricht ein Hook mit einem Fehler der
  Datenbankanbindung ab (`sqlalchemy.exc.SQLAlchemyError` oder `psycopg.Error`), nennen `error` und die Log-Zeile
  `Fehler: …` in `logs` nur den Typ des Fehlers, etwa `OperationalError`, nicht mehr den Text des Treibers. Jeder
  andere Fehler eines Hooks erscheint weiter mit seinem Text. Doku: Entwickler-Doku Hooks (DE+EN).
- **Server: Geheimnisse der FRP-Konfiguration zaehlen ohne Leerzeichen am Rand:** Ein neues `auth_token` oder
  `dashboard_password` der FRP-Server-Konfiguration und ein neuer `secret_key` eines STCP-Tunnels brauchen mindestens
  16 Zeichen ohne Leerzeichen am Anfang und Ende, sonst antwortet der Server mit `422` („must have at least 16
  characters besides leading and trailing whitespace“). Ein Wert nur aus Leerzeichen gilt damit nicht mehr als
  Geheimnis. Gespeichert wird der Wert so, wie er gesendet wurde; leer oder `null` wirkt wie bisher. Schon
  gespeicherte Werte bleiben unveraendert. Doku: Admin-Doku FRP-Tunnel und API-Referenz (DE+EN).
- **Server: die API lehnt einen Dashboard-Port ab, den frps nicht uebernimmt:** Ein `dashboard_port` der
  FRP-Server-Konfiguration gleich 443, gleich dem Bind Port oder gleich `FRP_BIND_PORT` ist beim Anlegen und beim
  Aendern ein `422` („the dashboard port must be neither 443 nor the bind port nor FRP_BIND_PORT (…)“), statt dass
  frps die Konfiguration erst beim Uebernehmen verwirft. `POST` prueft gegen den gesendeten Bind Port (ohne ihn
  7000); `PUT` prueft, sobald `dashboard_port` oder `bind_port` gesendet wird, den Stand nach dem Update mit dem Bind
  Port, den frps bekommt (ein gespeicherter `bind_port` `null` oder ausserhalb 1 bis 65535: 7000), meldet den
  Fehler auf dem gesendeten Feld und speichert nichts davon. Eine schon gespeicherte Konfiguration mit solchem Port
  bleibt unveraendert, ein `PUT` ohne beide Felder geht weiter durch, und die Pruefung beim Start meldet sie wie
  bisher. Die Web-Maske sendet beide Ports immer mit; dort ist ein solcher Port also vor dem Speichern zu aendern.
  Doku: Admin-Doku FRP-Tunnel und API-Referenz (DE+EN).
- **Desktop: Netzwerkfehler nennen die URL der Anfrage nicht mehr:** Scheiterte eine Anfrage des Desktops, etwa weil
  der Server nicht erreichbar war oder mit einem Fehlerstatus antwortete, nannte die Meldung in der Oberflaeche und im
  Log die vollstaendige URL der Anfrage samt Pfad und Query. Jetzt fehlt die URL; die Ursache bleibt in der Meldung,
  etwa „Connection refused“ oder der Status „500 Internal Server Error“. Doku: Desktop fuer Entwickler (DE+EN).
- **Desktop: frpc laeuft nur fuer die aktuelle Anmeldung:** Abmelden, eine neue Anmeldung und eine abgelaufene
  Sitzung (gescheiterte Erneuerung) beenden frpc jetzt im Desktop-Prozess selbst, nicht nur ueber die Oberflaeche;
  ein Abgleich, der dabei laeuft, startet keinen neuen. Kommt ein Visitor-Bundle fuer eine andere Anmeldung
  (Server-URL oder Benutzer) als die, fuer die frpc laeuft, startet frpc neu, statt die Visitors per Reload zu
  uebernehmen. Gespeicherte Passwoerter und die Tunnel-Aufloesung nutzen nur die Visitors des frpc der aktuellen
  Anmeldung. Doku: Desktop fuer Entwickler (DE+EN).
- **Desktop: ein gespeichertes RDP-Passwort gehoert zu genau einer Verbindung:** Ausser unter Windows lag ein
  gespeichertes RDP-Passwort im Schluesselbund unter Adresse, Port, Benutzer und Domaene; zwei Verbindungen mit
  denselben Werten, etwa von zwei Servern, teilten sich ein Passwort. Jetzt traegt der Eintrag auch die `id` der
  Verbindung. Ein bisher gespeichertes Passwort bleibt nutzbar: Es gilt fuer jede Verbindung zu diesem Ziel als
  gespeichert, bis die erste es oeffnet; diese uebernimmt es, fuer die anderen ist es danach nicht mehr gespeichert.
  Das gilt nicht fuer Ziele auf dem eigenen Rechner (`localhost` und Namen unter `.localhost`, Loopback- und
  unspezifizierte Adressen) wie die automatischen Verbindungen des Servers ueber `127.0.0.1`: Verbindungen
  verschiedener Server koennen dasselbe solche Ziel nennen, deshalb gilt ein bisheriger Eintrag dafuer fuer keine
  Verbindung als gespeichert, und das Passwort wird je Verbindung einmal neu eingegeben. Loeschen entfernt auch einen
  solchen bisherigen Eintrag. Unter Windows liegt es seit den Workspaces ebenfalls je Verbindung im Namensraum der
  App (siehe Added). Doku: Desktop fuer Entwickler (DE+EN).
- **Server: `{{` in Feldern der FRP-Configs wird abgewiesen:** frp liest seine Config-Dateien als Go-Template, bevor
  es die TOML liest; `{{` beginnt dort eine Template-Anweisung. Die API antwortet jetzt mit `422` auf `{{` im
  Servernamen (`/api/servers`), in `name` und `server_addr` der FRP-Server-Config und in `name`, `local_ip`,
  `secret_key`, `custom_domains`, `auto_connection_username` und den `extra_config`-Werten eines Tunnels, je beim
  Anlegen und Aendern. Ein einzelnes `{` und `}}` bleiben erlaubt; bereits gespeicherte Werte bleiben unveraendert.
  Doku: API-Referenz (DE+EN).
- **Desktop: die Sitzung liegt nur im Speicher des Desktop-Prozesses (R-0430):** Access- und Refresh-Token liegen
  nicht mehr im System-Schluesselbund und gehen nicht mehr an die Oberflaeche; die Eintraege frueherer Versionen
  loescht der Start einmal. Die Wahl „Selbstsignierte Zertifikate erlauben“ gilt fuer eine Sitzung so, wie sie bei
  der Anmeldung stand: Eine Aenderung wirkt ab der naechsten Anmeldung, auch fuer den Export des
  Browser-Zertifikats, der bisher den Haken im offenen Einstellungsdialog nahm.
- **Desktop: eigene lokale Ports fuer die Tunnel-Visitors (R-0430):** Der Desktop lauschte fuer jeden STCP-Tunnel
  auf dem Visitor-Port des Servers (Standard 6000–6999). War der Port auf dem Rechner belegt, etwa durch ein anderes
  Programm oder den Tunnel einer zweiten AdminHelper-Installation, erreichten die Verbindungen dieses Tunnels ihr Ziel
  nicht. Jetzt ist der Visitor-Port der Wunschport: Ist er belegt oder liegt er unter 1024, nimmt der Desktop einen
  freien Port aus 23000–23999 und behaelt ihn, solange der Tunnel besteht; nur ein beim Start des Tunnels fremd
  belegter Port wechselt. Die Zuordnung liegt in `port-registry.json` im App-Data-Verzeichnis, gilt fuer alle
  AdminHelper-Prozesse des Benutzers und steht in `tunnel_status` als `bindings`. Verbindungen auf einen Tunnel loest
  der Desktop auf den tatsaechlichen Port auf: eine mit dem Tunnel verknuepfte ueber die Tunnel-Zuordnungen, die nur
  Admins lesen, und ohne Zuordnung jede Verbindung auf `127.0.0.1` oder `localhost` mit dem Visitor-Port eines
  laufenden Tunnels. So legt der Server seine automatischen Verbindungen an; sie erreichen damit auch fuer Nicht-Admins
  den tatsaechlichen Port. Eine von Hand mit einem Tunnel verknuepfte Verbindung loest der Desktop weiter nur fuer
  Admins auf. Solange ein Tunnel laeuft, geht auch eine selbst angelegte Verbindung auf `127.0.0.1` oder `localhost`
  mit seinem Visitor-Port durch ihn. Doku: FRP-Tunnel (Administration), Desktop fuer Entwickler (DE+EN), README,
  DEVELOPMENT.
- **Server-CLI: `reset-admin` meldet die bestehenden Sitzungen ab:** Setzt `python -m app.cli reset-admin` das
  Passwort eines Benutzers zurueck, gelten danach wie beim Passwortwechsel ueber die API (`PUT /api/users/{id}`) die
  vor dem Reset ausgestellten Access- und Refresh-Tokens nicht mehr; der Benutzer meldet sich mit dem neuen Passwort
  neu an. Doku: Troubleshooting (DE+EN).

- **Monitoring: Die Checks melden englisch (R-0422):** Die Push-Checker (`agent_ping`, `agent_resources`,
  `service_process`, `proxmox_backup`, `zfs_health`, `docker_health`, `smart_health`), die Pull-Checker (`http`,
  `ping`, `tcp`) und die Check-Engine meldeten teils deutsch, und diesen Text zeigen Dashboard, Glocke und
  Benachrichtigungen unveraendert, auch in der englischen Oberflaeche. Jetzt sind die Meldungen englisch, mit denselben
  Werten wie vorher, etwa „Waiting for agent data“, „All services OK“, „No backup: …“ oder „Timeout after 10s“. Ein
  gedaempfter Fehlschlag endet auf „(failure 1/2)“ statt „(Fehler 1/2)“, ein HTTP-Check ohne TLS-Pruefung auf
  „[TLS verification disabled]“. `service_process` spricht von „services“ statt von systemd-Units, weil der
  Windows-Agent seine Dienste im selben Block meldet. Status, `_details` und Metriken bleiben gleich; eine gespeicherte
  deutsche Meldung ersetzt die naechste Auswertung. Die Fehlertexte der API und den Rahmentext der Alert-Mail stellt
  R-0488 um. Wer externe Filter (etwa Mail-Regeln) auf den Meldungstext setzt, passt sie an. Doku: Monitoring fuer
  Entwickler und Administration (DE+EN).

- **Monitoring: Recovery-Mail, Fehler im Alert-Log und API-Fehlertexte englisch (R-0488):** Die
  Recovery-Benachrichtigung hat jetzt den Betreff `[AdminHelper Monitor] RECOVERY: <Check>` wie die Alarme
  `[AdminHelper Monitor] <STATUS>: <Check>`, ohne das angehaengte „ist wieder OK“, und endet auf „The check is OK
  again.“ statt „Der Check ist wieder in Ordnung.“. Betreff und Text gehen gleich in Mail, Webhook (`subject`,
  `text`), Glocke und persoenliche Benachrichtigungen. Ein Mail- oder Webhook-Filter auf „ist wieder OK“ greift nicht
  mehr; `RECOVERY:` im Betreff trifft die Entwarnung vorher wie nachher. Englisch sind auch die Fehler, die das
  Alert-Log zu einem gescheiterten Versand speichert und der Desktop dort zeigt, etwa „No recipients configured“,
  „Unknown channel: …“ oder „Webhook target is private/reserved (not allowed)“; bisher waren sie deutsch, auch in der
  englischen Oberflaeche. Gespeicherte Eintraege behalten ihren Text. Ebenso englisch sind die Fehlertexte der
  Monitoring-API, die der Desktop als „HTTP <Code>: …“ anzeigt, etwa „Check not found“, „Invalid API key“ oder
  „Invalid config for agent_resources: …“; die Status-Codes bleiben. Doku: Monitoring-Administration (DE+EN).

- **Monitoring: Check-Meldungen nennen hoechstens zehn Eintraege einer Liste und sind hoechstens 2000 Zeichen lang
  (R-0517):** Nennt die Meldung eines Checks eine Liste — VMs ohne oder mit altem Backup, Pools, Container, Platten,
  Dienste oder Mounts —, stehen dort hoechstens zehn Eintraege und hoechstens 1000 Zeichen davon, jeder Eintrag auf
  500 Zeichen gekuerzt, die uebrigen als „(+N more)“, etwa „Failed: a.service, …, j.service (+3 more)“. Bisher nannte
  die Meldung alle, bei einem defekten Agent mit 500 langen Namen bis zu mehreren Millionen Zeichen in Dashboard, Mail
  und Webhook. Zusaetzlich kuerzt der Dienst jede Meldung fuer Dashboard, Mail und Webhook auf hoechstens 2000 Zeichen
  samt „…“, etwa eine mit zwei vollen Listen oder dem langen Fehlertext „Unexpected error: …“ eines Checks; ein
  „(failure n/m)“ eines gedaempften Fehlers steht dahinter und bleibt sichtbar. Status und Metriken bleiben gleich,
  die Details (die Listen im Desktop) bleiben vollstaendig. Doku: Monitoring fuer Entwickler und Administration
  (DE+EN).

- **FRP: frps uebernimmt Konfigurations- und Zertifikatsaenderungen selbst (R-0411):** frps laeuft aus einem eigenen
  Image (`ghcr.io/admincave/adminhelper/frps`, Quelle `apps/frps/`, frps 0.69.1) unter einem Supervisor. Er prueft
  `frps.toml` und das TLS-Material vor jedem Start (Regeln und Gruende: Betrieb → frps-Supervisor) und startet frps aus
  einer geprueften Arbeitskopie unter dem eigenen Nutzer `frps` (UID 10002) ohne Capabilities. Eine geaenderte
  FRP-Server-Konfiguration oder ein erneuertes frps-Zertifikat uebernimmt frps nach wenigen Sekunden selbst und startet
  neu; ein Neustart von Hand ist dafuer nicht noetig. Alle Tunnel sind dabei kurz getrennt; Admins und Nutzer mit
  Tunnel-Zugriff bekommen eine Mitteilung in der Glocke, bei neuem Token mit dem Hinweis, dass Agent-Tunnel bis zu ~5
  Minuten brauchen. Eine Konfiguration, die die Pruefung nicht besteht, wird nicht uebernommen; den Grund zeigt die
  FRP-Seite, und solange frps mit der letzten gueltigen Kopie weiterlaeuft, bekommen Admins dazu eine Mitteilung in der
  Glocke. Ohne gueltige Kopie (etwa direkt nach dem Update) startet frps nicht, bis die Konfiguration die Pruefung
  besteht. Wird die FRP-Server-Konfiguration geloescht, stoppt frps. Neu auf der FRP-Seite
  ist der Block „Zustand des frps“ (Zustand, Grund, seit wann, letztes Ereignis; aktualisiert alle 30 s, solange der Tab
  sichtbar ist) ueber `GET /api/frp/supervisor-status` (nur Admins). Vor dem Speichern einer Aenderung, die frps neu
  startet, fragt die Maske nach; weicht der Bind Port vom veroeffentlichten `FRP_BIND_PORT` ab, warnt sie am Feld,
  Speichern bleibt moeglich. Compose: neue Volumes `frps-state` (Statusdatei; `server` und `scheduler` lesen sie
  read-only) und `frps-active` (Arbeitskopie, nur frps), beide nicht im Backup; `cap_drop: [ALL]` plus `DAC_OVERRIDE`,
  `SETUID`, `SETGID` und `KILL` fuer den Supervisor; `net.ipv4.ip_unprivileged_port_start: 0`, damit frps Port 443 ohne
  root bindet. `install.sh` und `update.sh` pinnen `FRPS_IMAGE` wie die uebrigen Images, CI und Release bauen und
  veroeffentlichen das Image mit. Doku: FRP-Tunnel, Installation und Betrieb (DE+EN), API-Referenz.
- **Server: Grenzen und Token-Feld der FRP-Server-Config (R-0411):** `POST`/`PUT /api/frp/server-config` nehmen
  `bind_port`, `vhost_https_port` und `dashboard_port` nur im Bereich 1–65535 und `max_ports_per_client` nur ab 0 an (0
  oder leer: Standard 16), sonst `422`; ein ausdrueckliches `"bind_port": null` im `PUT` ist ebenfalls `422`, fehlt das
  Feld, bleibt der Wert. **Vor dem Update pruefen:** die Ports und `max_ports_per_client` der FRP-Server-Config.
  Gespeicherte Werte ausserhalb dieser Grenzen bleiben in der Datenbank; der Generator ersetzt sie beim Schreiben der
  Konfigurationen (`bindPort`/`serverPort` 7000, vHost- und Dashboard-Port fallen weg, `max_ports_per_client` 16) und
  schreibt je Fall eine Warnung ins Log. Ein leeres oder `null`-`auth_token` im `PUT` laesst das gespeicherte Token
  unveraendert; ein neues braucht mindestens 16 Zeichen. Der Pflicht-Check `openapi-compat` nimmt genau diese engeren
  Grenzen ueber die Ausnahme-Datei `scripts/dev/oasdiff-err-ignore.txt` (oasdiff `--err-ignore`) hin; ohne die Datei
  bleibt er streng, jede andere Verengung bleibt ein Fehler. Der CI-Job `ops-scripts` und das Bootstrap der Test-VMs
  installieren dafuer oasdiff 1.32.0 mit gepinnter SHA-256. Doku: FRP-Tunnel und API-Referenz (DE+EN), CI/CD (DE+EN),
  `DEVELOPMENT.md`.
- **Server: `extra_config` und Textfelder der FRP-Server-Config nach den Regeln des frps-Supervisors (R-0411):**
  `POST`/`PUT /api/frp/server-config` nehmen in `extra_config` nur `transport.maxPoolCount`, `transport.tcpMux`,
  `transport.tcpMuxKeepaliveInterval`, `transport.heartbeatTimeout`, `transport.tcpKeepalive`, `userConnTimeout`,
  `log.level` und `log.maxDays` an, mit `true`, `false`, einer endlichen Zahl oder einem String ohne Anfuehrungszeichen,
  Backslash, geschweifte Klammern und Steuerzeichen, sonst `422`; `{` oder `}` in `subdomain_host`, `dashboard_user`,
  `dashboard_password` oder `auth_token` ist ebenfalls `422`. Die Tunnel-Configs (frpc) betrifft das nicht. Ein
  einzelnes Surrogat (U+D800 bis U+DFFF) ist `422` in den Textfeldern und `extra_config`-Werten der FRP-Server-Config,
  in `name`, `local_ip`, `secret_key`, `custom_domains`, `auto_connection_username` und `extra_config`-Werten der
  Tunnel und im Server-Namen. **Vor dem Update pruefen:** `extra_config` und diese vier Felder der FRP-Server-Config;
  das Auth Token hat mindestens 16 Zeichen; ein gesetzter Dashboard Port ist weder 443 noch der Bind Port noch
  `FRP_BIND_PORT`. Beim Start entfernt der Server `extra_config`-Eintraege ausserhalb dieser Regeln (etwa
  `proxyBindAddr` oder `log.to`) aus der gespeicherten Konfiguration und meldet die entfernten Schluessel den Admins in
  der Glocke. Ein Feld mit einem Wert, den frps nicht annimmt (unzulaessige Zeichen, ein Auth Token unter 16 Zeichen,
  ein Dashboard Port gleich 443, dem Bind Port oder `FRP_BIND_PORT`), aendert er nicht; er meldet den Admins in der
  Glocke, welche Felder neu zu setzen sind, je Feld mit der Regel (einmal, solange dieselben Felder betroffen sind),
  und bis dahin startet frps ohne gueltige Arbeitskopie nicht (Zustand `waiting`). Log und Mitteilungen nennen
  Schluessel und Felder, nie Werte.
  Doku: Betrieb und API-Referenz (DE+EN).
- **Web: Rueckfragen enden mit Escape und mit der Sitzung (R-0411):** Escape bricht eine angezeigte Rueckfrage ab und
  schliesst nur sie, nicht den Dialog darunter. Endet die Sitzung (Abmelden oder Ablauf), endet eine angezeigte
  Rueckfrage mit „Abbrechen“, damit die Aktion nicht nach einer neuen Anmeldung mit der neuen Sitzung laeuft.
- **Monitoring: neue Warnungen fuer Docker und ZFS nach dem Update (R-0419):** Ein Host mit gestopptem Docker-Daemon
  oder mit einem `zpool`, dessen `zpool list` scheitert oder haengt (etwa ein LXC-Container ohne ZFS-Modul), meldet
  `docker_health` bzw. `zfs_health` jetzt als `warning` mit Benachrichtigung, alte mit Exit ≠ 0 beendete Container
  ohne Restart-Policy erstmals als `critical`. Das ist gewollt. Ausweg je Check: `alert_on_unavailable: false` (neu in
  der Konfiguration von `docker_health` und `zfs_health`, Default `true`, nur echte Booleans; im Check-Editor die
  Checkbox „Ausfall melden“) laesst einen Ausfall auf `unknown` ohne Benachrichtigung stehen, `ignore_containers`
  blendet einzelne Container aus, auch solche, die geplant neu starten.
- **Agent: das Paket empfiehlt `smartmontools` (R-0419):** deb und rpm tragen `Recommends: smartmontools`, ohne das
  Paket vorauszusetzen: Ohne `smartctl` laeuft der Agent weiter, `smart_health` meldet dann „No SMART data: smartctl
  is not installed“. Eine Neuinstallation mit `apt-get install` oder `dnf install` zieht es mit, sofern Empfehlungen
  nicht abgeschaltet sind. Auf bestehenden Hosts kommt es mit einem Upgrade des Agents nicht sicher mit
  (`apt-get upgrade` und `dpkg -i` installieren neue Empfehlungen nicht nach): Dort bei Bedarf `smartmontools` von
  Hand installieren.
- **Server: FRP-Abgleich ohne FRP-Config ohne Fehler, ohne aktiven Tunnel ohne frps-Zugangsdaten (R-0398):**
  `GET /api/frp/provision/{id}/config-hash` antwortet ohne FRP-Config mit `200` und `{"hash": null}` statt mit `404`
  „Keine FRP-Config vorhanden“; fuer den Agent-Abgleich gibt es dann nichts zu tun, `GET …/config` bleibt `404`. Ein
  Host ohne aktiven Tunnel (eingeschaltet, STCP nur mit Secret) bekommt ueber `GET …/config` eine Config ohne Tunnel
  und ohne frps-Zugangsdaten, `config-hash` liefert deren Hash, und die Provisionierung liefert ihm denselben Text als
  FRP-Paket (`frp` ist nur ohne FRP-Config `null`). Ein Agent dieser Version stoppt und deaktiviert frpc darauf. Ein
  aelterer Agent startet frpc damit neu; frpc meldet sich dann nicht an und wird von systemd neu gestartet, bis der
  Agent aktualisiert ist. Bei der Provisionierung schreibt ein aelterer Agent damit auch die Sync-Config mit dem neuen
  API-Key; einen schon laufenden frpc startet er dabei nicht neu, der uebernimmt die Config erst bei seinem naechsten
  Neustart. Die `403` der Scope-Pruefung und die `404` fuer einen unbekannten Server bleiben. Die API-Referenz und die
  Server-Doku (DE+EN) nennen es.
- **Monitoring: Template-Sync behaelt Anpassungen und geloeschte Checks (R-0420):** Aendert man an einem vom Template
  erzeugten Check Name, Beschreibung, Typ, Konfiguration, Aktiviert, Intervall, Schweregrad oder Fehlversuche, merkt
  sich der Check das Feld als angepasst, und kein Sync ueberschreibt es mehr, weder nach einer Template-Aenderung
  (auch dem Update eines Standard-Templates) noch nach einer Umbenennung des Servers noch beim Wiederherstellen; die
  uebrigen Felder folgen weiter dem Template, ein Feld zurueck auf dem Template-Wert gilt nicht mehr als angepasst.
  Ein geaenderter Typ zaehlt auch als geaenderte Konfiguration. Ein geloeschter Template-Check entsteht beim naechsten
  Sync nicht neu, bis er wiederhergestellt oder die Zuweisung neu angelegt wird. Steht eine Definition nicht mehr im
  Template, loescht der Sync ihren Check weiterhin. Anpassungen von vor dem Update erkennt der erste Start einmal:
  Jedes Feld, das vom Template abweicht, gilt als angepasst, aufgeloest mit den Namen, mit denen der Check angelegt
  wurde (ein seither umbenannter Server zaehlt nicht als Anpassung); ein Check, der sich nicht vergleichen laesst,
  gilt ganz als angepasst. Das geschieht vor jedem Sync; scheitert es, unterbleibt der Sync, bis es gelingt.
  Restrisiko: Eine Template-Aenderung, die vor dem Update nie auf einen Check synchronisiert wurde, erscheint dort als
  angepasst. Alert-Regeln aus Templates setzt jeder Sync weiter auf die Template-Werte. Checks liefern dafuer additiv
  `templateDefId` und `overriddenFields`; neue Alembic-Revision `a7c9e1b3d5f7` (Spalte
  `monitor_checks.overridden_fields`, Tabelle `monitor_check_tombstones`; sie loescht beim Upgrade den Merker der
  Erkennung in `monitor_seed_state`).
- **Monitoring: unveraenderte Standard-Templates folgen neuen Versionen (R-0420):** Jedes Standard-Template traegt
  eine Version und den Hash der zuletzt ausgerollten Definitionen (`builtin_version`, `builtin_hash`). Liefert ein
  Release eine neuere Version, hebt der Monitoring-Dienst beim Start jedes Standard-Template mit unveraenderten
  Definitionen darauf und synchronisiert dessen Server; angepasste Check-Felder sowie Name und Beschreibung des
  Templates bleiben. Ein Template mit angepassten Definitionen bleibt, wie es ist, und bietet das Update an (siehe
  Added). Bisher wurde jedes Standard-Template genau einmal geseedet und nie aktualisiert. Ein bestehendes von vor den
  Versionen gilt als Version 1; weichen seine Definitionen von denen der Version 1 ab, gilt es als angepasst.
- **Monitoring: neuer Hostname oder Servername erreicht bestehende Zuweisungen (R-0420):** Der Tag-Sync gleicht jetzt
  fuer jede Zuweisung, auch fuer manuelle, Hostname und Servername mit dem Server-Inventar ab und synchronisiert bei
  einer Abweichung genau dieses Paar neu, sodass `{{hostname}}` und `{{server_name}}` einer Umbenennung folgen;
  angepasste Check-Felder bleiben, Alert-Regeln werden neu gesetzt. Bisher galten die Werte vom Anlegen der
  Zuweisung. `POST /templates/tag-sync` liefert zusaetzlich `refreshed`.
- **ca-issuer startet erst nach der Server-Migration (R-0288):** In `docker-compose.yml` wartet der `ca-issuer` per
  `depends_on` auf den healthy `server`, und healthy wird der Server erst nach `alembic upgrade head`. Vorher konnten
  `/enroll` und `/renew` bei einem Teil-Start auf ein Schema ohne ihre Tabellen treffen und mit 500 antworten; im
  normalen Start schloss nur das Warten des Gateways auf den Server dieses Fenster. Die Installationsanleitung (DE+EN)
  nennt die Reihenfolge.
- **Audit des Self-Mints nennt das langlebige Browser-Leaf (R-0204):** `POST /api/enrollment/token?browser=true`
  vermerkt im Audit-Log (`enrollment.token.minted`) wie `/token/for`, dass das Leaf langlebig und nur unter
  `MTLS_ENFORCE=true` widerrufbar ist, weiterhin mit `(self)`. Die API-Referenz (DE+EN) beschreibt den Endpunkt als
  Selbstbedienung fuer ein weiteres eigenes Geraet: unter `MTLS_ENFORCE=true` erreicht ihn nur ein Geraet mit
  gueltigem Client-Zertifikat, er ist keine Bootstrap-Tuer ohne Zertifikat.
- **Agent und Audit auf Go 1.27 (R-0352):** CI (`agent`, `agent-windows`), Release und der woechentliche Audit bauen
  mit Go 1.27 und `check-latest`, also mit dem neuesten 1.27.x (heute go1.27.2); Go 1.26 faellt mit dem Erscheinen
  von Go 1.28 aus dem Support. Die Test-Boxen (`scripts/vm/bootstrap_linux.sh`) installieren go1.27.2 statt 1.26.9.
  `govulncheck` bleibt auf v1.9.0, die `go`-Direktive in `apps/agent/go.mod` bleibt `1.25.0`.
- **Gezieltes Verify ohne Schemathesis (R-0380):** `verify.sh <komp> --strict -- <test>` laesst den Schritt
  `schemathesis` aus (`SKIP … (AH_ARGS)`, unter `--strict` kein Fehler wie bei `AH_ONLY`); er kostete jede
  Task-Verify gut fuenf Minuten, voll laeuft er in der PR-CI.
- **Schwere Suite als Sammellauf, PR-CI statt lokaler Wiederholung:** `Heavy: linux-full` laeuft nicht mehr je
  Vorhaben vor dem Merge, sondern als Sammellauf `/test all` ueber `main`, faellig nach drei solchen Vorhaben,
  sieben Tagen oder vor einem Release; rot sperrt weitere Merges mit Heavy bis auf Fix, Revert und SEC.
  `scenario` und `windows` bleiben vor dem Merge. Die lokale Komponenten-Suite vor dem PR und die
  Kombinationspruefung entfallen: die PR-CI testet `main` + PR, sobald der Branch `origin/main` enthaelt
  (`/feature-build` §4–§5, CLAUDE.md §2 und §5).
- **Entwicklungsablauf (Team v3, Dev-Werkzeuge):** eine Claude-Code-Session mit Sub-Agenten (`.claude/agents/`:
  `builder`, `reviewer`, `tester`, `security`) statt Chef, Worker und Loop; die Regeln stehen in `CLAUDE.md`.
  `AUTONOMOUS.md` und der Skill `feature-review` entfallen, das Ledger-Format steht in `tasks/README.md`.
  `task-close.sh` prueft das Urteil des `reviewer` als Datei, `review.sh` behaelt `sec`, `risk` und `pr-body`,
  `scripts/dev/worktree-setup.sh` und `worktree-teardown.sh` ersetzen `lane.sh`. Sub-Agenten haben eine Notbremse
  (`maxTurns`) statt einer Uhr; `harness-guard.sh` prueft nur noch Bash-Befehle.

- **Desktop: Zuruecksetzen widerruft das Geraet am Server (R-0224):** "Geraete-Identitaet zuruecksetzen" widerruft das
  Geraet zuerst am Server, ausgewiesen durch sein Zertifikat, und loescht es dann lokal. Widerruft der Server es
  nicht, sagt der Desktop das; registriert man das Geraet danach wieder fuer denselben Benutzer, loest das das alte
  Zertifikat ab. Neu-Registrieren nennt das vorige Zertifikat dieses Geraets, ein Browser-Export nie. Lehnt der Server
  das Zertifikat ab (`ERR_CERT_REVOKED`), zeigt der Login einen Hinweis und bietet das Zuruecksetzen an.
- **Neu-Provisionieren ersetzt den API-Key des Agents (R-0279):** Eine weitere Provisionierung desselben Servers loescht
  den API-Key der vorigen; es gilt nur noch der Key des Agents, der jetzt installiert wird. Globale und manuell angelegte
  Keys sowie die Keys anderer Server bleiben. Das Audit-Log nennt jeden ersetzten Key (`apikey.deleted`).
- **Client-Zertifikate werden pro Geraet erfasst und geprueft (R-0224):** Der ca-issuer haelt jedes ausgestellte
  Client-Zertifikat in einem Register fest (Fingerprint, Seriennummer, Laufzeit, Art) und ordnet es einer
  Geraete-Linie zu; ein Erneuern bleibt auf der Linie. Server und Erneuern pruefen jedes Zertifikat, mit dem sich ein
  Client ausweist: Es gilt, wenn seine Linie nicht gesperrt ist und es nicht unter den Widerruf seines Benutzers
  faellt. Sonst antwortet der Server mit 403 `ERR_CERT_REVOKED`, auch bei `MTLS_ENFORCE=false`. Erneuert wird nur ein
  Zertifikat, das vom Intermediate seines eigenen Scopes signiert ist. Zertifikate von vor dem Update werden beim
  ersten Kontakt uebernommen; das geht 90 Tage ab dem Update, danach gilt nur noch, was erfasst ist.
- **Ein Enrollment-Token gilt nur fuer eine Identitaet, die noch besteht (R-0306):** Ein Token, das bis zum Loeschen
  seines Benutzers oder Servers ausgestellt und noch nicht eingeloest wurde, stellt danach kein Zertifikat mehr aus.
  Wer eine Geraete-Linie anlegt (Enroll, Erneuern, die Uebernahme eines Zertifikats von vor dem Register) und wer eine
  Identitaet widerruft, laufen nacheinander.
- **Ein Agent-Zertifikat gilt nur fuer den eigenen Server (R-0283):** An den Routen eines Servers, dem Agent-Report
  und der frpc-Config, muss der CN eines Agent-Zertifikats die `server_id` des Pfads sein. Sonst antwortet der Server
  mit 403 `ERR_CERT_SERVER_MISMATCH`, auch bei `MTLS_ENFORCE=false`. Ein Admin mit seinem access-Zertifikat liest die
  frpc-Config wie bisher.
- **Ein Restore beginnt den Uebergang des Registers neu (R-0224):** `restore.sh` und `pg-restore.sh` setzen nach dem
  Restore der Server-DB den Installationszeitpunkt des Registers auf den Restore. Zertifikate, die seit dem Backup
  ausgestellt oder erneuert wurden und deshalb nicht im zurueckgespielten Register stehen, werden beim ersten Kontakt
  uebernommen, 90 Tage ab dem Restore.
- **Der Widerruf eines Benutzers ist ein Zeitpunkt (R-0224):** Wird ein Benutzer geloescht, gelten alle bis dahin
  ausgestellten Zertifikate dieses Usernames nicht mehr, am Server wie beim Erneuern. Legt ein Admin spaeter einen
  Benutzer mit demselben Namen an, bekommt der neue Benutzer neue Zertifikate; die alten bleiben gesperrt. Ein erneutes
  Loeschen setzt den Zeitpunkt neu. Das Loeschen eines Benutzers oder Servers sperrt auch seine offenen Geraete (Grund
  `admin`); sie stehen als widerrufen in der Geraeteliste, auch in der eines spaeter gleichnamig angelegten
  Benutzers.
- **Regeln des Teams in `CLAUDE.md` (Team-Plan Phase 1, R-0270):** §2 beschreibt das Betriebsmodell mit dem Team.
  Die Aufsicht heisst jetzt Chef und uebernimmt ihren Stand aus Dateien (AH-STATUS, Roadmap, Ledger). Das Team laeuft
  unter Kevins UID ohne Docker und ohne sudo; der Runner-Nutzer ist eingefroren. Deckel: 2 Bau-Slots (nur disjunkte
  Ledger), 1 VM-Lauf zugleich, hoechstens die Haelfte des Wochenlimits. Opus plant und baut; Sonnet prueft nur Tasks
  ausserhalb der Risikopfade, den ganzen Branch prueft Opus. Der Chef merged Produkt-PRs nach eigener Pruefung, wenn
  die CI im ersten Anlauf gruen ist; PRs an Harness und Gates, auch an `.github/workflows/`, merged Kevin; ein roter
  `main` wird per Revert des letzten Merges zurueckgenommen. In der Triage gilt als angenommen, was Kevin diktiert;
  kein eigener Fund wird ohne ihn `geplant`. Ein Dauerlauf laeuft nach Kevins Start innerhalb der Deckel weiter, aber
  erst nach der Sandbox (R-0241). §8 sagt jetzt richtig, dass die Dev-Box Docker hat. `skill_consistency_test` haelt
  die Sandbox-Regel, den Chef samt altem Namen, „Nie prueft Sonnet, was Sonnet baute“, die 2 Bau-Slots, den Merge
  nach eigener Pruefung, Kevins Merge der PRs an Harness und Gates und hoechstens 226 Zeilen fest.
- **Client-Zertifikat und angemeldeter Benutzer gehoeren zusammen (R-0223):** Unter mTLS gehoert das
  Client-Zertifikat dem angemeldeten Benutzer; Login, API und Zertifikats-Ausgabe pruefen das. Ist die Identitaet am
  Gateway verifiziert, muss ihr Scope `access` und ihr CN der Username sein, sonst antwortet der Server mit 403
  `ERR_CERT_USER_MISMATCH`. Das gilt fuer Login, Refresh und Bootstrap (dort fuer den neu anzulegenden Username), fuer
  die Anfragen, deren Benutzer aus dem JWT kommt, darunter die Zertifikats-Ausgabe, und fuer das Oeffnen des
  Benachrichtigungs-Streams. Logout und Zugaenge, bei denen der API-Key entscheidet, sind nicht gebunden; ein API-Key
  gehoert keinem Benutzer. Jeder Benutzer nutzt damit sein eigenes Zertifikat.
- **Monitoring: die DB-Session laeuft in UTC (R-0218):** Wie der Server seit R-0209 setzt jetzt auch die Engine des
  Monitorings jede Verbindung auf `TimeZone=UTC`, auch gegen ein `PGTZ` in der Umgebung. Der Stack faehrt Postgres mit
  `TZ=Europe/Berlin`; ohne das lief die Session des Monitorings dort in Ortszeit. Heute schreibt und vergleicht das
  Monitoring schon ueberall naive UTC, Werte und Ausgaben aendern sich also nicht; die Einstellung schuetzt kuenftigen
  Code.
- **Hooks: Cron-Wochentage zaehlen wie im Standard-Cron (R-0249):** Im Wochentag-Feld eines Schedule-Hooks war `0`
  Montag statt Sonntag, denn APScheduler 3.x zaehlt in `from_crontab` ab Montag. Damit lag jeder Wochentag in Ziffern
  einen Tag daneben: `0 9 * * 1-5` lief Dienstag bis Samstag, `7` wurde abgelehnt. Jetzt gilt Standard-Cron: `0` und
  `7` sind Sonntag, `1` ist Montag, `1-5` ist Montag bis Freitag. Namen wie `mon-fri` galten schon richtig.
  Tag-im-Monat und Wochentag bleiben, anders als im Standard-Cron, mit UND verknuepft: `0 9 1-7 * mon` laeuft am
  ersten Montag des Monats (R-0274).
  **Bei bestehenden Hooks meinen die Ziffern im Wochentag ab diesem Stand den Tag davor**: `1` war Dienstag und ist
  jetzt Montag, der Hook laeuft also an dem Tag, den der Cron-Ausdruck meint. Das gilt auch hinter einem Schritt:
  `*/2` laeuft Sonntag, Dienstag, Donnerstag, Samstag statt Montag, Mittwoch, Freitag, Sonntag. Die gespeicherten
  Ausdruecke bleiben, wie sie sind; den neuen Zeitpunkt (`next_run`) traegt der Scheduler beim naechsten Abgleich
  ein. Ein Hook mit `7`, angelegt vor R-0235, lief bisher nie und laeuft jetzt sonntags; ebenso ein Namensbereich ab
  `sun` (`sun-mon` bis `sun-sat`, jede Schreibweise), den APScheduler ablehnte und der jetzt laeuft. Namen gelten wie ihre
  Zahlen, auch in Bereichen und mit Schritt, wie in Vixie-Cron: `mon-fri/2` laeuft Montag, Mittwoch, Freitag (bisher
  Montag bis Freitag, der Schritt fiel weg), `sun-thu` Sonntag bis Donnerstag (bisher abgelehnt); `sat-sun` laeuft
  weiter Samstag und Sonntag.
  **Ein Schritt auf einem einzelnen Wert (`1/2`, `mon/2`) und kaputte Namen (`mon;wed`, `mon-fri-sat`) werden jetzt
  abgelehnt**; APScheduler nahm sie bisher an, Standard-Cron lehnt sie ab. Solche Hooks laufen erst nach einer
  Korrektur wieder, mit einer Warnung im Scheduler-Log. Betroffene Hooks findet diese Abfrage auf der
  Server-Datenbank:
  `SELECT id, name, enabled, schedule_interval FROM hooks WHERE hook_type = 'schedule' AND
  (regexp_split_to_array(btrim(schedule_interval), '\s+'))[5] ~* '[0-9]|sun-';` Sie listet auch Ausdruecke wie `*/1`
  oder `sun-sun`, die sich nicht aendern; kaputte Namen ohne Ziffer (`mon;wed`) findet sie nicht, die meldet der
  Scheduler im Log.
- **Proxmox-Token aus einer 0600-Datei (R-0229):** `scripts/vm/vm.py` und `scripts/vm/lib.sh` lesen den
  Proxmox-Zugang auch aus `~/.config/adminhelper/pve.env` (Zeilen `KEY=VALUE` fuer `AH_PVE_*`/`AH_VM_*`,
  gelesen, nie gesourct). Vorrang: Umgebung > `pve.env` > `env`-Block von `.claude/settings.local.json`,
  der als Rueckfall bleibt. Eine `pve.env`, die kein regulaeres 0600-File des eigenen Benutzers in einem
  fuer Gruppe und Andere nicht schreibbaren Verzeichnis ist, bricht mit Exit 2 und dem `chmod` ab. Das
  Token gehoert nach `pve.env`, damit es nicht mehr in der Umgebung jeder Session steht; den einmaligen
  Umzug beschreibt `DEVELOPMENT.md`, „VMs mit vm.py“.
- **Doku-Smoke prueft auch die Namen in Grossbuchstaben als Gate (R-0044):** `scripts/dev/doc-smoke.py --env`
  zaehlt einen Namen, den die Doku als `<code>` nennt, als bekannt, wenn ihn ausser den drei `config.py` und
  `.env.example` irgendeine getrackte Datei ausserhalb von `docs/`, `CHANGELOG.md` und `tasks/` traegt — Agent-
  Einstellungen, CI-Secrets, Zustaende und HTTP-Methoden sind also kein Fund mehr (vorher 138 Funde ueber 48
  Namen). Der einzige echte Fund, `FRP_DOMAIN` in `docs/en/admin/frp-tunnel.html`, ist korrigiert: gemeint ist der
  Subdomain-Host der FRP-Server-Konfiguration. Der CI-Job `ops-scripts` faehrt jetzt
  `doc-smoke.py --paths --env --strict`.

- **Der Public repo guard prueft auch mit der Logik der Basis (R-0174):** Der CI-Job
  „Public repo guard (review.sh sec)" faehrt `review.sh sec --range` zuerst mit dem `review.sh` der
  Basis (ein Worktree von `origin/<base>`, beim Push der Stand vor ihm), dann mit dem des geaenderten
  Stands; beide muessen gruen sein. Ein Pull Request, der `sec` aendert, wird so mit der Logik
  geprueft, die vor ihm galt; eine Basis ohne `sec --range` macht den Job rot. Einen Fehlalarm der
  Basis-Logik nimmt ein Admin-Merge. Anleitung: `docs/developer/cicd.html`, `DEVELOPMENT.md`.
- **CI-Laeufe auf Pushes nach `main` laufen zu Ende (R-0174):** Die `concurrency` von `ci.yml` gibt
  jedem Push eine eigene Gruppe je Commit und bricht nur noch Pull-Request-Laeufe ab; ein spaeterer
  Push bricht den Lauf davor weder ab noch verdraengt er ihn, solange er wartet. Nur dieser Lauf liest
  die Commits eines Pushs (`before..sha`). Anleitung: `docs/developer/cicd.html`.
- **`review.sh sec --range` sagt, wenn die Spanne leer ist (R-0174):** Ohne einen Commit in der
  Spanne meldet `sec` jetzt `sec: empty span (<range>) — nothing read` statt „sec: clean" (Exit
  weiter 0, ein Push ohne neue Commits ist keine Verweigerung). Der CI-Job „Public repo guard" macht
  daraus einen Hinweis, etwa bei einem `workflow_dispatch` auf `main`.
- **`task-close.sh` prueft billig zuerst (Stufe 6b, R-0150):** `diff-scan`, `scope`,
  `docs-pairs` und `sec` laufen vor der Suite, `contracts` danach; ein einseitiger Doku-Abschluss
  kostet keinen Suite-Lauf mehr. Aendert sich der Index waehrend des Laufs, bricht der Abschluss
  mit Exit 2 ab. `pr-body` prueft Verdict-Dateien ueber `check-verdict` (schemawidrig heisst
  „ungueltig").
- **Red Team root-eigen, in fester Umgebung (R-0152):** `scripts/dev/runner-setup.sh` installiert
  `runner-redteam.sh` mit `runner-env.sh`, `runner-settings.json` und `runner-claude.version` nach
  `/usr/local/lib/adminhelper-dev/` (root) und haelt die sha256 der Runner-CLI in
  `/var/lib/adminhelper-dev/runner-claude.sha256` fest; `--remove` nimmt beides mit. Das Red Team
  laeuft von dort (`sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh`),
  startet sich unter `env -i` mit festem `PATH` neu, sourct keine Datei des Runners
  (`AH_RUNNER_ENV_NO_DEVENV=1` in `runner-env.sh`), nimmt das Soll des Pin-Checks aus seinem eigenen
  Verzeichnis und meldet `FAIL`, wenn es von woanders laeuft, wenn `runner-env.sh` es veraendert
  oder wenn die CLI nicht die festgehaltene ist. Nach einem CLI-Wechsel braucht es deshalb erneut
  `sudo bash scripts/dev/runner-setup.sh`. Anleitung: `DEVELOPMENT.md` „Runner-User".

- **Python-Sperre ueber Nutzergrenzen, Runner-Setup klont nur neu (R-0080, R-0077):**
  `scripts/tests/run.sh` nimmt fuer `server-pytest` und `schemathesis` die geteilte Sperre
  `/var/lib/adminhelper-dev/py.lock`, sobald ihr Verzeichnis existiert (`AH_PY_LOCK_FILE` geht
  vor, der Pfad ist ueber `AH_PY_LOCK_SHARED` aenderbar); ohne es bleibt es bei
  `~/.cache/adminhelper-py.lock` je Nutzer. So warten Kevins Laeufe und die des Runners
  aufeinander. Eine nur lesbare Sperrdatei sperrt weiter, eine fehlende oder nicht oeffenbare ist
  ein SKIP mit Grund (unter `--strict` rot), und die Halter-Zeile erscheint nur mit druckbaren
  Zeichen. `scripts/dev/runner-setup.sh` legt die Datei
  an (`--remove` nimmt sie mit) und klont nur noch in einen Pfad, den es nicht gibt: ein
  vorhandenes Verzeichnis ohne `.git` bricht mit einem Satz ab, der Klon entsteht in einem
  Temp-Verzeichnis in `/srv` und wird danach umbenannt. Ein bestehender Runner bekommt die Sperre mit einem erneuten
  `sudo bash scripts/dev/runner-setup.sh`. Das Red Team prueft die Sperre mit
  (`runner-redteam.sh --py-lock <pfad>`: vorhanden, root gehoerend, Verzeichnis fuer den Runner
  nicht schreibbar, nehmbar) und meldet `FAIL`, solange das Setup nicht erneut lief. Anleitung:
  `DEVELOPMENT.md` „Runner-User".

- **diff-scan: weitere Skip-Muster und Rueckgaben mit Wert (R-0132):** `review.sh diff-scan`
  meldet jetzt auch `fit(`, `fdescribe(`, `.runIf(`, `.fails(`, `test.fail(`, `.fixme(` (also <!-- review: ok nennt die Muster -->
  `test.describe.fixme(`), `self.skipTest(` und `pytest.importorskip(` in einer hinzugefuegten Zeile <!-- review: ok nennt die Muster -->
  sowie `return None`, `return undefined;` und `return Ok(());` in einem Test — bisher nur ein
  nacktes `return`, und in einer Datei mit CRLF-Zeilen nicht einmal das. `assert.fail(`,
  `sys.exit(` und `profit(` bleiben frei, ebenso ein `return` in einer im Test verschachtelten
  Funktion (Stub, Callback) und eines, nach dem kein Code des Tests mehr folgt; die Meldung heisst
  `early return in a test`.

- **diff-scan: entfernte Assertions zaehlen nur, wo Tests stehen (R-0130):** Eine geloeschte Zeile
  mit `assert`, `assert_…!`, `expect(` oder Go-`t.Fatal…` ist nur noch ein Fund in einer
  Testdatei (`tests/`, `e2e/`, `test_*.py`, `*_test.{py,go,sh}`, `*.test.*`, `*.spec.*`) oder in
  der Spanne eines Tests (inline `#[test]` unter `src/`); eine Import-Zeile nie. Bisher meldete
  diff-scan auch ein entferntes `.expect("…")` im Rust-Produktivcode, einen entfernten Import
  `use pretty_assertions::assert_eq;` und `review.sh` selbst, ohne Ausweg (eine geloeschte Zeile
  kann kein `review: ok` tragen).

- **Waechter: wer ein Verzeichnis mit Harness-Pfaden wegnimmt, nimmt sie mit (R-0127):**
  `scripts/dev/hooks/harness-guard.sh` verweigert im autonomen Lauf auch `rm -rf .claude`,
  `rm -rf scripts/dev/hooks`, `chmod -R -x scripts/dev/hooks`, `mv scripts/dev /tmp/x`, einen
  Glob, der Harness-Pfade im Baum trifft (`rm -rf scripts/dev/*`; `rm -f *.log` bleibt frei), die
  Repo-Wurzel (`rm -rf ./*`) und ein
  loeschendes `find` von dort aus — bisher zaehlte nur der Harness-Pfad selbst. Die Regel gilt
  nur fuer wegnehmende Kommandos (`rm`, `rmdir`, `shred`, `unlink`, `chmod`/`chown`/`chgrp`,
  `mv`-Quelle, `find … -delete`); interaktiv bleibt es eine Warnung. Dazu erkennt der Waechter
  `[^x]`, Klammer-Listen (`/{tmp,x}/…`) und `cd` in einen Glob mit woertlichem Operand
  (R-0125), und ein Kommentar verdeckt keine Folgezeilen mehr (`# … <<X`, ein Apostroph im
  Kommentar; R-0139). Anleitung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".

- **Schema-Fuzzing im PR deterministisch (R-0063):** Der Schritt `schemathesis` (lokal `run.sh` und der
  CI-Job „Schema fuzzing") faehrt mit `AH_SCHEMATHESIS_EXAMPLES=0` nur noch die explizite Phase
  (Schema-Beispiele und Coverage-Faelle): fuer denselben Baum dieselben Faelle, ein roter Lauf ist
  lokal nachstellbar. Der Wochenlauf behaelt alle Phasen mit 100 Beispielen. `hypothesis==6.168.3`
  und `schemathesis==4.29.0` sind exakt gepinnt. `scripts/tests/schemathesis_determinism.sh` prueft,
  ob zwei Laeufe je Test dieselben Faelle schicken. Die Server-Suite ersetzt den Proxy-Client zum
  Monitoring durch einen Stub; die fuenf Ausschluesse der Proxy-Routen sind entfallen. Doku:
  `DEVELOPMENT.md` „Generatoren", `docs/developer/cicd.html`.
- **Monitoring: Obergrenzen fuer ganzzahlige Eingaben (R-0063):** `cooldown_minutes` (Alert-Regeln und
  Vorlagen) und `consecutive_fails` (Checks und Vorlagen) enden bei der INTEGER-Grenze `2147483647`;
  `duration_minutes` (1–1440) und `weekdays` (0–6) der Wartungsfenster tragen ihre Grenzen jetzt auch
  im Schema, bisher galten sie nur im Validator (ein `once`-Fenster, das `duration_minutes` bisher
  ignorierte, darf damit keinen Wert ausserhalb 1–1440 mehr senden). Groessere Werte beantwortet der
  Dienst mit `422`, statt sie an die Datenbank zu geben. Je Dienst prueft ein Test, dass
  jeder Integer-Eingang des veroeffentlichten Schemas ein `maximum` hat.
- **Import-422 in der deklarierten Form (Server):** `POST /api/connections/import` meldet abgelehnte
  Eintraege jetzt wie jede andere 422 der API: `detail` ist eine Liste mit einem Eintrag je Fehler,
  `loc` = `["body", "connections", <index>, <feld>]`, in Import-Reihenfolge. Bisher stand dort
  `detail.message` und `detail.rejected[]` mit `index`, `name` und `errors`; Skripte, die das lesen,
  muessen auf `detail[]` umstellen. Alles oder nichts bleibt. Auch ein Eintrag mit snake_case-Feld
  (etwa `server_id`) wird so gemeldet. Der Schemathesis-Ausschluss fuer die Route faellt. Doku:
  `docs/developer/api-reference.html`.
- **Verbindungen nur in camelCase (Server):** `POST` und `PUT /api/connections` lehnen die
  snake_case-Schreibweisen `server_id`, `key_path`, `trust_cert` und `last_used` mit `422` ab (je
  Feld ein Eintrag in `detail`, Hinweis auf den camelCase-Namen). Jede dieser Spalten wird damit nur
  ueber ihren API-Namen geschrieben und durchlaeuft dessen Pruefungen. Alle Clients im Repo senden
  camelCase; andere Zusatzfelder bleiben erlaubt.
- **Verify-Zeile, wie sie dasteht (R-0104):** `scripts/dev/verify.sh` nimmt mehrere Komponenten
  und faehrt sie als einen Lauf `run.sh quick --only <a> <b>` (Argumente nach `--` nur fuer eine
  Komponente, `all` nur allein). `scripts/dev/task-close.sh` liest die Komponenten aus einer
  `Verify:`-Zeile in der Form `verify.sh <a> [<b> …] --strict` oder `run.sh <layer> --strict
  --only <a> [<b> …]` und faehrt genau diese — bisher lief fuer `--only web desktop-e2e` nur
  `web`. Fehlt die `Komponente:` der Task in der Liste, ist das Exit 2. Die `Evidenz:`-Zeile nennt
  die gelaufenen Komponenten (`run.sh[quick] web desktop-e2e: …`).

- **diff-scan erkennt mehr stummgeschaltete Tests (R-0082):** `scripts/dev/review.sh diff-scan`
  wertet jetzt auch geloeschte Rust-Makros `assert_…!` und in Go-Tests `t.Fatal…`/`t.Error…`
  als entfernte Assertion (ausserhalb einer `*_test.go` bleibt `err.Error()` frei), kennt die
  Skip-, xfail-, todo- und only-Muster von vitest/jest, Playwright, pytest, Rust (auch
  `#[ignore = "…"]`) und Go (`t.SkipNow()`), und meldet ein hinzugefuegtes nacktes `return` <!-- review: ok nennt die Muster -->
  innerhalb eines Tests (Python, Go, Rust, TS/JS). Der Ausweg bleibt `review: ok <grund>` auf
  der Zeile. Anleitung: `DEVELOPMENT.md` „Task schliessen".

- **Commit-Hooks auch bei merge, cherry-pick, revert, rebase und git am (R-0110):** Neben
  `scripts/dev/hooks/pre-commit` fahren jetzt `prepare-commit-msg` (cherry-pick, revert, jeder
  Commit eines rebase mit dem Standard-Backend, Merge-Commit), `pre-merge-commit` (vor einem
  Merge-Commit) und `pre-applypatch` (`git am`, `git rebase --apply`)
  `review.sh sec --staged` — bisher kam eine private Datei aus einem anderen Branch ueber diese
  Wege ungeprueft in den Verlauf. Dass der Sequencer `prepare-commit-msg` ruft, ist nicht
  dokumentiert, aber mit git 2.47.3 gemessen und im Test festgehalten. `harness.sh status`
  prueft alle vier Hooks und nennt einen fehlenden; der Waechter verweigert `git am -n` wie
  `git commit -n`; `chmod`, `chown` und `chgrp` auf einen
  Harness-Pfad zaehlen fuer den Waechter als Schreiben. Wirksam je Worktree mit dem Branch,
  der die Hooks traegt. Anleitung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".

- **Temp-Waechter erkennt mehr Formen (R-0109):** `scripts/dev/hooks/harness-guard.sh`
  verweigert jetzt auch einen Glob **ueber** einer Temp-Wurzel in jeder Tiefe
  (`/t*/claude-1000/*`, `cd /t* && rm -rf claude-1000/*`) — bisher zaehlte nur ein Treffer auf
  der Wurzel oder direkt darin, so dass ein solcher Glob die Verzeichnisse aller Sessions
  erreichte. Dazu erkennt der Parser einen Operanden nach `--`, `|&` als Pipe, `);` als zwei
  Operatoren (`for d in $(ls -d /tmp/tmp.*); do rm …`), `xargs sh -c 'rm …'` wie `xargs rm`
  und `grep -l`/`-L` als Lister. Frei bleiben die Aufraeumer im eigenen Verzeichnis; die
  verbleibenden Grenzen (Prozess-Substitution, `mapfile`, Laufzeit-Pfade ohne Glob,
  `cat … | xargs rm`) stehen in `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".
- **Audit: Logout nur, wenn eine Sitzung endet (Server, R-0105):** `POST /api/auth/logout` schreibt
  `auth.logout` nur noch, wenn der Aufruf einen Token gesperrt hat (Bearer oder Refresh-Token aus Body
  oder Cookie). Ein Logout ohne Token, mit ungueltigem oder abgelaufenem Token oder mit denselben
  Tokens ein zweites Mal hinterlaesst keinen Eintrag; Antwort (`200`) und Cookie-Loeschung bleiben
  gleich. Ein Logout nur mit Cookie traegt jetzt den Benutzernamen. Doku:
  `docs/developer/api-reference.html`, `docs/admin/betrieb.html`.
- **FRP: leere STCP-Secrets werden gefuellt (Server):** Eine Datenmigration gibt jedem
  stcp-Tunnel, dessen Secret leer ist, ein eigenes zufaelliges Secret; der Generator laesst
  einen stcp-Tunnel ohne Secret aus der frpc- und Visitor-Konfiguration weg. Der Agent holt die
  neue Konfiguration von selbst (Provision-Hash); ein laufender Desktop-Visitor eines solchen
  Tunnels braucht einen Tunnel-Neustart.
- **FRP: Tunnel-Antworten ohne Secret (Server):** Die JSON-Antworten von `/api/frp/tunnels`,
  `/api/frp/status`, `/api/frp/server-config/{id}` und `/api/servers` liefern `secretKey` als
  `null`; das Feld bleibt, das Schema aendert sich nicht. Das Secret steht nur noch in den
  erzeugten TOML-Dateien und im Provisioning. Ein `PUT /api/frp/tunnels/{id}` mit `secret_key`
  `null` oder `""` laesst das gespeicherte Secret unveraendert; wird ein Tunnel per `PUT` zu STCP
  und hat kein Secret, erzeugt der Server eins. Doku: `docs/developer/api-reference.html`.
- **Ein ruff ueberall (R-0074):** `apps/server/requirements-dev.txt` pinnt `ruff==0.15.20`
  statt des Bodens `ruff>=0.15`, und `scripts/dev/toolchain-lockstep.sh` verlangt Gleichheit
  mit `ci.yml` und `scripts/vm/bootstrap_linux.sh` statt nur „nicht darueber". Mit dem Boden
  blieb ein vorhandenes ruff 0.16.x im `AH_VENV` liegen und meldete ueber die vier Lint-Pfade
  841 Treffer, die CI mit 0.15.20 nie sah. Der Schritt `server-pytest` zieht das `AH_VENV`
  beim naechsten Lauf auf 0.15.20 zurueck. Dazu verlangt `ruff.toml` per
  `required-version = "==0.15.20"` genau diese Version, und der Lockstep prueft auch diese
  Stelle: ein anderes ruff im `PATH` bricht mit Exit 2 ab, statt still andere Regeln
  anzuwenden (der Format-Hook `scripts/dev/format-file.sh` formatiert dann still nicht).
  Auch das Tool-Venv des Runners (`VENV_PKGS` in `scripts/dev/runner-setup.sh`, das erste
  ruff in seinem `PATH`) installiert `ruff==0.15.20`, als fuenfte Stelle im Lockstep; auf
  einem bestehenden Runner wirkt das nach erneutem `sudo bash scripts/dev/runner-setup.sh`.

- **API-Schema: `X-API-Key` und `X-Internal-Key` als Security-Schemes (Server):** Das
  OpenAPI-Schema deklariert neben `HTTPBearer` jetzt `ApiKey` (Header `X-API-Key`, an allen
  Routen, die API-Key oder JWT annehmen) und `InternalKey` (Header `X-Internal-Key`, der
  Dienst-zu-Dienst-Ingress); die Swagger UI bietet beide unter „Authorize" an. Dafuer entfaellt
  der optionale Header-Parameter `x-internal-key` der zwei Internal-Routen, deren Verhalten
  gleich bleibt (Anfragen mit zwei Anmeldungen: siehe naechsten Punkt). Der Schemathesis-Check
  `ignored_auth` laeuft damit in allen vier Auth-Kontexten statt nur mit JWT. Doku:
  `docs/developer/api-reference.html`.
- **Verhaltensaenderung: jede mitgesendete Anmeldung muss gelten (Server):** An den Routen, die
  API-Key oder JWT annehmen (`/api/connections`, `/api/frp/provision`), prueft der Server jetzt
  alle mitgesendeten Anmeldungen, bevor er entscheidet. Ein gueltiger `X-API-Key` neben einem
  ungueltigen oder abgelaufenen Bearer-Token — oder ein gueltiger Bearer neben einem
  unbekannten Key, auch als `?api_key=` — ergibt `401` statt `200`; ebenso ein
  `X-API-Key` neben einem ungueltigen `?api_key=` (bisher wurde die Query dann ignoriert). Nur
  `Authorization: Basic` (von einem Proxy oder aus `user:pass@` einer Sync-URL) wird ignoriert;
  jeder andere `Authorization`-Header muss ein gueltiger Bearer sein — ein fremdes Schema, ein
  leerer oder unlesbarer Wert ergibt `401`. Sind beide
  gueltig, entscheidet wie bisher der Key; mit nur einer Anmeldung bleibt alles wie es war.
  Kein Client sendet zwei (Web und Desktop den Bearer, der Desktop-Sync nur `?api_key=`,
  der Agent nur `X-API-Key`, das Monitoring nur `X-Internal-Key`). Doku:
  `docs/developer/api-reference.html`.
- **API-Schema: typisierte Antworten fuer users und frp (Server):** `GET`/`POST /api/users` und
  `PUT /api/users/{id}` deklarieren `UserResponse`, die FRP-Server-Config-Routen
  `FrpServerConfigOut` (Detail: `FrpServerConfigDetail` mit den Tunneln als `FrpTunnelOut`) und
  `GET /api/frp/status` `FrpStatus` — statt eines leeren Schemas im OpenAPI. Die Antwort-Bytes
  bleiben gleich (je Route ein Differential-Test gegen den bisherigen Builder); Zeitstempel
  bleiben Strings aus `isoformat()`, das `tunnel`-Objekt im FRP-Status bleibt offen. Die Doku
  nannte fuer die Config-Detail-Route ein `?include_tunnels=true`, das es nicht gibt: die Tunnel
  kommen immer mit. Doku: `docs/developer/api-reference.html`.
- **Test-Ausgaben und Pflicht-Tests gegen den Stack (Harness Stufe 5c, Entwickler-Werkzeuge):**
  Die pytest-Schritte von `scripts/tests/run.sh` schreiben JUnit-XML nach
  `.ah-out/junit/<schritt-id>.xml` (Schemathesis eine Datei je Dienst), Playwright mit gesetztem
  `AH_OUT_DIR` nach `junit/web-playwright.xml`, die Desktop-E2E ueber `@wdio/junit-reporter` eine
  Datei je `wdio run`; jeder Lauf verwirft die XMLs des letzten, `heavy.sh` kopiert `junit/` in
  das Laufverzeichnis und nennt im Report ihre Zahl. Das Test-Overlay `docker-compose.test.yml`
  veroeffentlicht Postgres und Redis nur auf `127.0.0.1` (`ITEST_PG_PORT`, `ITEST_REDIS_PORT`, pro
  Lauf gestreut), `lib_e2e_stack.sh` exportiert `ITEST_DATABASE_URL` und `ITEST_REDIS_URL`. Zwei
  neue Pflicht-Schritte im `integration`-Layer: `stack-pytest` (`scripts/tests/stack_pytest.sh`)
  faehrt den Migrations-Smoke des Monitorings, `test_stream_redis` und den TOCTOU-Test des
  ca-issuers gegen diese Dienste, ein Skip ist dort ein Fehler; `web-live`
  (`scripts/tests/web_live.sh`) faehrt das Playwright-Projekt `live` ohne Mocks (Login als
  Seed-Admin, jede Admin-Seite, Benutzer anlegen und loeschen). `test_stream_redis` liest die
  Redis-URL aus `AH_TEST_REDIS_URL`. Anleitung: `DEVELOPMENT.md` („Automatisierte
  Integrations-/E2E-Tests", „Wochenlauf") und `docs/developer/cicd.html`.
- **Planen und Beweis (Harness Stufe 5b, Entwickler-Werkzeuge):** Ledger haben die Status-Folge
  `geplant` -> `freigegeben` -> `aktiv` -> `bereit` -> `erledigt` und das Kopf-Feld `Heavy:`
  (`none | linux-full | scenario <flags> | windows`) statt `Fast-Suite:`/`Warm-Profil:`;
  `ledger.sh lint` prueft `Heavy:` und die Zeilen der Beweis-Konvention A-D (`Orakel:`,
  `Dedup-Key:`, `HEAD:`). `/feature-plan` committet den Plan am Gate als ersten Commit auf
  `feature/<slug>`, kennt `--kurz R-nnnn` (Kurz-Ledger aus einer belegten Roadmap-Zeile, mit
  Pflichtzeile `Semantik:`, ohne SEC) und `--bundle <komponente>` (REF-Zeilen einer Komponente)
  und fuehrt die Roadmap-Schritte am Gate aus; `/feature-build` folgt der Status-Folge, liest
  `Heavy:` und zieht die Roadmap mit. `roadmap.py status` bekommt `--ledger` und `--pr`, die
  Spalten, die `next` und `sync` lesen. Neu ist `scripts/tests/skill_consistency_test.sh`, der
  die Skill-Texte gegeneinander prueft. Anleitung: `tasks/README.md` und
  `docs/developer/cicd.html` („Beweis-Konvention").
- **Die Roadmap als Skript (Harness Stufe 5a, Entwickler-Werkzeuge):** `scripts/dev/roadmap.py`
  (Python-Stdlib) liest, lintet und schreibt die private Roadmap `tasks/private/ROADMAP.md`
  mit `lint`, `show`, `next`, `add`, `status`, `approve`, `sync` und `stats`. Jedes Schreiben
  laeuft unter `flock`, mit `.bak`, Zeilenzahl-Pruefung, einer 5-Sekunden-Regel gegen einen
  offenen Editor und einem lokalen Commit im privaten Repo. Der Abschnitt einer Zeile folgt
  ihrem Status, der WIP-Kopf wird neu gerechnet, `neu` ist bei 20 Zeilen gedeckelt, und ein
  Dedup-Key haelt Dubletten zurueck. `heavy.sh` legt REG- und REL-Zeilen nur noch ueber
  `roadmap.py add` an. Der Status-Hook zeigt alle Punkte von „Als Naechstes" und die
  WIP-Deckel, bei einem erreichten mit `Warnung:`. Neu sind der Skill `/roadmap` (Ueberblick
  und `triage`) und der `run.sh`-Schritt `scripts/dev pytest` (Id `dev-pytest`, Pflicht).
  Anleitung: `DEVELOPMENT.md`, „Die Roadmap als Skript: `roadmap.py`".
- **VM-Rollen bekommen mehr vCPUs:** `scripts/vm/profiles.json` gibt der Desktop-Rolle und dem Bake
  6 statt 4 bzw. 2 Kerne und der Server-Rolle 4 statt 2 — der Host lief waehrend eines Capstones
  bei 10 % CPU, waehrend Tauri-, npm- und Go-Builds in den VMs auf 2 Kernen warteten (Bake
  `linux-full` 56 min). Agent-, Tunnel-, Visitor-, Moncheck-, RPM- und Probe-Rolle bleiben bei 2.

- **Die schweren Suites laufen ohne externes Binary (Harness Stufe 2b):** Alle Wrapper rufen
  jetzt `scripts/vm/vm.py` statt des externen `crabbox` auf, bei unveraenderter Aufruf-Semantik.
  Neu: `scripts/vm/warm.sh`, `iter.sh`, `reap.sh`, `bake.sh` und `scripts/vm/bootstrap_linux.sh`;
  `scripts/tests/multibox.sh` und die sieben Rollen-Skripte heissen `box_*.sh`. Die
  Ausgabe-Artefakte liegen unter `.ah-out/`, der Warm-Zustand unter `.vm/warm.env`, die
  Lane-Kennung explizit in `.vm/lane`. Eine Multi-Host-Szenerie traegt ein gemeinsames
  `sc-`-Tag: der Teardown ist ein `vm.py destroy --scenario` und erwischt auch die Box, deren
  Klon zwar kam, aber nie hochfuhr. Vor dem ersten Klon prueft `vm.py doctor --roles` die
  Kapazitaet fuer die ganze Szenerie — was nicht passt, kostet nichts statt vier gebooteter
  Boxen. `heavy.sh` trennt jetzt Ganz-Lauf-Abbrueche von Rollen-Abbruechen: ein einzelner
  verlorener Klon im Capstone wird der Rolle zugeordnet, statt den Lauf als UNVERIFIED zu
  verwerfen. Die Lease-Wiederholung entfaellt mit dem Rennen, das sie umging.
  Anleitung: `/vm` (die VMs) und `/test` (die Suiten), Details in `DEVELOPMENT.md`.

- **Bau- und Review-Tempo (Harness):** Der Frischer-Kontext-Reviewer laeuft jetzt auf Sonnet
  statt Opus (Opus nur bei einem Risikopfad im Diff: PKI/mTLS, Auth, SSRF, Migrationen,
  Release-Workflows), hat ein Zeitbudget von zehn Minuten und faehrt die Suiten nicht mehr
  selbst nach. Ein Kurz-Ledger mit hoechstens drei Tasks bekommt `Review: am Ende` — ein
  Review ueber den ganzen Branch-Diff statt einem je Task, ohne den abschliessenden
  `/code-review`. Und pro Task laeuft nur noch das gezielte `Verify:`, die volle
  Komponenten-Suite einmal vor dem Commit — nie zwei Testlaeufe gleichzeitig, weil die
  `server`-Suite sich eine Postgres-Test-DB teilt (`DEVELOPMENT.md`, „Python-Tests lokal").

- **Lange Laeufe ueberwacht:** `/test weekly|all|capstone` startet `heavy.sh` jetzt selbst in
  `tmux` und wacht mit einem Hintergrund-Waechter bis zum Report, statt Kevin die tmux-Zeile
  zurueckzugeben; Verdict-Zeile, Summary-Zeilen, VM-Liste und die Roadmap-Zeilen des Laufs
  kommen als Meldung. Start und Abbruch bleiben Kevins Zuruf; die Ebene `all` startet die Session seit
  2026-10-15 ausserdem selbst als faelligen Sammellauf (siehe „Schwere Suite als Sammellauf“).

- **Audit-Hygiene:** `audit.yml` installiert `pip-audit` und `cargo-audit` jetzt gepinnt
  (2.10.1 bzw. 0.22.2, wie `govulncheck@v1.7.0` seit dem letzten Update-Lauf) — ein Job
  darf nicht rot werden, weil ein Werkzeug ueber das Wochenende seine Exit-Codes oder
  seine Advisory-Quelle geaendert hat. Neu prueft `scripts/dev/toolchain-lockstep.sh`
  (CI-Step im Job `frp-consistency`), dass alle `go-version`-Stellen in
  `ci.yml`/`release.yml`/`audit.yml` uebereinstimmen und die `go`-Direktive des gepinnten
  `x/vuln`-Release nicht darueber liegt — sonst scheitert der Audit-Job unter
  `GOTOOLCHAIN=local` schon am Installieren von `govulncheck` und meldet nichts ueber
  unsere Dependencies. Ist der Modul-Proxy nicht erreichbar, endet der Check mit 75
  (SKIP) und faerbt den Job rot, statt eine Pruefung durchzuwinken, die nie lief. `DEVELOPMENT.md` beschreibt die drei Werkzeuge jetzt auch lokal,
  in denselben Versionen wie CI.

- **Ausfuehrung zuerst (Autonomie-Roadmap, Stufe 3):** Der Release-Workflow prueft jetzt
  das Ergebnis statt des Rezepts — das Agent-Binary muss statisch sein und darf kein
  `GLIBC_`-Symbol importieren, das ausgelieferte `.deb` darf keine zstd-Member tragen,
  die frische `SHA256SUMS.minisig` wird gegen den in `scripts/update.sh` gepinnten
  Public Key verifiziert, die Windows-`.exe` wird einmal ausgefuehrt und muss die
  Tag-Version drucken (neuer harter Job `agent-windows-smoke`), und das MSI wird
  installiert, geprueft und wieder deinstalliert (weiter `continue-on-error`).
  `scripts/release/check-versions.sh <X.Y.Z>` prueft alle sechs handgepflegten
  Versions-Stellen statt nur `tauri.conf.json` — dabei kam heraus, dass die
  Sidebar-Footer der beiden Landing-Pages seit 0.43.2 hingen (mehrzeiliges Markup, vom
  alten Muster nie erfasst); sie sind mitgezogen. Die Go-Suite laeuft in CI unter `-race`, in
  `run.sh` dort, wo ein C-Compiler mit cgo vorhanden ist (sonst sagt der Lauf, dass der
  Detektor aus war).
  Neu ist der **Wochenlauf** `bash scripts/tests/heavy.sh all|capstone|weekly`: ein
  Wrapper um die vorhandenen crabbox-Skripte, der einen Report mit den woertlichen
  Summary-Zeilen schreibt, jeden roten Schritt mechanisch als `infra`, `flaky`,
  `unbestaetigt`, `extern` oder `reg` klassifiziert (Wiederholung auf derselben Box,
  dann eine frische zweite VM, dann eine Gegenprobe gegen den letzten PASS-Commit) und
  aus einer bestaetigten Regression eine Roadmap-Zeile plus Kurz-Ledger macht. Er
  startet nie von selbst. Zusaetzlich abgedeckt: der Upgrade-Pfad vom letzten
  veroeffentlichten Release auf den aktuellen Stand (`upgrade_path_test.sh`, inkl.
  `update.sh` real) und die fuenf Desktop-Specs, die bisher von keinem Skript gefahren
  wurden (`desktop_e2e_misc.sh`). Der Multibox-Capstone schliesst `--enforce` ein und
  meldet jede bedingte Pruefung, die nicht lief, als SKIP statt sie zu verschweigen.

- **Test-Infrastruktur (Autonomie-Roadmap, Stufe 1 — „Gruen heisst Beweis"):** Der
  Test-Aggregator `scripts/tests/run.sh` kennt `--strict`, `--only <keys>` und
  `--step <name>`; unter `--strict` ist ein uebersprungener Pflicht-Schritt ein
  Fehler statt eines PASS, ebenso ein strenger Lauf, in dem ueberhaupt nichts lief.
  Die pytest-internen Skips sind jetzt sichtbar (`N passed, M failed, K skipped,
  J test-skips, R reruns`) und fuer Tests mit erfuellter Vorbedingung ein Fehler.
  Jeder Lauf schreibt `last-<layer>.json` mit Tree-Hash als Evidenz. Neu:
  `scripts/dev/verify.sh <komponente>` als einzige Verify-Form (Flags statt
  Env-Praefix, `last-verify.json`), `scripts/dev/tree-hash.sh` und ein
  Session-Status-Hook, der jede Session mit einem `AH-STATUS`-Block eroeffnet.
  Elf Stellen, die mangels Toolchain still `exit 0` meldeten (die sieben
  Desktop-GUI-Suiten und vier in `agent_install_test.sh`), enden jetzt mit
  `exit 75` = SKIP; die beiden minisign-Weichen in `install_test.sh`/
  `update_test.sh` melden ebenfalls SKIP, statt den Signaturpfad zu
  neutralisieren und PASS zu melden. Der
  crabbox-Bootstrap bricht ab, statt eine halb hydrierte Box zu hinterlassen.
  CI bekommt den Job `agent-windows`, der die Go-Suite erstmals nativ unter
  Windows ausfuehrt. `@typescript-eslint/no-unused-vars` ist in Web-Panel und
  Desktop-UI von `warn` auf `error` gestellt — ein verwaister Import laesst einen
  PR jetzt durchfallen, statt nur zu warnen.

- **Entwickler-Harness (Autonomie-Roadmap, Stufe 0):** `CLAUDE.md` auf 179 Zeilen neu
  geschnitten (Betriebsmodell, Warn-Trigger, Stufen-Fahrplan, Definition of Done); die
  Release- und Test-Stolperfallen leben jetzt als pfadgebundene Regeln unter
  `.claude/rules/` (`testing.md`, `docs.md`, `release.md`). `.gitignore` gibt
  `.claude/rules/` und `.claude/agents/` frei und haelt `.ah-out/`, `.vm/` und
  `tasks/private/` lokal. Die Autonomie-Roadmap liegt im privaten Repo statt unter
  `docs/features/`.

## [0.45.0] - 2026-09-08

### Fixed

- **Agent-Installation scheitert nicht mehr am apt-Lock:** Auf einer frischen
  Debian-/Ubuntu-Maschine laeuft `unattended-upgrades` direkt nach dem Boot, und
  `agent-install.sh` lief mit seinem ersten `apt-get update` genau da hinein. Der
  Abbruch meldete „repo unreachable or TLS/GPG problem" — eine Fehldiagnose, die
  in die voellig falsche Richtung schickt. Jeder apt-Aufruf laeuft jetzt mit
  `DPkg::Lock::Timeout` (apt wartet damit selbst auf die Sperre, ohne Zusatz-
  Werkzeug, deckt aber nur die dpkg-Sperren ab) und wird zusaetzlich von einer
  Warteschleife ueber alle vier apt/dpkg-Sperren gedeckt. Der Listen-Lock von
  `apt-get update` — der tatsaechliche Ausloeser — kennt keinen apt-Timeout und
  ist jetzt zusaetzlich durch drei Wiederholversuche abgesichert; der Fehlertext
  nennt die Sperre als moegliche Ursache.

- **„Jetzt pruefen" meldet keinen Erfolg mehr, wo nichts passiert:** Der Endpunkt
  `POST /api/monitoring/checks/{id}/run` rief `execute_check` auch fuer
  push-ausgewertete Check-Typen (`agent_resources`, `service_process`,
  `proxmox_backup`, `zfs_health`, `docker_health`, `smart_health` — 6 von 11)
  und fuer deaktivierte Checks auf. Beide steigen dort still aus; der Endpunkt
  antwortete trotzdem mit HTTP 200 und unveraendertem Zustand, was von
  „geprueft, unveraendert" nicht zu unterscheiden war. Jetzt kommt in beiden
  Faellen ein `409` mit Klartext-Begruendung. Der Desktop-Client bietet die tote
  Aktion gar nicht mehr an: Der „Jetzt pruefen"-Knopf ist fuer diese Checks
  ausgegraut und nennt im Tooltip den Grund. `agent_ping` bleibt ausloesbar — er
  misst das Ausbleiben eines Pushes und wird vom Scheduler ausgewertet.

- **Hook-Ausfuehrung bleibt nach einem fehlgeschlagenen Prozess-Start nutzbar:**
  Das Semaphore-Permit wurde vor `subprocess.Popen` geholt, das freigebende
  `try`/`finally` begann aber erst nach dem Start der Lese-Threads. Schlug
  dazwischen etwas fehl — `Popen` bei Speicherdruck, `Thread.start` bei
  erschoepftem Thread-Kontingent —, war das Permit dauerhaft verloren. Nach acht
  solchen Fehlschlaegen meldete **jeder** Hook bis zum Neustart „Server
  ausgelastet", obwohl gar keiner mehr lief.
- **Deaktivierte Schaltflaechen sehen im Desktop-Client jetzt auch deaktiviert
  aus:** Das Stylesheet hatte keine einzige `:disabled`-Regel — ein gesperrter
  Knopf war optisch nicht von einem funktionierenden zu unterscheiden und
  leuchtete beim Ueberfahren weiter auf. Betrifft ueber die Monitoring-Knoepfe
  hinaus alle `.btn`-Schaltflaechen, etwa Speichern-Knoepfe waehrend eines
  laufenden Vorgangs.

- **Kein Heartbeat-Sturm mehr bei Uhr-Spruengen des Monitoring-Hosts:** Die
  agent_ping-Staleness
  misst auf der Wanduhr (nur die ist ueber Prozessgrenzen persistierbar) — ein
  NTP-Vorwaertssprung groesser als `stale_minutes` liess dadurch schlagartig
  ALLE Agents als "nicht erreichbar" gelten und schaltete ueber die
  Host-down-Unterdrueckung zugleich alle anderen Alerts dieser Server stumm.
  Ein monotoner Zweit-Zeitstempel entlarvt den Sprung jetzt (Divergenz > 60 s);
  der Checker rechnet ihn heraus und bewertet auf der echten Stillstandszeit
  weiter — ein frischer Agent bleibt ok, ein wirklich toter bleibt critical.

### Security

- **cryptography auf 50.0.1 angehoben (Server + CA-Issuer):** Die gepinnte
  Version 48.0.1 war von PYSEC-2026-3552, -3553 und -3554 betroffen
  (PKCS#7-Entschluesselung bzw. X.509-Verifier; behoben ab 50.0.0). **Diese
  Pfade nutzt der Code nicht** — gebaut und signiert wird ueber
  `CertificateBuilder`/`CertificateSigningRequestBuilder`, PKCS#7 und
  `x509.verification` kommen nirgends vor. Angehoben wird trotzdem, weil
  cryptography ausgeliefert in der eigenen PKI (CA-Issuer) und im mTLS-Pfad des
  Servers steckt. Die Untergrenze in beiden `requirements.in` steht jetzt auf
  `>=50.0.0`, damit ein spaeterer Resolver nicht hinter die Sicherheitsschwelle
  zurueckfaellt; die gehashten Lockfiles wurden neu erzeugt.
- **npm-Lockfiles von Web und Desktop-UI bereinigt:** `npm audit fix` (ohne
  `--force`, also rein semver-kompatibel) hebt `brace-expansion`, `nanoid`,
  `postcss`, `postcss-selector-parser` und `undici` an, im Web zusaetzlich
  `@humanfs/core` und `@humanfs/node` — durchweg Build- und Test-Werkzeug, das
  nicht ausgeliefert wird. Beide Projekte melden jetzt `found 0
  vulnerabilities`. Fuer `apps/desktop/e2e` reichte das nicht: der
  WebdriverIO-Stack hing an `extract-zip`, fuer das es **keine** gepatchte
  Version gibt (GHSA-jmr9-qjv8-65gv). Zwei `overrides` loesen das ohne
  Unterdrueckung — `deepmerge-ts ^8.0.0` und `@puppeteer/browsers ^3.2.1`, das
  den Entpack-Pfad von `extract-zip` auf `modern-tar` umstellt. Danach greift
  auch dort `npm audit fix`, und alle drei Projekte melden
  `found 0 vulnerabilities`.
- **Rust-Abhaengigkeiten des Desktop-Clients entschaerft:** `quick-xml` steht
  jetzt auf 0.41.0 statt 0.37.5/0.38.4 (RUSTSEC-2026-0194 und -0195, ueber
  `plist` 1.10.0; `tauri-winrt-notification` 0.7.3 streicht seine
  quick-xml-Abhaengigkeit ganz), und mit
  `tauri-plugin-log` 2.9.1 faellt der Teilbaum `byte-unit` → `rust_decimal` →
  `rkyv` samt RUSTSEC-2026-0235 ganz aus dem Baum. `cargo audit` meldet keine
  Vulnerabilities mehr. Bewusst als gezielte `-p`-Bumps (26 Pakete) statt eines
  vollen `cargo update` (246 Zeilen inkl. tokio, hyper, rustls und einem
  signal-hook-Major) — vor einem Release nur so viel Flaeche wie noetig.

## [0.44.0] - 2026-07-28

### Added

- **Monitoring: Standard-Templates + Seeding:** Fuenf Built-in-Templates (Linux
  Server, Windows Server, Proxmox Host, Docker Host, ZFS Storage) mit
  recherchierten Schwellwerten (Zabbix/Netdata/Checkmk/Backblaze) werden beim
  Start des Monitoring-Dienstes einmalig geseedet (Tombstone in
  `monitor_seed_state` — User-Edits und -Deletes ueberleben jeden Neustart).
- **Tag-basierte Template-Zuweisung:** Ein Template laesst sich an einen
  Server-Tag binden; der Sync materialisiert Zuweisungen sofort bei
  Server-Aenderungen und alle 15 Minuten (`GET /api/internal/servers`,
  `POST /templates/tag-sync`). Manuelle Zuweisungen bleiben unangetastet.
- **Template-Zuweisung in der UI:** Template-Modal mit Server-Mehrfachauswahl
  (Bulk), Opt-in-Template-Dropdown im Server-Anlege-Dialog, Zuweisungs-Sektion
  im Server-Monitoring-Tab und Uebersichts-Banner "N Server ohne Monitoring"
  mit Bulk-Zuweisungs-Dialog.
- **Maintenance-Fenster (pro Server oder global):** einmalig oder woechentlich (Wochentage +
  Zeitfenster in IANA-Zeitzone, DST-korrekt), collect-but-mute — Checks und
  Metriken laufen weiter, Alerts und Hub-Benachrichtigungen sind unterdrueckt.
- **Disk-Full-Prognose (`disk_forecast`):** Least-Squares-Fuellrate aus der
  VictoriaMetrics-Historie pro Mountpoint — warnt bei "voll in <= 24 h",
  kritisch bei "<= 8 h", deutlich vor den statischen Disk-Schwellen.
- **Kachel-Grid + Heartbeat:** Die Monitoring-Uebersicht bekommt eine
  umschaltbare Kachel-Ansicht (Worst-State-Farbe pro Server) und einen
  24-h-Verfuegbarkeits-Balken aus der `agent_ping`-Timeline; Loading-/Empty-/
  Error-States mit Retry.
- **Default-Subscription fuer neue Admins:** Jeder Admin-Create-Pfad (API, CLI
  `create-admin`, `ADMIN_PASSWORD`-Env, Bootstrap-Endpoint) legt automatisch
  eine Benachrichtigungs-Regel "Alle Server / warning / Glocke" an — auf
  Frisch-Installationen erreicht damit jeder Alert mindestens die Admins.
- **`alert.triggered`-Event-Hook:** Kritische Monitoring-Transitionen feuern
  den bisher nur dokumentierten Hook jetzt wirklich (Payload `server_id`,
  `severity`, `title`, `message`).
- **Retention konfigurierbar:** `ALERT_LOG_RETENTION_DAYS` (Alert-Log, Default
  90 Tage) und `VM_RETENTION` (VictoriaMetrics, Default 90d) als Env-Variablen.

### Changed

- **Alerter mit Sent-State (Level-Semantik):** Der Alerter merkt sich pro Check
  den zuletzt real gemeldeten Status (`monitor_states.notified_status`, Migration
  mit Backfill) und meldet Diskrepanzen nach, sobald keine Unterdrueckung mehr
  greift: Ein Problem, das waehrend eines Host-Ausfalls entstand und danach
  bestehen bleibt, wird nach der Agent-Recovery nachgemeldet; Recoveries fuer
  vor einem Maintenance-Fenster gesendete Alerts und Probleme, die das Fenster
  ueberdauern, werden nach Fenster-Ende nachgeholt; `unknown -> ok` erzeugt nur
  noch dann eine Recovery, wenn zuvor real ein Problem gemeldet wurde (kein
  Recovery-Spam durch ok/unknown-Flapping). Transitionen vollstaendig innerhalb
  eines Fensters bleiben weiterhin stumm.
- **unknown-Policy:** Uebergaenge nach `unknown` benachrichtigen nie mehr
  (vorher eskalierte `unknown` wie ein Failure); `unknown -> ok` meldet nur
  noch nach einem real gemeldeten Problem eine Recovery (siehe Sent-State-
  Eintrag oben).
- **Alert-Daempfung:** `agent_resources` arbeitet pro Metrik mit Hysterese
  (Release = Entry - 10 pp, konfigurierbar via `hysteresis_pp`); steht der
  `agent_ping` eines Servers auf critical, sind alle anderen Checks des
  Servers unterdrueckt (Host-down-Inhibition).
- **Agent-Liveness persistiert:** Der letzte Push-Zeitpunkt liegt jetzt in
  `monitor_agent_liveness` und wird beim Start hydratisiert — kein
  False-Alert-Sturm nach einem Monitoring-Restart; `stale_minutes`-Default 15.
- **Check-Konfiguration strikt validiert:** Pro Check-Typ ein striktes
  Pydantic-Modell — Tippfehler in Config-Keys und Werte ausserhalb der Grenzen
  geben 422 statt stumm `unknown`.
- **Monitoring-Modals vereinheitlicht:** Gemeinsame UI-Primitives (Modal,
  ConfirmDialog, EmptyState) im AdminCave-Design ersetzen die duplizierten
  Editor-Overlays; Check-CRUD direkt auf der Monitoring-Seite.

### Fixed

- **`restore.sh` stellt `./data` wieder her, statt daran zu scheitern:**
  `backup.sh` sichert das Verzeichnis im Container (als root), der Restore
  raeumte und entpackte es aber mit dem Host-`tar` als aufrufender Nutzer — die
  Bereinigung schlug still fehl und das Entpacken starb an `Cannot utime` /
  `Cannot mkdir`. Disaster Recovery scheiterte damit genau dann, wenn man sie
  braucht, mit irrefuehrender Meldung. Wipe und Extraktion laufen jetzt als
  Container-Root (wie `restore_volume`), der Tar-Escape-Guard bleibt davor.
- **Ping-/TCP-Checks erreichen wieder interne Ziele:** Der SSRF-Schutz lehnte in
  `ping` und `tcp` auch private/reservierte Adressen ab (10.x, 192.168.x,
  localhost) — damit war der Hauptanwendungsfall, interne Server zu ueberwachen,
  nicht moeglich; die Checks blieben dauerhaft auf `unknown`. Beide pruefen jetzt
  beliebige Ziele (Anlegen bleibt Admin-only, das Signal ist reine
  Erreichbarkeit). `http`-Checks und Alert-Webhooks bleiben bewusst geschuetzt:
  Sie liefern bzw. verschicken Antwort-Inhalte (Cloud-Metadaten).
- **Web-Panel: Hook-Editor bietet alle Events an:** Die Event-Auswahl im
  Hook-Dialog fuehrte eine eigene, veraltete Liste — `playbook.*` und das neue
  `alert.triggered` fehlten und waren nur per API abonnierbar. Die Liste ist
  ergaenzt (inkl. Labels DE+EN) und ein Guard-Test pinnt sie jetzt gegen die
  Server-Whitelist `VALID_EVENTS`.
- **Admin-Doku Monitoring (DE+EN):** Das dokumentierte
  `warn_threshold`/`crit_threshold`-Modell existierte nicht — ersetzt durch
  die echten per-Typ-Config-Keys samt Defaults; der `alert.triggered`-Abschnitt
  beschreibt jetzt den implementierten Hook.

## [0.43.2] - 2026-07-14

### Fixed

- **Agent-Binary laeuft wieder auf aelterer glibc (Debian Stretch, RHEL 8,
  UniFi-/Appliance-Firmware):** Der Release-Build baute den Agent mit einem
  nackten `go build`, das die Runner-Default `CGO_ENABLED=1` erbt und dadurch
  **dynamisch** gegen die glibc des Build-Hosts (2.39) linkt — das ausgelieferte
  Binary brach mit `GLIBC_2.34 not found`. Der Release baut den Agent jetzt
  **ueber den Makefile** (`CGO_ENABLED=0`, vollstatisch), sodass es genau das
  getestete Binary ist. Zusammen mit dem xz-Fix aus 0.43.1 installiert **und**
  laeuft das Paket damit auf dem gesamten unterstuetzten Feld.
- **Regressions-Guard:** Der Multibox-Test installiert das frische `.deb` jetzt
  in einem `debian:9`-Container (dpkg 1.18 + glibc 2.24) **und fuehrt das Binary
  aus** — faengt kuenftig beide Klassen (Kompression und glibc-Linkage), die die
  reine Modern-Ubuntu-Testflotte durchrutschen liess.

## [0.43.1] - 2026-07-14

### Fixed

- **Agent-`.deb` installiert wieder auf aelterem Debian / Appliance-Hosts:** Das
  Paket wurde auf modernen Build-Hosts mit **zstd**-Kompression gebaut, die ein
  aelteres `dpkg` (Debian Stretch/Buster, UniFi- und aehnliche Debian-basierte
  Firmware) nicht lesen kann (`unknown compression for member 'control.tar.zst'`).
  `build-deb.sh` erzwingt jetzt **xz** (verstaendlich fuer jedes `dpkg` seit
  Debian 6), plus ein Build-Guard, der einen zstd-Rueckfall hart failt. Das
  Agent-Binary selbst war nie betroffen (statisch, `CGO_ENABLED=0`).
- **`agent-install.sh` haengt nicht mehr an einem nicht erreichbaren Port:** die
  Repo-/Release-Fetches bekommen `--connect-timeout 10`, brechen also mit klarer
  Meldung ab, statt am TCP-SYN eines gefilterten `:8445` stillzustehen.

## [0.43.0] - 2026-07-13

### Added

- **Ein-Befehl-Agent-Rollout (`scripts/agent-install.sh`):** richtet auf
  Debian/Ubuntu (apt) und Rocky/Alma/RHEL (dnf) das server-eigene Paket-Repo
  ein (Repo-Schluessel von `:8445` mit **erzwungenem** GPG-Fingerprint-Vergleich
  gegen den gepinnten Projekt-Schluessel), installiert den Agent und
  provisioniert ihn direkt mit. Nach erfolgreichem mTLS-Enrollment stellt das
  Skript die Repo-Quelle automatisch auf CA-Pinning um (apt `CAInfo` /
  dnf `sslcacert`). Token optional per `/dev/tty`-Abfrage;
  `--from-github`-Fallback (minisign-verifiziert, apt). Liegt auch im
  Runtime-Bundle (`/opt/adminhelper/scripts/agent-install.sh`).
- **Verifizierter Erstkontakt (`adminhelper-agent provision --ca-fp`):** Der
  Agent prueft im TLS-Handshake, dass die praesentierte Kette die interne CA
  mit genau diesem SHA-256-Fingerprint enthaelt und das Server-Leaf
  kryptografisch daran haengt — der Einmal-Token verlaesst den Host erst nach
  bestandener Pruefung (ersetzt blindes Trust-on-first-use).
- **Provisionierungs-Tab als Vertrauensanker-Kurier:** generiert den
  Install-Einzeiler und den `provision`-Befehl inklusive `--ca-fp` (der
  Desktop kennt die interne CA aus seinem eigenen Enrollment) und zeigt den
  CA-Fingerprint fuer den Out-of-band-Vergleich an; ohne enrollte Identitaet
  sichtbarer Hinweis auf den unverifizierten TOFU-Erstkontakt.

### Changed

- **Multibox-Suite testet den echten User-Pfad:** Server-Box baut und signiert
  ein Test-Repo auf `:8445`, Agent-Box installiert ueber das reale
  `agent-install.sh` mit `--gpg-fp`/`--ca-fp` und asserted Repo-Quelle und
  CA-Pinning-Endzustand.

### Fixed

- **Multibox: .deb-Pfad-Capture repariert** — `cbx_build_agent_deb` leakte
  make-/dpkg-Ausgaben in den per Command-Substitution zurueckgegebenen Pfad
  (betraf alle vier Rollen-Boxen der Suite).
- **Doku:** toter Verweis auf eine Ansible-Beispiel-Role
  (`apps/agent/ansible/`) ersetzt; veraltete Versionsbeispiele im
  Agent-Install-Abschnitt (README, EN-Doku) bereinigt.

## [0.42.0] - 2026-07-13

### Added

- **Trust-Dialog beim Erstkontakt (Desktop):** Praesentiert der Server ein nicht
  oeffentlich vertrauenswuerdiges Zertifikat (Standard-Installation mit
  AdminHelper-eigener PKI), fragt der Login-Screen bei Anmeldung und
  Token-Enrollment per Dialog, ob dem Server dennoch vertraut werden soll —
  Bestaetigen aktiviert dauerhaft "Selbstsignierte Zertifikate erlauben"
  (TOFU-Pin) und wiederholt die unterbrochene Aktion automatisch. Neuer
  stabiler Fehlercode `ERR_TLS_UNKNOWN_ISSUER` ersetzt die rohe rustls-Meldung.

### Fixed

- **"invalid peer certificate: UnknownIssuer" beim Bootstrap:** Der allererste
  Login-/Enrollment-Versuch mit Default-Einstellungen lief gegen die
  Standard-PKI in eine Sackgasse (roher TLS-Fehler ohne Handlungs-Hinweis) —
  jetzt Trust-Dialog bzw. verstaendliche Meldung mit Verweis auf die
  Einstellung.
- **"Selbstsignierte Zertifikate erlauben" war im Server-Modus unsichtbar**
  (die Checkbox wurde nur im Sync-Modus gerendert, obwohl Login/Enrollment sie
  auch im Server-Modus auswerten) — liegt jetzt im gemeinsamen Bereich beider
  Remote-Modi.
- **desktop_e2e_crud.sh laeuft standalone auf frischen Boxen:** fehlende
  node_modules werden selbst installiert (vorher zog `npx wdio` das falsche
  Wizard-Paket aus der Registry und der Tauri-Build scheiterte an fehlendem
  svelte-check).

## [0.41.0] - 2026-07-13

### Added

- **AdminCave-Design-System-Retheme (Web + Desktop):** beide Svelte-Frontends auf die
  visuelle Sprache des AdminCave-Design-Systems umgestellt — monochrom, True-Black
  dark-first, gebuendelte Geist-Schrift (offline-/CSP-fest, kein CDN), Pill-Radien,
  monochrome Primary-Buttons, Hairline-Borders und der AdminCave-Brand-Mark
  (currentColor, keine Verlaeufe mehr). DOM-Struktur und Layout bleiben unangetastet.
- **Light-Mode mit Umschalter:** gleichwertiger Light-Mode neben dem Default-Dark;
  Icon-Umschalter im Sidebar-Footer (Web neben EN/DE, Desktop neben Einstellungen),
  FOUC-frei via Inline-Script im `<head>`, Praeferenz in `localStorage['ah-theme']`
  (nicht im persistierten Settings-Contract, keine Migration). Monitoring-Charts (uPlot)
  und Status-Timeline sind theme-adaptiv.

## [0.40.0] - 2026-07-11

Umfassendes Security- und Qualitaets-Audit ueber alle Komponenten (Server,
Monitoring, Agent, Desktop, CA-Issuer, Gateway, Web): 590 Funde behoben,
CI (inkl. Windows) und die vollen Test-Suiten gruen.

### Fixed

- **Sicherheit:** Netz-Segmentierung des CA-Issuers (nur ueber die interne
  PKI-Plane erreichbar), Rate-Limit auf der CA-Renew-Plane, Secrets nur noch
  ueber stdin statt argv, Zip-Bomb-Schutz beim Report-Ingest, IPv6-taugliche
  Enroll-Endpunkte, gehaertete Header-/mTLS-Terminierung am Gateway.
- **Korrektheit:** deterministische FRP-Config-/Tunnel-Generierung, explizite
  UTC-Defaults in der Datenbank (Zeitzonen-Bug), Entfernung doppelt
  geschriebener Monitoring-Metriken, robustere System-Metrik-Parser (systemd,
  Docker/ZFS, SMART).
- **Desktop:** Windows-.rdp-Launch-Dateien (Host/Benutzername) werden beim
  naechsten Start zuverlaessig aufgeraeumt, Enrollment respektiert die
  Self-Signed-Einstellung, stabilere RDP-/SSH-/Tunnel-Verbindungsfluesse.

### Changed

- **Architektur:** Import-Zyklen aufgebrochen, Client-/Factory-Logik
  extrahiert, ConnectionKind-Vertrag auf ssh/rdp/web vereinheitlicht,
  Validierung konsequent an den Boundaries.
- **Betrieb:** Healthchecks und Startup-Reihenfolge im docker-compose-Stack
  gehaertet, FRP-bindPort-Kopplung entschaerft, Doku (DE/EN) durchgaengig
  nachgezogen.

### Added

- Umfangreiche Test-Abdeckung: neue Live-E2E-Specs (Enrollment-Formular,
  Tunnel-Erstellung/-Start/-Connect, SSH-/Web-/RDP-Connect), Windows-gated
  Unit-Tests, deterministische Alembic-Smoke- und Integrations-Suiten.

## [0.39.0] - 2026-07-04

### Changed

- **Projekt in die Admin-Cave-Organisation umgezogen.** Repo, Container-Registry
  (`ghcr.io/admincave/*`), Projekt-URLs und die Homepage (`admincave.com`) verweisen jetzt
  auf die Organisation; die Release-Signaturschlüssel (minisign + GPG) wurden neu erzeugt.

### Fixed

- **Agent: statisch gelinktes Linux-Binary (`CGO_ENABLED=0`).** Das `.deb`/`.rpm` lief
  bisher nur auf Systemen mit mindestens der glibc des Build-Hosts; auf älteren Distros
  (RHEL/Rocky/Alma 8, glibc 2.28) brach der Agent mit `GLIBC_2.34 not found` ab. Der Agent
  ist reines Go (gopsutil liest `/proc`), daher erzeugt `CGO_ENABLED=0` ein voll statisches
  Binary, das auf jeder glibc läuft.
- **Agenten-Provisionierung unter erzwungenem mTLS (`MTLS_ENFORCE=true`).** Ein frisch
  installierter Agent konnte sich nicht gegen einen bereits mTLS-erzwungenen Server
  provisionieren — sein `provision/activate`-Aufruf traf die zertifikatspflichtige
  Data-Plane (:443), bevor er ein Client-Zertifikat besaß. Die token-gesicherte
  Bootstrap-Route wird jetzt (wie `/enroll`) zertifikatslos auf der Enrollment-Plane (:8444)
  bedient; die Data-Plane (:443) bleibt unverändert zertifikatspflichtig.

### Added

- **Verteilte Multi-Host-Integrationstests via crabbox** (Entwickler-Tooling): der schwere
  Test-Tier (echter Stack, Cross-Host-mTLS, `.deb`/`.rpm`-Installation, 3-Host-FRP-Tunnel,
  Monitoring-Closed-Loop, Desktop-GUI-E2E) läuft auf ephemeren Proxmox-VMs, mit einem
  schnellen Warm-Reuse-Loop + Auto-Debug bei Fehlern. Siehe `DEVELOPMENT.md`.

## [0.38.0] - 2026-06-23

### Added

- **Server: Multi-Worker-Tauglichkeit (Skalierungs-Fundament).** Der Server kann nun
  mit mehreren Uvicorn-Workern laufen (`WEB_CONCURRENCY`, Default 1 = unverändert).
  Damit die periodischen Jobs (E-Mail-Outbox, Aufbewahrungs-Cleanups, Scheduled
  Hooks) genau einmal laufen, ist der **APScheduler in einen dedizierten
  `scheduler`-Dienst** ausgelagert (im Compose enthalten, genau eine Instanz,
  `RUN_MODE=scheduler`); die Web-Worker führen nur noch `uvicorn` aus. Scheduled
  Hooks werden vom Scheduler-Prozess periodisch aus der DB rekonziliert statt direkt
  von den Routern registriert. Das Rate-Limit warnt bei Multi-Worker ohne Redis; der
  DB-Pool ist pro Worker konfigurierbar (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`).
- **Server: SSE-Push für die Benachrichtigungs-Glocke (Push statt Polling).** Neuer
  Stream-Endpoint `GET /api/notifications/stream` (Server-Sent Events): sobald ein
  Nutzer eine neue Benachrichtigung bekommt, pusht der Server ein leichtes
  „Refresh"-Signal, woraufhin die Glocke sofort lädt — statt bis zu 30&nbsp;s zu
  warten. Worker-übergreifend via Redis Pub/Sub (`stream_hub`, eine Subscription pro
  Web-Worker); der Handler ist async und DB-frei und hält keine DB-Connection über
  die Stream-Dauer. Das Gateway (nginx) proxyt den Stream ungepuffert mit langem
  Read-Timeout. Polling bleibt als Fallback.
- **Server: Fundament für ein Benachrichtigungssystem (Phase A).** Der Server wird
  zum Notification-Hub. Neue Tabellen: `notification_subscription` (pro-User-Regeln
  — Scope *alle Server* / *Tag* / *einzelner Server*, Mindest-Severity, optionaler
  Kategorie-Filter, externe Kanäle E-Mail/Telegram), `notification` (Glocken-Feed
  mit gelesen/ungelesen) und `notification_outbox` (Versand-Queue für externe
  Kanäle, mit Retry-Feldern), plus `email`/`telegram_chat_id` am User. Ein
  Recipient-Resolver fächert Events least-privilege auf — ein Nutzer wird nur über
  Server benachrichtigt, die er sehen darf (Admin oder via `user_servers`
  zugeordnet). Neue Endpoints: `POST /api/internal/events` (Event-Ingress vom
  Monitoring-Dienst, `X-Internal-Key`), `GET /api/notifications` (+ `/unread-count`,
  `/read`) als eigener Feed, und `GET`/`PUT /api/users/me/notification-prefs`
  (Self-Service-Einstellungen). Das Monitoring bleibt reine Event-Quelle; die
  Empfänger-Auflösung liegt nur im Server, wo die User↔Server-Zuordnung existiert.
  Noch ohne UI und ohne tatsächlichen Versand (folgt in späteren Phasen).
- **Monitoring speist den Hub (Phase B1).** Jeder Check-Statuswechsel wird
  zusätzlich zum regelbasierten Webhook-/E-Mail-Versand an `POST
  /api/internal/events` des Servers gepusht (`SERVER_HUB_URL`, Auth via
  `MONITOR_API_KEY` als `X-Internal-Key`, best-effort). Die Event-Severity ist der
  schlimmere der beiden Zustände, damit eine Entwarnung (`warning→ok`) auch
  Abonnenten mit Schwelle „warning" erreicht.
- **Server-interne Events speisen den Hub (Phase B2).** Der In-Process-Event-Bus
  (`fire_event`) bridged eine kuratierte Auswahl in den Hub: neuer Admin-Benutzer
  (`security`), Server entfernt und FRP-Tunnel angelegt (`lifecycle`). Reine
  CRUD-Events, die der Auslöser selbst verursacht, werden bewusst nicht gespiegelt
  (kein Noise).
- **Desktop: Benachrichtigungs-Glocke, Desktop-Notifications und Self-Service-
  Einstellungen (Phase C).** Eine Glocke mit Ungelesen-Badge im Header öffnet ein
  Panel mit dem Benachrichtigungs-Feed (app-weites Polling, solange eine
  Server-Session aktiv ist). Neue Feed-Einträge erscheinen optional als native
  **OS-Benachrichtigungen** (`tauri-plugin-notification`, opt-in mit
  Permission-Abfrage; ein „Priming"-Schritt verhindert eine Flut beim Start). In
  den Einstellungen kann jeder Nutzer seine **Kontakt-E-Mail** und beliebig viele
  **Regeln** verwalten — Geltungsbereich (alle Server / Tag / einzelner Server),
  Mindest-Schweregrad und Kanal (Glocke immer, E-Mail optional). Telegram ist im
  Datenmodell vorgesehen, aber noch nicht in der Oberfläche.
- **E-Mail-Versand der Benachrichtigungen (Phase D).** Ein APScheduler-System-Job
  (Muster wie der Audit-Retention-Job) leert die `notification_outbox` minütlich
  aus dem Request-Pfad heraus und stellt E-Mails über einen externen SMTP-Relay
  zu (`SMTP_HOST`/`PORT`/`USER`/`PASSWORD`/`FROM`, 587 STARTTLS oder 465 SMTPS).
  Fehlversuche werden mit linearem Backoff bis `NOTIFICATION_MAX_ATTEMPTS` (Default
  5) wiederholt und danach als fehlgeschlagen markiert. Damit ist der MVP-Umfang
  (Glocke + Desktop-Notification + E-Mail) vollständig.
- **Agent-Paket-Repo (apt/dnf-Update-Kanal).** Der AdminHelper-Server stellt selbst
  ein **GPG-signiertes** apt-/rpm-Repo über eine neue **certless Repo-Plane des
  Gateways** bereit (`REPO_PORT`, Default `8445`), sodass Agent-Hosts neue Versionen
  über `apt upgrade` / `dnf upgrade` beziehen statt per manuellem Download — gedacht
  für laufende Updates auf vielen Servern. `release.yml` baut das Repo
  (`apps/agent/build-repo.sh`: `InRelease`/`Release.gpg`, `rpm --addsign` +
  `repomd.xml.asc`, je ein de-/armored Public-Key) und veröffentlicht es als ein in
  `SHA256SUMS` + minisign abgedecktes Asset `adminhelper-agent-repo-<tag>.tar.gz`.
  `install.sh`/`update.sh` ziehen das Asset best-effort nach `./repo` (in-place, der
  Live-Bind-Mount bleibt gültig). Signatur via neuem Secret `REPO_GPG_PRIVATE_KEY`:
  ohne Schlüssel wird das Asset mit Warnung übersprungen und `/repo` liefert `404` —
  kein Bruch. Onboarding (apt `deb822`/`signed-by` + dnf `.repo`, GPG-Fingerprint als
  Vertrauenswurzel, TLS via CA-Pinning oder `Verify-Peer`) unter *Agent-Deployment*;
  Maintainer-Setup unter *CI/CD & Release*. Test: `scripts/tests/repo_build_test.sh`.

### Changed

- **Server-Auth-Gate-Test robust gegen FastAPI-Versionssprünge.**
  `test_route_auth_gate.py` nahm an, `app.routes` liste eingebundene Router flach
  als `APIRoute`. FastAPI 0.138 kapselt jedes `include_router()` in ein opakes
  `_IncludedRouter` → der Test sammelte 0 Routen (false-positive „route no longer
  exists", und schlimmer: der Guard-Test wäre still leergelaufen). Jetzt rekursiver
  `_collect_api_routes()` für beide Strukturen (≤0.136 flach + ≥0.138 verschachtelt)
  plus Emptiness-Guard. Trat nur in CI auf, weil der Test-Job über `requirements.in`
  die *neueste* FastAPI zieht, nicht die gehashte Lock.

### Removed

- **Desktop-E2E (tauri-driver-Smoke) aus der CI entfernt.** Die headless-WebKit-Kette
  (tauri-driver → WebKitWebDriver → WebKit unter xvfb) driftet mit dem GitHub-Runner-
  Image + ungepinnten Upstream-Tools und färbte `main` rot ohne echten Defekt — und
  überdeckte dabei einen realen Bug. Der Smoke-Test läuft jetzt wie die Desktop-
  `*.live.js`-Journeys **lokal/manuell** (`cd apps/desktop/e2e && xvfb-run -a npm test`).

### Security

- **starlette 1.2.1 → 1.3.1** in server + monitoring (gehashte Lock neu generiert):
  behebt CVE-2026-54282 und CVE-2026-54283. Vom wöchentlichen Dependency-Audit
  (`pip-audit`) erkannt; `fastapi` zieht dabei auf `0.138.0` mit (der Auth-Gate-Test
  ist bereits dafür robust, siehe Changed). `pytest` server (291) + monitoring (138)
  grün gegen die neuen Versionen, `pip-audit` ohne Befund.
- **undici 7.27.1 → 7.28.0** in `apps/desktop/ui` (transitiv über `jsdom`, eine
  Dev/Test-Abhängigkeit — nicht im Production-Bundle): behebt eine high-severity
  Sammel-Lücke (TLS-Bypass, Cache-Disclosure, Header-Injection, DoS u.a.). Nicht-
  breaking via `npm audit fix`; `npm audit --audit-level=high` ohne Befund, vitest
  (200 Tests) grün.
- **quinn-proto 0.11.14 → 0.11.15** im Desktop-Backend (transitiv über `quinn`):
  behebt RUSTSEC-2026-0185 (Remote Memory Exhaustion durch unbegrenztes
  Out-of-order-Stream-Reassembly). Patch-Bump via `cargo update -p quinn-proto`
  (nur diese Crate); `cargo check` grün, vollständige fmt/clippy/test-Prüfung im
  CI-Rust-Job.

## [0.37.2] - 2026-06-20

### Added

- **Desktop: Live-E2E für den Settings-Moduswechsel** (`settings-mode.live.js`,
  läuft mit im `desktop_e2e_crud.sh`-Boot). Wechsel server→local in den
  Einstellungen beendet die Server-Session und lädt in den Local-Mode; verifiziert
  wird der beobachtbare Seiteneffekt: das Modus-Badge wechselt und die server-only
  Navigation (Infrastruktur) verschwindet.
- **Desktop: Live-E2E für „SSH/Web/RDP über FRP-Tunnel" (voller End-to-End-
  Durchstich)** (`desktop_e2e_connect_tunnel.sh`, `tunnel-connect.live.js`). Die App
  enrollt, die Tunnel connecten, und das Öffnen der per `connection_id` verknüpften
  Connections schickt `ssh`/Browser/`xfreerdp3` über die **ganze FRP-Strecke**:
  Desktop-frpc-Visitor → frps → **ein agent-frpc mit drei STCP-Proxies** → echte
  `sshd`-/`nginx`-/`xrdp`-Container (zielseitig verifiziert). Der STCP-Server ist
  ein echter Agent, der via Provisioning seine `frpc.toml` + enrollte mTLS-Identität
  bekommt und mit `snowdreamtech/frpc` läuft. Die getunnelten Connections nutzen
  **tote Platzhalter-Ziele**, damit nur der Tunnel-Pfad (nicht ein Direkt-Treffer)
  grün sein kann.
- **Desktop: Live-E2E für „Verbindung öffnen" gegen echte Ziel-Container**
  (`desktop_e2e_connect.sh`). Die App öffnet über die GUI eine **SSH**-Verbindung
  (`openssh-server`), eine **Web**-Verbindung (`nginx`) und eine **RDP**-Verbindung
  (`xrdp`; inkl. des Passwort-Prompts, den der Desktop auf Linux für RDP zeigt). Da
  der Desktop `ssh`/Browser/`xfreerdp3` als externe Prozesse startet, wird
  zielseitig verifiziert: **sshd-Log** (eingehende Verbindung), **nginx-Access-Log**
  (Web-Fetch via `xdg-open`-Shim) bzw. **xrdp-Log** (RDP-Handshake) — analog zur
  frps-Log-Prüfung des Tunnel-Tests.
- **Desktop: Live-E2E für die Monitoring-Check-Journey** (`monitoring-check.live.js`,
  `desktop_e2e_monitoring.sh`) gegen **echte Agent-Daten**: ein echter Agent pusht
  Metriken, dann legt die App über die GUI einen `agent_resources`-Check an, der
  nach dem Reload aus dem Monitoring-Dienst (GUI → `api_proxy` → Gateway → Server →
  Monitoring) erscheint.
- **Integrations-E2E: echter Agent → Monitoring-Pipeline**
  (`scripts/tests/agent_monitoring_test.sh`). Mehrere echte Go-Agenten (in
  Wegwerf-Containern) provisionieren gegen den Test-Stack, **enrollen ein
  mTLS-Client-Zertifikat** und pushen Metriken; verifiziert beidseitig (Agent-Log
  „Report gesendet" + `POST /agent/{id}/report 200` im Monitoring-/Server-Log).
  Deckt die bisher nur unit-getestete Provision→Enroll→Push-Kette real ab. Das
  Test-Overlay baut den Monitoring-Dienst jetzt ebenfalls lokal.
- **Desktop: Live-E2E für die Provisioning-Journey** (`provisioning.live.js`).
  Die echte App fordert über die GUI einen Agent-Enrollment-Token an; der Server
  stellt ihn aus, die GUI listet ihn (Round-Trip). Läuft im selben
  `desktop_e2e_crud.sh`-Boot wie die GUI-CRUD-Journeys.
- **Web: Playwright-CRUD für API-Keys, Hooks, FRP-Config und Audit** (gegen die
  stateful Mocks). API-Keys: anlegen → Secret **genau einmal** im Reveal → Liste →
  löschen. Hooks: Webhook anlegen → Einmal-Token → löschen. FRP-Config: anlegen →
  bearbeiten mit **leerem Token** (der gespeicherte Secret bleibt, da das Modal
  `auth_token` weglässt). Audit: Einträge anzeigen + nach Aktion filtern. Der
  `mocks.ts`-In-Memory-Store deckt dafür `/api/api-keys`, `/api/hooks`,
  `/api/frp/server-config` und `/api/audit` ab.
- **Web: Unit-Tests für die Stores `users`, `hooks`, `frpConfig`** (analog
  `apikeys`). Der fehleranfällige Kern: optimistische Listen-Updates **per ID**
  (nicht per Index), `hooks.toggle` als Partial-Merge nur auf den passenden Hook,
  und `frpConfig.save`, das je nach vorhandener Config auf create vs. update routet.
- **Monitoring: Alert-Korrektheit** — die Schwellwert-Logik der Checker
  (`AgentResourcesChecker`/`SmartHealthChecker` `evaluate`: ok→warning→critical-
  Eskalation, `>=`-Grenze, Pseudo-FS-Filter, Temp-Overrides bzw. Disk-Typ-Temp,
  smartctl-Exit-Bitflags, NVMe-Wear (**invertiertes** `available_spare` +
  `percentage_used`/media_errors) und ATA-Wear (reallocated/pending/spin-retry))
  und die bisher ungetesteten Alert-Dispatch-Pfade
  (`_dispatch` fail-closed bei kaputter `channel_config`/unbekanntem Kanal; der
  Email-Kanal mit Empfänger-Parsing und SMTP-Host-Pflicht).

- **Desktop: Live-E2E für die GUI-CRUD-Journeys** (`scripts/tests/desktop_e2e_crud.sh`
  + `*-crud.live.js`). Die echte App legt über die GUI gegen den echten Stack eine
  Verbindung an, benennt sie um und löscht sie; legt einen Tunnel an, benennt ihn um
  und löscht ihn; legt einen Server an und löscht ihn. Jeder Schritt wird durch die
  neu geladene Liste verifiziert (GUI → `api_proxy` → Gateway → Server → Postgres →
  GUI). Geteilte Login-/Navigations-Helfer unter `apps/desktop/e2e/test/lib/`.

- **Test-Abdeckung der bisher ungetesteten Server-Module `ansible` und
  `hooks`.** Ansible (vorher 0 Tests): Admin-Authz, der Dateinamen-Allowlist als
  Path-Traversal-Guard, YAML-Validierung beim Schreiben, und der
  Create→Content-lesen→Update→Delete-Roundtrip (Inhalt auf Disk). Hooks:
  Admin-Authz, die typ-spezifische Create-Validierung (webhook/event/schedule),
  und — bisher ungeprüft — dass der Event-Dispatch (`_run_event`) wirklich nur die
  passenden, aktivierten Event-Hooks auslöst.

- **Erweiterte Unit-Test-Abdeckung an den von CLAUDE.md priorisierten Stellen.**
  Gezielt die echten Lücken geschlossen (vorhandene Abdeckung — FRP-Config-
  Generierung, `require_scope`-Enforcement, Tunnel-Auflösung — blieb unangetastet):
  Server-Authz für das `servers`-Modul (non-admin → 403, ergänzt das Struktur-Gate
  semantisch), die reinen Schema-Validatoren `_validate_server_name`
  (Pfad-/TOML-Injection-Guard) und `_validate_tags`, sowie IP-Filter-Proxy-Header-
  Spoofing (`resolve_client_ip` mit `TRUSTED_PROXIES`). Go-Agent: `round1`/`round2`
  (Metrik-Rundung, betrifft jeden Push) und `baseURL` (mTLS-Origin-Ableitung).
  Desktop-Rust: die RDP-Credential-Cache-Key-Helfer (`rdp_storage_key`,
  case-insensitiv, Port-Default). Monitoring: Ping-RTT-Parsing + Target-Hardening
  (Command-Injection-Guard) und `format_line`-Abweisung nicht-finiter Werte
  (inf/nan würden den Batch vergiften). Web: der `apikeys`-Store (das Einmal-Secret
  aus `create()` wird zurückgegeben, landet aber nie in der sichtbaren Liste).

- **Desktop: Live-E2E „Verbindung mit Tunnel über die GUI anlegen" gegen einen
  echten Stack.** `scripts/tests/desktop_e2e_live.sh` fährt den realen Backend-
  Stack permissiv hoch, seedet Admin + Server + FRP-Config per Admin-API, und
  treibt die **echte** Desktop-App (WebdriverIO + tauri-driver): Login durch das
  nginx-Gateway (TOFU, self-signed vertraut), dann im Infrastruktur-Hub einen
  Tunnel anlegen. Damit ist erstmals der volle Pfad GUI → `api_proxy` → Gateway →
  Server → Postgres abgedeckt (vorher endeten die Tests an der IPC-Grenze). Doppelt
  verifiziert: der Tunnel erscheint in der GUI **und** wird unabhängig per
  Server-API gegengeprüft. Der App-Keyring wird über eine frische
  D-Bus-Session + leeres `gnome-keyring` isoliert (sonst bricht eine real
  enrollte Identität den Login).

- **Desktop: Live-E2E „Tunnel testen" (starten + verbinden) gegen echtes frps.**
  `scripts/tests/desktop_e2e_tunnel.sh` fährt zusätzlich `frps` hoch, seedet einen
  STCP-Tunnel und mintet einen Enrollment-Token; die App enrollt ein Geräte-Cert,
  loggt sich ein, und der Infrastruktur-Hub startet den Tunnel automatisch.
  Verifiziert wird der **volle PKI-Tunnel-Pfad**: der GUI-Tunnel-Indicator
  erreicht „connected" **und** das frps-Container-Log bestätigt unabhängig, dass
  sich der Desktop-`frpc` per mTLS verbunden hat (ca-issuer-provisioniertes
  frps-Cert, Access-Intermediate-Trust). Damit ist „Verbindung mit Tunnel anlegen
  **und** testen" über die echte GUI vollständig abgedeckt.

- **Desktop: echtes End-to-End-Test-Harness (WebdriverIO + tauri-driver).** Neu
  unter `apps/desktop/e2e/`: treibt die gebaute Tauri-App über eine echte
  WebDriver-Session (auf Linux via `tauri-driver` → `WebKitWebDriver`). Erster
  Test ist ein Smoke-Test (App startet, Fenster „AdminHelper", Svelte-UI mountet)
  — die billigste sinnvolle E2E-Stufe, ohne Backend. Als eigener CI-Job
  (`desktop-e2e`, unter `xvfb`) auf `main`-Pushes + manuell, kein PR-Gate. Der
  Live-„Verbindung-mit-Tunnel-anlegen-und-testen"-Flow (braucht den echten Stack
  aus dem From-outside-Test plus `frpc`) baut auf diesem Harness auf und ist der
  nächste Schritt.

- **Desktop: Komponententests für den „Verbindung-mit-Tunnel-anlegen"-Flow.**
  `TunnelModal` und `ServerConnectionModal` werden jetzt als echte Komponenten
  gemountet (`@testing-library/svelte`), das Formular ausgefüllt und abgesendet,
  und das an den Server gehende API-Payload sowie die bedingten Felder geprüft
  (STCP↔HTTPS bzw. SSH↔Web — inkl. Validierungs-Abbruch). Der IPC-/Server-Rand
  ist gemockt, also ohne Tauri-Runtime/Server/frpc lauffähig im bestehenden
  `desktop-ui`-Job. Deckt die „anlegen"-Logik ab; das tatsächliche Öffnen/
  Verbinden bleibt plattformspezifisch (manuell verifiziert) bzw. ist über die
  Rust-Tunnel-Auflösungs-Tests und den From-outside-Integrationstest abgedeckt.

- **From-outside-Integrationstest gegen das echte Gateway.** Bisher fuhr kein
  Test den echten Multi-Container-Stack hoch — CI baute nur Images und prüfte
  Komponenten isoliert (gemockt bzw. mit DB-Override). Neu schließt
  `scripts/tests/integration_stack_test.sh` genau diese Lücke mit **einem**
  Pfad: Er startet den realen Stack (Postgres, Redis, Server, ca-issuer,
  nginx-Gateway) mit erzwungenem mTLS (`MTLS_ENFORCE=true`) und redet
  ausschließlich von außen durch das Gateway — mintet einen Enrollment-Token
  in-container, enrollt von außen per CSR über die certless Enroll-Plane (:8444)
  ein Client-Cert, und prüft den ganzen Pfad: certless → vom Gateway abgewiesen
  (400), Cert ohne JWT → 401, Cert + Login → JWT, Cert + JWT → 200. Hermetisch
  (Wegwerf-Secrets, lokal gebaute Images, isolierte Ports/Volumes, `down -v`).
  Als eigener CI-Job auf `main`-Pushes + manuell (bewusst noch kein PR-Gate, da
  Image-Build + 5-Container-Boot).

- **Struktur-Gate gegen „neuer Router ohne Auth".** Ein neuer pytest-Test
  (`apps/server/tests/test_route_auth_gate.py`) introspiziert beim Lauf alle
  gemounteten `/api`-Routen und schlägt fehl, sobald eine Route weder eine
  Auth-Dependency (`require_scope` / `get_current_user` / `get_current_admin` /
  `ApiKeyOrUser`) im Dependency-Baum trägt noch in einer kurzen, begründeten
  Allowlist bewusst öffentlicher Routen steht. Damit kann ein Modul-Router, der
  in `app.main` ohne Scope-Guard eingebunden wird, nicht mehr unbemerkt
  ungeschützt durchrutschen — der Fehler fällt im bestehenden Server-`pytest`-Job
  auf (in-process, keine DB, ~0,2 s) statt erst im Betrieb auf. Strukturell, nicht
  semantisch: geprüft wird, *ob* ein Guard verdrahtet ist, nicht *ob* er greift —
  Letzteres deckt der Integrationstest gegen das Gateway ab.

### Fixed

- **Desktop: Tunnel- und Verbindungs-Formular im Infrastruktur-Hub waren unbedienbar.**
  Beim Öffnen von „Tunnel anlegen" bzw. „Verbindung anlegen" (Server-Detail) lief der
  Initialisierungs-`$effect` in eine Endlosschleife (`effect_update_depth_exceeded`): Er
  wies `form` ein frisches Objekt zu und las direkt danach `form.tags` — wodurch der Effect
  von dem State abhing, den er selbst schreibt, und sich bei jedem Lauf neu triggerte.
  Svelte brach nach 10 Durchläufen ab und zerstörte dabei die Reaktivität des Modals:
  Eingabefelder *und* alle Buttons (inklusive „Abbrechen"/„×") waren tot. `tagsInput` wird
  jetzt aus dem lokalen, frisch erzeugten Objekt abgeleitet statt aus dem `form`-State.
  (Das Server-Anlegen war nicht betroffen — `ServerModal` leitete schon aus der lokalen
  Quelle ab.) Abgesichert durch erste mountende Komponenten-Tests (`@testing-library/svelte`),
  die den Crash reproduzieren — bislang wurde keine Svelte-Komponente in Tests gemountet.

## [0.37.1] - 2026-06-16

### Fixed

- **Desktop: Zertifikat-/Identitäts-Reset jetzt direkt am Login-Screen.** Ein TOFU- bzw.
  CA-Pin-Mismatch (z. B. nach einer Server-Neuinstallation) trat genau dort auf, wo die
  Reset-Aktionen *nicht* erreichbar waren: am Login-/Verbinden-Screen — die Einstellungen
  (und damit beide Reset-Buttons) gibt es erst nach erfolgreichem Login. Der Login-Screen
  zeigt jetzt bei einem Pin-/Identitäts-Fehler einen passenden Reset-Button direkt unter
  der Fehlermeldung („Gepinntes Server-Zertifikat zurücksetzen" bzw. — bei registriertem
  Gerät — „Geräte-Registrierung zurücksetzen"); danach neu verbinden.
- **Release-Signatur funktionsfähig (Key-Rotation).** Der minisign-Signing-Key wurde durch
  einen **passwortlosen** Key ersetzt — der bisherige war passwortgeschützt, was den CI-Schritt
  `Sign SHA256SUMS` scheitern ließ (kein interaktives Passwort möglich; 0.36.0/0.37.0 blieben
  daher unsigniert/ohne Release). Der gepinnte `MINISIGN_PUBKEY` in `scripts/install.sh` und
  `scripts/update.sh` wurde entsprechend rotiert. Der vollständige Signier-Pfad (base64-Dekodierung
  → `minisign -S` ohne Prompt → Verify gegen den gepinnten Pubkey) wurde lokal nachgestellt.

## [0.37.0] - 2026-06-16

### Added

- **Desktop: „Geräte-Identität zurücksetzen".** Neuer Einstellungs-Button (Modus
  *Server*, nur sichtbar wenn das Gerät registriert ist) für den Recovery-Fall nach
  einer Server-Neuinstallation / neu erzeugten PKI. Löscht das enrollte mTLS-Geräte-
  Zertifikat **und** den TOFU-Zertifikat-Pin in einem Schritt — danach pinnt/registriert
  sich das Gerät beim nächsten Verbinden neu. Mit Gefahren-Bestätigungsdialog.

### Changed

- **Desktop: eindeutige Fehlermeldung bei CA-Pin-Mismatch.** Präsentiert der Server
  ein Zertifikat, das nicht mehr zur bei der Registrierung gepinnten CA passt (z. B.
  nach einem Reinstall), liefert der mTLS-Client jetzt eine explizite, gefahren-bewusste
  Meldung (mögliche MITM-Attacke + Verweis auf *Geräte-Identität zurücksetzen*) statt des
  rohen rustls-Fehlers — analog zur bestehenden TOFU-Leaf-Pin-Meldung.

### Fixed

- **Release-Signatur: base64-Interpretation des Secrets.** Das `MINISIGN_SECRET_KEY`-Secret
  wird jetzt als base64-kodiertes Key-File interpretiert (`base64 -w0 minisign.key`) — der
  rohe, mehrzeilige Key wurde im Secret-Store verstümmelt. Hinweis: Das Signieren der
  `SHA256SUMS` erfordert zusätzlich einen **passwortlosen** minisign-Key (`minisign -G -W`),
  da der CI-Schritt das Passwort nicht interaktiv liefern kann.

## [0.36.0] - 2026-06-15

Ergebnis eines projektweiten Audits (Bugs, Verbesserungen, Sicherheit) über alle
fünf Code-Komponenten. Alle Punkte sind durch Tests bzw. die jeweilige
Verifikations-Suite (pytest/ruff, go test/vet, cargo clippy/test, svelte-check/vitest)
abgesichert.

### Security

- **FRP-Secrets nicht mehr lesbar zurückgegeben.** `GET /api/frp/server-config`
  maskiert `auth.token` und Dashboard-Passwort; das Web-Modal füllt sie beim
  Bearbeiten nicht mehr vor (leer lassen = unverändert) und zeigt den Auth-Token
  als Passwortfeld.
- **Monitoring-Webhooks SSRF-geprüft.** Alert-Webhook-Ziele werden — wie bereits
  der HTTP-Checker — gegen private/reservierte Adressen geprüft und ohne Redirects
  gesendet. SMTP-Port 465 nutzt jetzt implizites TLS (`SMTP_SSL`) statt eines
  Klartext-Logins.
- **Desktop: Token-Ziel-Pinning gehärtet.** `api_proxy`/`authenticated_get` pinnen
  die *finale* Ziel-URL an den angemeldeten Server und weisen Pfade ab, die die
  URL-Authority umschreiben (führendes `@`, `\`, `://`) — verhindert JWT-Leak an
  fremde Hosts. TOFU-Pinning ist jetzt race-frei (atomares `load_or_store`); rohe
  Server-Fehler-Bodies werden vor Anzeige/Log redigiert und gekürzt.
- **Web: Access-Token nur noch im Speicher** (nicht mehr in `localStorage`) — eine
  XSS-Lücke kann ihn nicht mehr aus persistentem Storage exfiltrieren; nach einem
  Reload wird die Session aus dem HttpOnly-Refresh-Cookie wiederhergestellt.
- **`restore.sh` weist manipulierte Backups ab** (absolute/`../`-Pfade, Sym-/
  Hardlink-Member) und entpackt mit `--no-same-owner` — schließt eine
  Path-Traversal-Lücke beim Wiederherstellen eines untergeschobenen Backups.
- **Docker-Base-Images per Digest gepinnt.** `postgres`, `redis`, `nginx`,
  `python`, `node`, das internet-facing `snowdreamtech/frps` und
  `victoria-metrics` sind in `docker-compose.yml` und den Dockerfiles zusätzlich
  zum Tag per `@sha256:`-Index-Digest fixiert — ein neu gepushter Tag kann nicht
  mehr still ein anderes Image unterschieben (reproduzierbare Builds). Der
  CI-FRP-Pin-Check ist digest-robust gemacht.
- **Signierte Releases (Supply-Chain).** Docker-Images werden schlüssellos mit
  cosign (GitHub-OIDC) signiert und tragen SLSA-Provenance + SBOM. Die
  Release-`SHA256SUMS` werden mit minisign signiert (`SHA256SUMS.minisig`);
  `install.sh`/`update.sh` prüfen die Signatur gegen einen im Skript gepinnten
  Public Key, bevor sie den Checksummen vertrauen — die `curl|bash`-Kette belegt
  jetzt Authentizität, nicht nur Transport-Integrität. Scharf geschaltet (Public
  Key gepinnt, Signing-Secret hinterlegt); greift ab dem nächsten Release. Der
  hermetische Update-Sandbox-Test verifiziert den signierten Pfad end-to-end.

### Fixed

- **Migrations-Sicherheit (Server).** `alembic/env.py` importiert jetzt die
  Module `audit`, `enrollment` und `provisioning`; ein künftiges
  `--autogenerate` schlägt sonst `drop_table` für `audit_log`,
  `enrollment_tokens` und `revoked_identities` vor (Datenverlust).
- **Monitoring `agent_ping` korrekt.** Wird nicht mehr zusätzlich im Push-Endpoint
  ausgewertet (dort war die Staleness immer ~0 → fälschlich „ok"); der Scheduler
  ist die einzige Quelle.
- **Monitoring-Robustheit.** Ein einzelner Check mit defekter `config` bricht nicht
  mehr die Auswertung aller Checks eines Servers ab; `process_alert` committet die
  geteilte Session nicht mehr vorzeitig (sauberes Rollback im Fehlerfall).
- **Alert-Versand blockiert den Agent-Push nicht mehr.** Webhook/SMTP-Benachrichtigungen
  werden im Agent-Push-Pfad erst *nach* der Antwort als Hintergrund-Task versendet
  (eigene DB-Session); ein langsamer/hängender Webhook- oder SMTP-Server kann den
  Push-Request — und damit bei 250–500 Agents den Worker-Pool — nicht mehr blockieren.
- **Doppelte Port-/Namensvergabe verhindert (Server).** DB-Constraints für STCP-
  `visitor_port` und Tunnel-/Benutzernamen schließen ein TOCTOU-Fenster; Konflikte
  werden als 409 statt als 500 gemeldet.
- **Connection-Import validiert.** Jeder Eintrag wird gegen `ConnectionCreate`
  geprüft (422 mit Fehlerliste) statt ungültige Werte zu persistieren oder mitten
  im Lauf 500 zu werfen; ein `replace`-Import mit fehlerhaftem Input löscht nichts.
- **Agent.** Kritische NVMe-SMART-Nullwerte (z. B. „Spare aufgebraucht") fallen
  nicht mehr aus dem Report; der Windows-Dienst reagiert beim Stop sofort
  (Push-Retry-Backoff per Context abbrechbar); der Windows-FRP-Sync bricht nicht
  mehr bei jeder Config-Änderung an einem nicht registrierten Dienst ab;
  PKI-Dateien werden mit geprüftem Close + `fsync` geschrieben; Proxmox-Backup-
  Index nutzt den echten Node-Namen statt `localhost`; OS-Info im Diagnose-Bericht
  funktioniert auch unter Windows.
- **Desktop-UI.** Beim schnellen Serverwechsel zeigen die Tabs keine Daten des
  falschen Servers mehr (Out-of-order-Fetches); die Monitoring-Sparkline lädt bei
  Zeitraum-/Check-Wechsel neu; ein RDP-Kindprozess wird bei fehlgeschlagenem
  Passwort-Stdin sauber beendet; die „vor X min"-Anzeige auf dem Dashboard wechselt
  jetzt sofort die Sprache (reaktiver Übersetzer statt Snapshot).
- **Web.** `ConfirmDialog` hängt nicht mehr bei überlappenden Aufrufen; Audit- und
  FRP-Status-Listen zeigen bei schnellem Filtern keine veralteten Antworten mehr;
  der Login zeigt bei falschen Zugangsdaten die Server-Meldung statt „Sitzung
  abgelaufen".
- **Diverse Robustheit.** inf/nan-Metrikwerte werden vor dem Line-Protocol verworfen;
  die Pagination spart die `COUNT(*)`-Query, wenn ohne Limit/Offset gelistet wird;
  Hook- und Tunnel-Updates re-validieren ihre Eingaben (kein 500 bei ungültigem
  Cron/`tunnel_type`); ein N+1 im FRP-Bulk-ZIP ist behoben; der Redis-Increment im
  Agent-Ingest-Proxy blockiert den Event-Loop nicht mehr.

## [0.35.0] - 2026-06-15

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
- **Diagnose-Bundle für Bug-Reports (`scripts/diagnostics.sh`).** Erzeugt auf dem Server-Host
  ein **redaktiertes** `tar.gz` (Versionen, OS/Docker, `docker compose ps`, pro-Service-Logs,
  `compose.yml`, sanitisierte `.env`), das der Admin durchsieht und an ein GitHub-Issue hängt.
  Secret-Werte (SECRET_KEY, Passwörter, API-Keys, JWT-/Bearer-Tokens) werden automatisch
  maskiert (Best-effort). Dazu ein GitHub-Issue-Template; das Skript ist im Runtime-Bundle
  enthalten; ein hermetischer Redaction-Test läuft im CI. Ersetzt das in der Doku erwähnte,
  nie implementierte `app.cli support-bundle`. Der Go-Agent bringt analog
  `adminhelper-agent diagnostics` mit (Version, OS, Config ohne Secrets, Log-Auszug; redaktiert).
  Der **Desktop-Client** loggt jetzt in eine rotierende Datei (+ Panic-Hook) und bietet unter
  Einstellungen → Diagnose einen „Diagnose-Bericht" (Version, OS, Log-Auszug; redaktiert).

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

[0.39.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.39.0
[0.38.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.38.0
[0.37.2]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.37.2
[0.37.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.37.1
[0.37.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.37.0
[0.36.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.36.0
[0.35.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.35.0
[0.34.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.34.0
[0.33.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.33.0
[0.32.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.32.1
[0.32.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.32.0
[0.31.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.31.0
[0.30.4]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.4
[0.30.3]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.3
[0.30.2]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.2
[0.30.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.1
[0.30.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.0
[0.29.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.29.0
[0.28.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.28.0
[0.27.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.27.0
[0.26.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.26.0
[0.25.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.25.0
[0.24.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.24.0
[0.23.2]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.23.2
[0.23.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.23.1
[0.22.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.22.1
[0.22.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.22.0
[0.21.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.21.0
[0.20.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.20.0
[0.19.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.19.1
[0.19.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.19.0
[0.17.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.17.0
