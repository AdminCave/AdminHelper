# Eingebettetes RDP: Auflösung einmal, OpenH264-Restfenster, Live-Test nach dem Resize (kern-rdp-10)

Roadmap: R-1198, R-1278, R-1283 (R-1198 und R-1283 vor dem Release 0.47.0, R-1110).

## Problem / Motivation

- **R-1198:** `rdp_session_start` (`apps/desktop/src-tauri/src/rdp_embedded/mod.rs:496-500`) ruft für
  `session_info` ein zweites Mal `resolve_connection` auf, obwohl `prepare` (`mod.rs:301`) die Verbindung schon
  aufgelöst hat. Beide Aufrufe sehen dieselben Eingaben, doch die Info beschreibt nur dann sicher den Weg der
  Sitzung, wenn sie aus derselben Auflösung stammt.
- **R-1278:** `h264_library` (`mod.rs:543`) liest erst die Einstellung `rdp_h264` und ruft dann
  `openh264::ensure`. `ensure_on` (`openh264.rs:158`) merkt sich den Zähler `removals` erst vor dem Download.
  Schaltet der Nutzer H.264 zwischen dem Lesen der Einstellung und diesem Zeitpunkt aus, löscht `remove` den
  Ordner, der Zähler danach ist schon der neue, und der Download legt die Bibliothek wieder an. Die Doku sagt
  dagegen: Aus löscht die Bibliothek.
- **R-1283:** Der CI-Job „Desktop (embedded RDP vs xrdp)“ war auf PR #438 einmal rot (Lauf 42796178873, Job
  129761820879), derselbe Job auf main@8dd290b61 grün. `xrdp_live_session` scheitert in der Resize-Phase
  (`session.rs`, „expected a picture, got … ResetWithoutClosingHandshake“): Die Sitzung endet, der Bild-WebSocket
  geht ohne Close-Frame zu. Das xrdp-Log zeigt den Ablauf: Nach dem Resize auf 1024×768 macht xrdp ein
  Deactivate/Reactivate („Core reset done“), legt den EGFX-Kanal neu an, und direkt danach schließt der Client die
  TLS-Verbindung („SSL_read … unexpected eof“). Das „SSL_accept … certificate unknown“ im selben Log gehört zur
  ersten Verbindung des Tests, die den unbekannten Schlüssel absichtlich ablehnt; es ist nicht die Ursache.
  Warum der Client nach dem Reactivate abbricht, zeigt der Lauf nicht: Der Test hat keinen Logger, und die
  Phasen nach dem Abbruch liest er nicht mehr.

## Ziel & Nicht-Ziele

Ziel:
- `prepare` gibt die Auflösung mit zurück; `session_info` nutzt genau sie. Kein zweiter Aufruf von
  `resolve_connection` im Start einer Sitzung.
- Der Zähler gilt ab dem Lesen der Einstellung: Ein `remove` danach verhindert jedes Schreiben dieses Starts.
- Der Live-Test übersteht das Resize gegen xrdp verlässlich. Scheitert er künftig, nennt seine Ausgabe den Grund
  (Log der Sitzung und die gemeldete Phase), nicht nur den geschlossenen WebSocket.

Nicht-Ziele:
- den Job `rdp-embedded` zum Pflicht-Check machen: Das Ruleset ändert Kevin, nach diesem Fix.
- den Resize-Weg von IronRDP umbauen, soweit die Ursache nicht dort liegt.

## Betroffene Komponenten & Dateien

- **desktop-rs:**
  - `apps/desktop/src-tauri/src/rdp_embedded/mod.rs`: `prepare` liefert `Target` und `ResolvedConnection`,
    `rdp_session_start` reicht die Auflösung an `session_info`; die Tests von `prepare` folgen der neuen Rückgabe.
    `h264_library` hält den Zähler vor dem Lesen der Einstellung fest.
  - `apps/desktop/src-tauri/src/rdp_embedded/openh264.rs`: `ensure` nimmt den festgehaltenen Zähler entgegen
    (eine Marke), `ensure_on` nutzt ihn statt eines eigenen Lesens. Test: ein `remove` zwischen Marke und
    `ensure` hinterlässt keinen Ordner.
  - `apps/desktop/src-tauri/src/rdp_embedded/session.rs`: der Live-Test (Logger, Phase beim Abbruch) und der Fix
    der Ursache von R-1283. Liegt die Ursache im Fork `AdminCave/IronRDP`, braucht es einen Fork-Commit und eine
    neue `rev` in `Cargo.toml`/`Cargo.lock`; das entscheidet die Session nach der Diagnose und hält es unter
    `## Entscheidungen` fest.

## Datenmodell / API / Migrationen

Keine. Kein Tauri-Command ändert Namen, Argumente oder Rückgabe.

## Externe Integrationen

IronRDP (Fork `AdminCave/IronRDP`, `Cargo.toml:93`) und xrdp (Container `scripts/tests/xrdp-gfx`). Der Ablauf
Deactivate/Reactivate steht in MS-RDPBCGR 1.3.1.3; das Neuanlegen des EGFX-Kanals danach in MS-RDPEGFX.

## Trade-offs & Alternativen

- R-1198: `prepare` gibt eine Struktur aus beiden zurück statt eines Tupels; die Tests lesen `target` daraus.
  Alternative: `ResolvedConnection` in `Target` ablegen. Verworfen, `Target` geht an den Sitzungs-Thread, die
  Auflösung braucht nur der Start.
- R-1278: Die Marke kommt aus `openh264` (`pub(crate) fn mark(base) -> u64`), damit der Zähler privat bleibt.
- R-1283: erst lokal reproduzieren (frischer xrdp-Container je Lauf, Logger im Test), dann die Ursache beheben.
  Ein Retry im Test wäre ein Abschwächen und kommt nicht in Frage.

## Risiken & Rollback

- R-1283 kann im Fork liegen; dann wächst die Task um einen Fork-Commit. Lässt sich die Ursache in zwei Versuchen
  nicht beheben, wird die Task verworfen und wandert in den nächsten Zug; der Logger im Test bleibt dann als
  eigener Schritt, damit der nächste rote Lauf den Grund zeigt.
- Rollback je Task per `git revert`.

## Doku-Impact

Keine: R-1198 ist intern, R-1278 stellt das dokumentierte Verhalten her, R-1283 betrifft Test und gegebenenfalls
einen dokumentierten Ablauf nicht. Ändert der Fix von R-1283 das Verhalten beim Resize sichtbar, zieht die Task
`docs/developer/desktop.html` (DE+EN, Abschnitt Sitzung) nach. CHANGELOG: `changelog.d/kern-rdp-10.md` für
R-1278 und R-1283.

## Offene Fragen

Keine aus Kevins Bereich.
