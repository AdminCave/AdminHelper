<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Live-E2E: neu registrieren bei laufendem Tunnel — Task-Ledger
Status: aktiv · Branch: feature/desktop-e2e-reenroll · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0246, von Kevin am 2026-10-09 in der Triage angenommen; Delegation Kevin 2026-10-05). Offene Fragen (Aufsicht): 1 Weg (a), dritter Schritt in settings-enroll.live.js; 2 Gegenprobe ja, als Teil der Heavy-Zeile (Wegwerf-Worktree ohne den Stop in onEnroll muss am neuen Schritt rot werden; dort wird nichts committet)
Spec: Roadmap R-0246 (Kurz-Ledger ohne Spec)
Heavy: linux-full — eine Desktop-Journey kommt dazu (Neu-Registrierung in den Einstellungen bei laufendem Tunnel); auf einer Pool-VM `run.sh e2e` mit `desktop_e2e_tunnel`. Dazu eine Gegenprobe auf derselben Box: derselbe Schritt auf einem Wegwerf-Stand ohne `stopTunnel()` in `onEnroll` muss rot werden (offene Frage 2).
DoD je Task: CLAUDE.md (Tests grün, ESLint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin in der Triage vom
2026-10-09 angenommen hat („später, braucht Heavy“). Sie stammt aus dem T7-Review von R-0212 (#102). Die private
Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@af77eb3c.

### T1 — `settings-enroll.live.js`: neu registrieren, während der Tunnel läuft, startet ihn neu (R-0246)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js, scripts/tests/desktop_e2e_tunnel.sh
Änderung: Seit #102 (T7) stoppt `onEnroll` in den Einstellungen einen laufenden Tunnel, bevor es ihn startet. Sonst
scheitert der Start neben dem frpc, der nach einem Zurücksetzen mit der alten Identität weiterläuft („frpc laeuft
bereits“). Das prüft heute nur der Komponententest. Die Live-E2E setzt die Identität vor dem Login zurück, dort läuft
noch kein frpc.

Der Plan folgt der Empfehlung zu offener Frage 1, Weg (a): ein dritter Schritt (`it`) in `settings-enroll.live.js`.
- Der Endzustand des zweiten Schritts ist genau der Startzustand dieser Journey: angemeldet, Identität aus den
  Einstellungen, Tunnel `connected`.
- Es braucht keinen zweiten App-Start, keinen zweiten Login und keinen zweiten `wdio`-Lauf samt Build.

Der Schritt:
1. Über die Bridge `tunnel_status` lesen: `running` ist `true`, `connected_since` merken (A).
2. Über die Bridge `reset_device_identity` aufrufen, nicht über den nativen Bestätigungsdialog. frpc läuft dabei
   weiter, genau der Fall von T7.
3. Die Einstellungen schließen und neu öffnen. Beim Öffnen liest der Dialog `isDeviceEnrolled` neu, also erscheint
   das Token-Feld.
4. Mit dem dritten Token registrieren; danach erscheint das Zurücksetzen.
5. Bis `tunnel_status` wieder `running` meldet und `connected_since` nicht mehr A ist, also ein neuer frpc läuft, und
   die Anzeige `connected` zeigt.

Die Anzeige allein beweist nichts: Ohne T7 stünde sie vom zweiten Schritt her womöglich noch auf `connected`. Der alte
frpc behält aber sein `connected_since` (`start_frpc` setzt es bei jedem Start neu, `frpc.rs:308`).

`desktop_e2e_tunnel.sh` mintet den dritten Token zusammen mit dem zweiten direkt vor dem Lauf und reicht ihn als
`AH_SETTINGS_REENROLL_TOKEN` durch (`:78-87`). Fehlt er, bricht die Spec gleich am Anfang mit einer klaren Meldung ab,
wie heute beim zweiten.
Beweis: origin/main@af77eb3c:
- `sed -n 16,35p apps/desktop/e2e/test/specs/settings-enroll.live.js` setzt die Identität vor dem Login zurück; ein
  laufender frpc kommt in keinem Schritt vor.
- Die Reihenfolge „stop vor start“ prüft nur `SettingsModal.enroll.test.ts` („after success shows the reset and the
  message, and starts the tunnel“, `stop` vor `startIfServerMode`).
HEAD: af77eb3c
Semantik: `docs/admin/benutzer.html:97`: „Ist mTLS nicht erzwungen und der Nutzer schon angemeldet, registriert er
das Gerät ohne Abmelden: in den Einstellungen (Modus Server) den Token eingeben → Gerät registrieren. Danach startet der
Tunnel mit dem neuen Zertifikat.“ `docs/admin/troubleshooting.html:73` nennt nach dem Zurücksetzen das Registrieren
„angemeldet, in den Einstellungen“.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict (Lint; der echte Lauf ist die Heavy-Zeile)
Doku: keine (Test)
