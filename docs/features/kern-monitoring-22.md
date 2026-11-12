# kern-monitoring-22 — Probe-Ziele: Weiterleitungen, Socket-Pfade, Docker-Erkennung; Meldetext; Testvorlage

Roadmap: R-1319, R-1320, R-1324, R-1321, R-1300, R-1365 · Stand 2026-11-12

## Problem / Motivation

Nachlese zu kern-monitoring-19 und arch-opnsense-plugin. Der Probe-Guard des Agents (`apps/agent/internal/probe/`)
lässt eine Probe nur zu Zielen dieses Hosts und nie zu Diensten, die Fehlversuche bestrafen oder den Host steuern.
Dieser Zug zieht ihn nach:

- **R-1319:** Der Abgleich von Port-Weiterleitungen kennt nur Docker. Weitere Weiterleitungen (rootless Container,
  Kubernetes, Kernel-NAT-Regeln) gleicht er künftig ebenfalls ab.
- **R-1320:** Die Verbindung zu einem Unix-Socket soll genau an die Datei gehen, die der Guard geprüft hat.
- **R-1324:** Die Docker-Erkennung soll nicht nur am Standard-Socket hängen.
- **R-1365:** Nachlese der Sicherheitsprüfung von arch-opnsense-plugin: ein Punkt im Agent (Socket-Abgleich, mit
  R-1320 in einer Task) und drei an der OPNsense-Testvorlage und am VM-Werkzeug (`scripts/vm/`, Harness-Teil auf
  Kevins Wort in der Roadmap-Notiz).
- **R-1321 (BUG):** Der Monitoring-Dienst meldet zu `not_allowed` immer „Target is no address of this host“, auch
  wenn der Agent aus einem anderen Grund ablehnt (Sperrliste, gebundene Zugangsdaten).
- **R-1300 (REF):** Der AST-Test, der Befehlsstarts in `monitor`, `probe` und `discovery` auf die Allowlist
  beschränkt, erkennt nicht jede Form eines Starts.

## Ziel & Nicht-Ziele

Ziel: eine Probe auf eine eigene Host-Adresse verbindet nur, wenn dort ein Prozess lauscht, den der Guard kennt und
zulässt, oder eine abgeglichene Docker-Veröffentlichung den Port trägt; Weiterleiter im Userland ohne erkennbaren
Zielport werden abgelehnt; die Socket-Verbindung geht an die geprüfte Datei; die Docker-Erkennung schließt
geschlossen, sobald ein Docker-Daemon läuft; der Meldetext passt zu jedem Ablehnungsgrund; der AST-Test sieht jede
Startform; die Testvorlage ist nach der Nachlese gehärtet.

Nicht-Ziele: Regelwerke von iptables/nftables/pf lesen (siehe Trade-offs), Weiterleitungen unter Windows, Proxys
auf Anwendungsebene (eigene Roadmap-Zeile), ein neuer Probe-Status.

## Betroffene Komponenten & Dateien

- Agent (Go): `apps/agent/internal/probe/guard.go` (`checkListener` ab Zeile 240, `checkPublished` Zeile 277,
  `socketToDial` Zeile 111, `controlSockets` Zeile 83), `sensor_local.go` (`dockerSocketServes` Zeile 359,
  `dockerPublications` Zeile 255), `sensor_local_linux.go` (`dialUnix` Zeile 137), `sensor_local_freebsd.go`
  (`dialUnix` Zeile 63) + Tests (`guard_test.go`, `sensor_local_linux_test.go`, `sensor_local_freebsd_test.go`);
  `apps/agent/internal/monitor/allowlist_test.go` (`commandStarts` Zeile 54).
- Monitoring (Python): `apps/monitoring/app/checkers/probe.py` (`_NOT_RUN` Zeile 37) + `tests/test_probe_checker.py`.
- Harness: `scripts/vm/vm.py` (`OPNSENSE_CLEAN` Zeile 2034), `scripts/vm/opnsense/bootstrap.sh` + `scripts/vm/tests/test_vm.py`.

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld, kein neuer Status. Der Meldetext zu `not_allowed` ändert sich (sichtbar in der
UI); der Agent liefert den Grund schon heute im Feld `error` mit.

## Externe Integrationen

- Lokal erzeugte Pakete durchlaufen NAT im Hook `output`; ein DNAT dort schreibt das Ziel um, bevor der Kernel einen
  Socket sucht: iptables-extensions(8) (DNAT/REDIRECT „only valid in the nat table, in the PREROUTING and OUTPUT
  chains“, https://ipset.netfilter.org/iptables-extensions.man.html), nftables-Wiki „Netfilter hooks“
  (https://wiki.nftables.org/wiki-nftables/index.php/Netfilter_hooks).
- Kubernetes NodePort im iptables-Modus „reachable on all local IP addresses“
  (https://kubernetes.io/docs/reference/networking/virtual-ips/).
- Linux: Verbindung über einen O_PATH-Deskriptor (`/proc/self/fd/N`); FreeBSD: `connectat(2)` relativ zu einem
  Verzeichnis-Deskriptor. Beides in der Task an man7.org bzw. man.freebsd.org nachlesen.

## Trade-offs & Alternativen

- **Weiterleitungen (advisor 2026-11-12):** Listener-Pflicht statt Regelwerke lesen. Ein Port mit Kernel-NAT hat
  typischerweise keinen eigenen Listener; die Pflicht deckt iptables (legacy und nft), nftables, kube-proxy und pf
  `rdr` ab, ohne ein Regelwerk zu lesen, und kostet nichts (die Listener-Liste liegt im Snapshot). Regelwerke zu
  lesen bräuchte zwei Quellen, versteht `xt`-Ausdrücke nicht und endet bei Sets, Maps und großen Regelwerken doch
  in „ablehnen“. Container-Adressen (`extra`) bleiben ausgenommen.
- Weiterleiter im Userland (rootlesskit, rootlessport, slirp4netns, pasta/passt, kube-proxy, socat) über Namen und
  `argv[0]` ablehnen statt ihren Zielport über eigene APIs zu lesen; wer einen rootless Container messen will,
  probt seine Container-Adresse.
- Docker-Erkennung: ein laufender `dockerd` gilt als „Docker da“, statt `daemon.json`/Kontexte zu lesen.

## Risiken & Rollback

- Listener-Pflicht: eine Probe auf einen Port ohne Listener verbindet nicht mehr; wie sie gemeldet wird, ist die
  offene Frage unten. Ein falsch gelesener Listener-Snapshot würde Proben ablehnen (fail-closed).
- Socket-Dial über Deskriptor: plattformabhängig, Test auf Linux und auf der FreeBSD-Box.
- Testvorlage: wirkt erst beim nächsten Bake der Vorlage.
- Rollback: Revert des Merge-Commits; keine Migration.

## Doku-Impact

`docs/admin/monitoring.html` + EN (Abschnitt zum Probe-Ziel: Listener-Pflicht, Weiterleiter, Meldetext),
`docs/developer/agent.html` + EN (Guard), `changelog.d/kern-monitoring-22.md`; `DEVELOPMENT.md` nur, falls sich
die Bake-Anleitung der Vorlage ändert.

## Offene Fragen

1. Wie meldet der Agent eine Probe auf einen Port ohne Listener (T1)? Empfehlung: wie heute ein abgelehnter
   Verbindungsaufbau (Ergebnis `error`, „no process listens on port N“), nicht `not_allowed`: ein abgestürzter
   Dienst bleibt „down“. Ein Port, den nur eine Weiterleitung trägt, erscheint dann ebenfalls als „down“.
