<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Lesegrenze für das Visitor-Bundle, Keyring beim Zurücksetzen, Rollback-Meldung, Launcher-Test

Zug `kern-desktop-3` (Roadmap R-0962, R-0961, R-0984, R-0981). Stand des Codes: `origin/main@2eac9b1d`. Pfade ohne
Präfix liegen unter `apps/desktop/src-tauri/src/`.

## Problem / Motivation

1. **Visitor-Bundle (R-0962).** `bundle_from` (`frpc.rs:268`) liest die Antwort mit `response.json()` (`:278`) ohne
   Obergrenze. Die Verbindungsliste (`sync.rs:43-48`, `read_list`) und die Playbook-Antwort (`ansible.rs:66`) lesen
   höchstens 16 MiB. Einzelheiten privat.
2. **Zurücksetzen auf dem async-Worker (R-0961).** `reset_identity` (`enrollment.rs:502`) liest den Fingerabdruck
   (`leaf_fingerprint`, `:391`), löscht die Identität (`clear_identity`, `:584`) und merkt den Fingerabdruck
   (`KEYRING_REPLACES`) im Keyring, und zwar direkt auf dem async-Worker. Ein Keyring, der wartet (Secret Service
   gesperrt, Dialog offen), hält damit einen Worker der Tauri-Laufzeit fest. Andere Kommandos legen solche Arbeit
   über `blocking` (`commands.rs:594`) auf einen Blocking-Thread.
3. **Rollback-Meldung (R-0984).** Hält der Workspace die URL einer gerade gelungenen Registrierung nicht
   (`enroll_with_token_in`, `commands.rs:239-243`), setzt er die Identität zurück und verwirft dessen Fehler
   (`let _ = reset(server_url).await`, `:242`). Scheitert auch das Zurücksetzen, sieht der Nutzer nur den ersten Fehler
   und weiß nicht, dass die Identität noch da ist.
4. **Flaky Launcher-Test (R-0981, BUG).** `open_gives_up_on_a_workspace_that_holds_no_lock_in_time`
   (`launcher.rs:2282`) prüft eine feste Obergrenze von 900 ms (`:2305`); der Windows-Runner gab nach 1,95 s auf
   (PR #326, Lauf 40972646852, Diff ohne Rust). Dieselbe Grenze trägt
   `delete_gives_up_on_a_purge_that_does_not_end_in_time` (`:2529`).

## Ziel & Nicht-Ziele

- Ziel: `bundle_from` liest höchstens 16 MiB, prüft zuerst die angegebene Länge, dann den gelesenen Körper, und kein
  Fehler zitiert die Antwort (wie `read_list`).
- Ziel: Fingerabdruck lesen, löschen und merken laufen in `reset_identity` auf einem Blocking-Thread; Reihenfolge und
  Ergebnis (`reset_with`) bleiben.
- Ziel: Scheitert das Zurücksetzen nach einer nicht gehaltenen Registrierung, nennt die Meldung beide Fehler und dass
  die Identität bleibt.
- Ziel: Beide Launcher-Tests prüfen weiter, dass bis zur Frist gewartet und dann aufgegeben wird; die Obergrenze ist
  großzügig und hängt nicht an der Geschwindigkeit des Runners (nur „hängt nicht“).
- Nicht-Ziel: ein gemeinsamer Lese-Helfer für alle drei Antworten (YAGNI; die Session entscheidet beim Bauen, ob
  `read_list` sich ohne Umbau teilen lässt, und schreibt es unter `## Entscheidungen`).
- Nicht-Ziel: andere Keyring-Zugriffe auf async-Workern (nur der Reset-Pfad der Zeile).

## Betroffene Komponenten & Dateien

Desktop-Backend: `frpc.rs` (`bundle_from`), `enrollment.rs` (`reset_identity`), `commands.rs`
(`enroll_with_token_in`), `launcher.rs` (zwei Tests). Keine API-, Schema- oder Migrationsänderung.

## Externe Integrationen

Keine; `reqwest::Response::content_length`/`chunk` wie in `read_list`.

## Trade-offs & Alternativen

- Lesegrenze: dieselben 16 MiB wie Liste und Playbook. Ein Bundle trägt nur TOML für die sichtbaren Tunnel; 16 MiB
  sind weit darüber und halten die Grenzen einheitlich.
- Reset: ein `spawn_blocking` je Keyring-Schritt (die Server-Abfrage bleibt async) statt einer Umstellung von
  `reset_with`; die Tests von `reset_with` bleiben unverändert gültig.

## Risiken & Rollback

Gering; jede Task ist ein eigener Commit und einzeln zurücknehmbar. Die Lesegrenze könnte ein riesiges legitimes
Bundle abweisen (praktisch ausgeschlossen, Meldung nennt die Grenze).

## Doku-Impact

`docs/developer/desktop.html` DE+EN: Lesegrenze beim Visitor-Bundle neben dem Abgleich (`refresh_tunnel`), falls die
Seite die Grenzen der anderen Antworten nennt; sonst keine. CHANGELOG über `changelog.d/kern-desktop-3.md`, neutral.

## Offene Fragen

Keine.
