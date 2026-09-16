<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `scripts/vm/tests` — Fixtures und ihre Herkunft

`test_vm.py` fährt `vm.py` hermetisch: kein Netz, keine VM, kein Proxmox. Jede Antwort,
die der echte Hypervisor liefern würde, liegt als Datei in `fixtures/` — **aufgezeichnet**,
nicht erfunden. Das ist der Unterschied zwischen „der Test prüft, was die API tut" und
„der Test prüft, was wir glauben, dass sie tut".

## Herkunft

Aufgezeichnet am 2026-09-16 gegen Proxmox VE **9.2.3** (`pve-manager/9.2.3`, Kernel 7.0.12-1-pve)
mit dem Token aus `.claude/settings.local.json`, im Pool `adminhelper-ci`. Die mutierenden
Antworten stammen aus drei Wegwerf-Klonen des Fat-Templates 9402 (VMIDs 3000/3001), die im
selben Lauf wieder zerstört wurden; danach war `/cluster/resources` wieder leer bis auf die
drei Templates. Das Aufzeichnungsskript lag im Scratchpad und ist **nicht** committet — eine
Neuaufnahme schreibt man neu, statt ein Skript zu pflegen, das einmal im Jahr läuft.

## Format

Eine Datei je Antwort, `{"status": <HTTP-Code>, "body": <JSON oder Text>}`. Der Body ist
JSON, wo Proxmox JSON liefert (`{"data": …}`), und ein **String**, wo es keins liefert:
Fehlerkörper kommen als roher Text zurück (`err_delete_body.json` ist nicht einmal JSON) —
genau der Fall, an dem ein naives `json.loads` in `vm.py` stirbt.

## Wenn ein Test eine Antwort braucht, die es noch nicht gibt

`conftest.tagged_resources()` legt auf die aufgezeichnete `/cluster/resources`-Antwort eine
benannte Änderung — die Template-Tags, die T8 erst setzt, und das `linux-server`-Template, das
T12 erst backt. Das ist der einzige erlaubte Weg, eine Zukunft zu testen: die Änderung steht
sichtbar im `conftest`, nicht in einer Datei, die so tut, als sei sie aufgezeichnet.

## Bereinigungsregel

Ersetzt wurden Hostname (`<node>`), IPv4/IPv6 (`<ip>`, `<ipv6-ll>`; `127.0.0.1` bleibt, weil
der IP-Filter genau daran hängt), MACs (`<mac>`), Token-/Benutzer-Identitäten
(`<user>@pve!<tokenid>`), UUIDs, Config-Digests, SSH-Public-Keys, die crabbox-Lease-Ids in der
Template-**Beschreibung** und der Hardware-Fingerabdruck des Knotens (CPU-Modell, Taktrate und
Flag-Liste in `node_status.json`; der Kapazitäts-Check liest davon nur `memory.*`). Stehen
geblieben sind zwei Dinge, die wie ein Rest aussehen und keiner sind: die Build-Id der
PVE-Version (`repoid`, auf jeder 9.2.3-Installation dieselbe, und `node_status.json` trägt sie
ohnehin im `pveversion`-String) und das Lease-Fragment im Template-**Namen**
(`Copy-of-VM-crabbox-ah-bake-9482bd41`) — der Name ist echter Bestandteil der Template-Auflösung
und wird von den Tests gelesen. **VMIDs bleiben unverändert** — sie sind keine Homelab-Geheimnisse,
und die Tests prüfen VMID-Wahl und Lock-Dateinamen (`lock-3001.conf`) gegen genau diese Zahlen.
Wer neu aufzeichnet, prüft das Ergebnis mit
`grep -rEn '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|PVEAPIToken=' fixtures/` (nur `127.0.0.1` darf stehen).

## Was die Aufnahme über die API gezeigt hat

- **Linked Clone**: `POST clone` mit `full=0` → Task `OK` in ~2 s. Snapshot 2–3 s, Rollback ~1 s.
- **Lock-Kollision ist kein HTTP-Fehler.** Nach `rollback --start` gibt der nächste Aufruf
  brav einen UPID mit 200 zurück; der **Task** endet dann mit
  `exitstatus: can't lock file '/var/lock/qemu-server/lock-3001.conf' - got timeout`
  (`task_lock_timeout.json`). Ein Retry nur auf HTTP-Ebene würde das nie sehen.
  Der zweite Fall ist `err_vm_locked.json`: `PUT config` während des Rollbacks → HTTP 500
  `VM is locked (rollback)`.
- **Der Guest-Agent hat zwei Nein.** `agent_ping_not_running.json` (`VM ... is not running`,
  direkt nach `status/start`) und `agent_ping_no_agent.json` (`QEMU guest agent is not running`,
  VM läuft, Agent noch nicht) — beide HTTP **500**, nicht 503. Agent oben nach 48–64 s.
- **`DELETE` verträgt keinen Body**: 501 `Unexpected content for method 'DELETE'`
  (`err_delete_body.json`) — Parameter müssen in den Query-String.
- **Fremde VM** → 403 `Permission check failed (/vms/100, VM.Audit)`; die VM ist für das
  Token nicht einmal sichtbar, es gibt also keinen Informationsabfluss.
- **Belegte VMID** → 500 `unable to create VM 3000: config file already exists`.
- **Tags kommen alphabetisch sortiert zurück** (`ah;lane-main;role-probe;sc-none;tpl-…;ttl-…`),
  nicht in der Reihenfolge des `PUT` — als Menge lesen.
- **Die Cluster-Ressourcen sind ein Cache und hinken — Namen lügen, Tags nicht.** VMID 3001
  war in derselben Aufnahme schon einmal vergeben; `/cluster/resources` **und** `/pools/<pool>`
  gaben beide noch den Namen des Vorgängers zurück (`ah-probe-main-c3d4`), während die `tags`
  derselben Antwort bereits aktuell waren (`lane-pilot;role-server;sc-capstone`). Der Widerspruch
  steht so im Fixture, weil er der Grund ist, warum `list`, `destroy --role/--lane` und `reap`
  ihre Auswahl **aus den Tags** treffen und nie aus dem Namen. Frischen Zustand einer einzelnen
  VM liefert `status/current` (`status_current_*.json`), nicht die Ressourcenliste.
- **`/pools/<pool>` liefert keine Tags** (`pool.json`), `/cluster/resources` schon. Template-
  Auflösung „neuestes `built-` zum Profil-Tag" muss deshalb über `/cluster/resources` laufen,
  auch wenn „im Pool" nach der Pool-Abfrage klingt.
- **Die Clone-Task läuft auf der QUELL-VMID.** `clone_post.json`/`task_ok.json` tragen
  `qmclone:9402` — die 9402 ist das Template, nicht der neue Klon. Wer einen Task über die
  `newid` wiederfinden will, sucht vergeblich; der UPID ist der einzige Handgriff.
