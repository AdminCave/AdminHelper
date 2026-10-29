<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Install-, Update- und Agent-Skripte: Geheimnisse über Datei und stdin, nur der gepinnte Repo-Schlüssel, Prüfung der `.env` vollständig

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/ops-install-hardening.md`. Härtung, Kevin 2026-10-22. Das Vorhaben ändert `scripts/install.sh`,
`scripts/update.sh` und `scripts/agent-install.sh`: den PR merged Kevin (CLAUDE.md §2). Das Schwester-Vorhaben
`ops-scripts-hardening` (eigener Branch) härtet `backup.sh` und `diagnostics.sh`; gemeinsam sind nur `README.md` und
`CHANGELOG.md`.

## Problem / Motivation

1. **Provisionierungs-Token als Programmargument (T1, T3).** `scripts/agent-install.sh` liest den Token auf Wunsch
   von `/dev/tty`, damit er nicht im Einzeiler und in der Shell-History steht (`:306-316`, Kopf `:32-33`), reicht ihn
   dann aber als `--token "$TOKEN"` an `adminhelper-agent provision` weiter (`:318`, `:334`). Damit steht er für die
   Dauer des Aufrufs in der Prozessliste. Der Agent kennt nur diesen Weg (`apps/agent/cmd/adminhelper-agent/main.go:96`,
   Pflicht-Flag `:103`). Für das Admin-Passwort gibt es den sicheren Weg schon: `install.sh` gibt es per
   `--password-stdin` an die CLI im Container (`scripts/install.sh:297-300`).

2. **Admin-Passwort als Programmargument (T4).** Für nicht-interaktive Installationen dokumentiert das Projekt
   `install.sh --admin-password P --yes` (`scripts/install.sh:18`, `:60`, Meldung `:223`;
   `docs/admin/installation.html:97`, EN `docs/en/admin/installation.html:75`, `README.md:176`). Unter
   `curl … | bash -s -- --admin-password P` steht das Passwort für den ganzen Lauf in der Prozessliste und in der
   Shell-History.

3. **Repo-Schlüssel (T2).** `verify_keyring` (`scripts/agent-install.sh:175-184`) prüft die heruntergeladene
   Keyring-Datei gegen den gepinnten Fingerprint (Kopf `:14-19`) und installiert sie als `Signed-By` für apt
   (`:193`, `:202`) bzw. als `gpgkey` für dnf (`:240`, `:258`). Steht der gepinnte Schlüssel nicht an erster Stelle,
   bricht die Installation ab, obwohl er in der Datei ist. Installiert werden soll genau der gepinnte Schlüssel.

4. **Prüfung der `.env` vor dem ersten compose-Aufruf (T5).** `check_env_templates` (`scripts/update.sh:124-167`)
   stoppt `update.sh` vor Backup und Tausch, wenn ein Wert ein `${` ohne gültigen Platzhalter hat, und nennt dabei den
   Schlüssel, nie den Wert. Zwei andere Fehler, an denen compose jeden Aufruf abbricht, lässt sie durch: ein nie
   geschlossenes Anführungszeichen (`:152`, `:155` gibt am Dateiende auf) und einen Schlüssel mit einem Zeichen, das
   compose im Namen nicht annimmt — auch Text direkt hinter einem schließenden Anführungszeichen, den compose als
   nächsten Schlüssel liest (`:158`, `:164`), und eine Zeile ohne `=`/`:` (`:145`). compose bricht dann erst nach
   Backup und Tausch ab. Beleg (Probe an `origin/main@b1432223`, Docker Compose v5.5.1,
   `check_env_templates` aus `update.sh` in einer Scratch-Kopie): `SMTP_PASSWORD="zz9secret`,
   `SMTP_PASSWORD='zz9secret`, `P='ab'cd'ef${q'`, `P="zz9ab"zz9cd"zz9ef"`, `"SMTP_PASSWORD"=zz9secret`,
   `zz9stray!line` und `SMTP PASSWORD=zz9secret` — die Prüfung gibt 0, `docker compose config -q` endet mit 1
   („unterminated quoted value …“, „unexpected character … in variable name …“, „key cannot contain a space“).
   `P="zz9ab"zz9cd`, `ÄKEY=…`, `a.b-c[0]=…` und ein BOM am Dateianfang vor dem ersten Schlüssel nimmt compose an.

## Ziel & Nicht-Ziele

Ziel:
- `adminhelper-agent provision --token-stdin` liest den Token von stdin; `--token` und `--token-stdin` schließen
  einander aus, einer ist Pflicht.
- `agent-install.sh` gibt den Token über stdin an den Agent, wenn dieser `--token-stdin` kennt; ein älterer Agent
  bekommt ihn wie bisher als `--token`, mit einer Warnung.
- `agent-install.sh` installiert aus der heruntergeladenen Datei genau den Schlüssel mit dem gepinnten Fingerprint
  (als Primärschlüssel), egal an welcher Stelle er steht; fehlt er, bricht es ab, bevor eine Quelle geschrieben wird.
- `install.sh --admin-password-file FILE` liest das Passwort aus einer Datei; `--admin-password` funktioniert weiter
  und gibt einen Hinweis auf den neuen Weg; die Doku nennt nur noch `--admin-password-file`.
- `update.sh` stoppt vor dem ersten compose-Aufruf auch bei einem nicht geschlossenen Anführungszeichen und bei einem
  Schlüssel, den compose nicht annimmt; die Meldung nennt den Schlüssel des Werts oder die Zeilennummer, nie Wert oder
  Zeilentext. Die Prüfung sagt genau dort nein, wo `docker compose config` nein sagt (Differentialtest).

Nicht-Ziele (YAGNI):
- Der Einzeiler im Provisionierungs-Tab des Desktops (`apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:73-87`)
  übergibt den Token weiter als `--token`; eine Änderung dort ist sichtbares Desktop-Verhalten (offene Frage 3).
- Kein `--token-file` für `agent-install.sh`, kein `--admin-password-stdin` (unter `curl | bash` ist stdin das
  Skript), keine Umgebungsvariable für das Passwort.
- `--admin-password` wird nicht entfernt (offene Frage 2).
- Die Prüfung der `.env` bleibt in `update.sh`; `install.sh`, `backup.sh`, `restore.sh` und `diagnostics.sh` bekommen
  keine eigene.
- Bestehende Agent-Hosts behalten ihren Keyring, bis `agent-install.sh` dort wieder läuft.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | agent | `apps/agent/cmd/adminhelper-agent/main.go`, `apps/agent/cmd/adminhelper-agent/provision_cmd_test.go` (neu), `CHANGELOG.md` |
| T2 | scripts | `scripts/agent-install.sh`, `scripts/tests/agent_install_test.sh`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |
| T3 | scripts | `scripts/agent-install.sh`, `scripts/tests/agent_install_test.sh`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |
| T4 | scripts | `scripts/install.sh`, `scripts/tests/install_test.sh`, `README.md`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `CHANGELOG.md` |
| T5 | scripts | `scripts/update.sh`, `scripts/tests/update_test.sh`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `CHANGELOG.md` |

`install.sh` und `update.sh` stehen auf der Risikoliste (`scripts/dev/review-risk.txt`): T4 und T5 bekommen
zusätzlich `security`; T2 und T3 ebenso (Vertrauensanker der Paketquelle, Weitergabe des Tokens), T1 empfohlen.

## Datenmodell / API / Migrationen

Keine Route, kein Schema, keine Migration. Neu sichtbar: der Flag `adminhelper-agent provision --token-stdin` (CLI des
Agents; `--token` bleibt), der Flag `install.sh --admin-password-file`, ein Hinweis bei `--admin-password`, neue
Abbruchmeldungen von `update.sh`. Vertrags-Drift: `agent-install.sh` kommt von `main` (Einzeiler,
`ProvisioningTab.svelte:74`), der Agent aus dem Repo des Servers in dessen Version — daher die Fähigkeits-Erkennung
über `provision --help` wie bei `--ca-fp` (`agent-install.sh:319-329`).

## Externe Integrationen

- GnuPG, Format der Colon-Listings (https://github.com/gpg/gnupg/blob/master/doc/DETAILS, gelesen 2026-10-22):
  „pub :: Public key“, „sub :: Subkey (secondary key)“, „fpr :: Fingerprint (fingerprint is in field 10)“; im
  Beispiel folgt jede `fpr`-Zeile ihrem `pub`- bzw. `sub`-Record (ausdrücklich steht es dort nicht; T2 prüft deshalb
  die Zeile direkt hinter `pub`). `gpg --export <fpr>` mit dem Fingerprint eines Unterschlüssels exportiert den ganzen
  Primärschlüssel samt Unterschlüsseln (Probe 2026-10-22, gpg 2.4.7; in DETAILS nicht beschrieben, der Test von T2
  pinnt es). gpg 2.4.7 startet beim Import in ein frisches `--homedir` einen gpg-agent; mit `--no-autostart` nicht
  (Probe 2026-10-22).
- compose-go `dotenv/parser.go` (https://github.com/compose-spec/compose-go/blob/main/dotenv/parser.go, gelesen
  2026-10-22): `locateKeyName` nimmt im Schlüssel Buchstaben und Ziffern (`unicode.IsLetter`/`IsNumber`) und
  `_ . - [ ]`, überspringt Leerraum (`isSpace`: Tab, VT, FF, CR, Leerzeichen, U+0085, U+00A0), endet an `=`, `:` oder
  am Zeilenende (dann ein Schlüssel ohne Wert); sonst „unexpected character %q in variable name %q“ mit der ersten
  Zeile ab dem Schlüssel. `extractVarValue`: Anführungszeichen ohne Ende → „unterminated quoted value %s“. Ein Schlüssel
  mit Leerzeichen → „key cannot contain a space“. Schiedsrichter ist das installierte `docker compose` (Test 32 in
  `update_test.sh`): v5.5.1 nimmt z. B. ein BOM vor dem ersten Schlüssel an, nur am Dateianfang. Bekannte
  Abweichung (Nachtrag 2026-10-23): einen Schlüssel mit Zahlzeichen außerhalb von ASCII wie `²` (`unicode.IsNumber`)
  nimmt compose an, die Prüfung lehnt ihn ab; sie bleibt damit auf der strengeren Seite.
- compose-Doku `.env`-Syntax (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/,
  gelesen 2026-10-22): „Single-quoted values can span multiple lines“, „Quotes can be escaped with `\`“, „Inline
  comments for quoted values must follow the closing quote“.
- cobra v1.10.2 (`apps/agent/go.mod:7`): `MarkFlagsOneRequired`, `MarkFlagsMutuallyExclusive`, `InOrStdin`.

## Trade-offs & Alternativen

1. **Weg für den Token (T1, T3).** (a) `--token-stdin` am Agent, `agent-install.sh` schreibt per `printf` (Builtin)
   in die Pipe — **Empfehlung**, wie `create-admin --password-stdin`. (b) Umgebungsvariable: nur für den Eigentümer
   lesbar, aber vererbt an jeden Kindprozess des Agents. (c) Datei: braucht Aufräumen.
2. **Älterer Agent ohne `--token-stdin` (T3).** (a) Rückfall auf `--token` mit Warnung — **Empfehlung**, wie der
   Rückfall bei `--ca-fp` (`agent-install.sh:324-328`): ein Rollout gegen einen älteren Server bricht nicht. (b) Abbruch:
   strenger, bricht aber jeden Rollout gegen einen Server, der noch nicht aktualisiert ist (offene Frage 1).
3. **Repo-Schlüssel (T2).** (a) Datei in ein eigenes, frisches GNUPGHOME unter `$_TMPROOT` importieren
   (`--no-autostart`), den gepinnten Schlüssel exportieren (apt binär, dnf `--armor`), den Export prüfen (genau ein
   `pub`, dessen Fingerprint der Pin ist) und nur ihn installieren — **Empfehlung**: installiert wird eine von gpg
   neu geschriebene Datei mit genau einem Schlüssel, unabhängig von seiner Position. (b) Abbruch, sobald die Datei mehr
   als einen `pub` trägt: einfacher, installiert aber weiter die Rohdatei und lehnt eine Datei mit altem und neuem
   Schlüssel (Rotation) ab.
4. **Passwort-Datei (T4).** `--admin-password-file` wird direkt nach dem Parsen gelesen, vor dem `cd` des
   Bootstrap-Modus (`install.sh:172`), damit ein relativer Pfad gilt; erste Zeile, ein `\r` am Ende entfällt; leer →
   Abbruch. `--admin-password` bleibt mit Hinweis (offene Frage 2); beide zusammen → Abbruch.
5. **Prüfung der `.env` (T5).** (a) Die Nachbildung in `check_env_templates` erweitern und mit dem Differentialtest
   gegen das echte `docker compose config` halten — **Empfehlung**, so ist sie gebaut (Test 32). (b) Im Preflight
   `docker compose config -q` selbst fragen und nur die Zeilennummer aus der Meldung zeigen: hängt am Meldungsformat
   und prüft dann auch die Compose-Datei.

## Risiken & Rollback

- T2 nimmt eine Keyring-Datei an, in der der gepinnte Schlüssel nicht an erster Stelle steht (heute Abbruch); die
  Datei auf dem Host hat danach genau einen Schlüssel. Ein Repo, das mit einem zweiten Schlüssel signiert, wird nach
  dem Rollout nicht mehr akzeptiert (gewollt).
- T5 kann ein Update stoppen, das heute erst am compose-Aufruf scheitert (dann nach Backup); Abbruch ohne Änderung.
- T1 ändert die Pflicht-Flags von `provision` (einer von beiden statt `--token`); bestehende Aufrufe mit `--token`
  bleiben gültig.
- Rollback je Task per `git revert`; keine Daten- oder Formatänderung.

## Doku-Impact

T2/T3: `docs/admin/agent-deployment.html:52` und `:179` (EN `:52`, `:178`). T4: `README.md:176`,
`docs/admin/installation.html:97`, EN `docs/en/admin/installation.html:75`, Kopf von `install.sh`. T5:
`docs/admin/installation.html:156`, `:213` (EN `:67`, `:166`). Die Hinweise in den älteren Neuigkeiten-Kästen von
`docs/index.html:573` und `docs/en/index.html:567` beschreiben ein früheres Release und bleiben. CHANGELOG je Task
(umlautfrei).

## Offene Fragen

1. **Älterer Agent ohne `--token-stdin`: Rückfall mit Warnung (gebaut) oder Abbruch?** Empfehlung: Rückfall, wie bei
   `--ca-fp`; der Abstand schließt sich mit dem Update des Servers. Hält T3 nicht an.
2. **`--admin-password` behalten (gebaut, mit Hinweis) oder entfernen?** Empfehlung: behalten, Entfernen später mit
   eigenem CHANGELOG-Eintrag. Hält T4 nicht an.
3. **Desktop-Einzeiler ohne `--token`** (Nicht-Ziele): eigene Zeile? Empfehlung: ja.
