# Eingebettetes RDP: eine Vorgabe für die eigene Größe (kern-rdp-11)

Roadmap: R-1218 (vor dem Release 0.47.0, R-1110).

## Problem / Motivation

- **R-1218:** Die Vorgabe für die eigene Fenstergröße ist uneinheitlich. Der Einstellungsdialog startet mit
  1920x1080 (`models/settings.ts`, `SettingsDialog.svelte`) und speichert diesen Wert mit. Eine Sitzung ohne
  gespeicherten oder mit ungültigem Wert nimmt dagegen 1280x720 (`FIXED_DEFAULT` in `lib/rdp/display.ts`). Wer
  den Dialog nie speichert, bekommt eine andere Größe als jemand, der ihn einmal speichert.

## Ziel & Nicht-Ziele

- Ziel (Kevin 2026-11-10): 1920x1080 gilt überall in der Webview. `FIXED_DEFAULT` wird 1920x1080, die
  Admin-Doku DE+EN nennt 1920&times;1080.
- Nicht-Ziel: die Vorgabe in Rust (`rdp_embedded/session.rs`, `DESKTOP_WIDTH/HEIGHT`) für eine Sitzung, der die
  Webview gar keine Größe schickt. Die Webview schickt immer eine. Die Kommentare dazu stehen in
  `rdp_embedded/mod.rs`, `lib/bridge/index.ts` und `docs/*/developer/desktop.html`; diese Dateien ändern gerade
  `feature/arch-namen` und `feature/arch-monitoring-ui`.

## Betroffene Komponenten & Dateien

- **desktop-ui:** `apps/desktop/ui/src/lib/rdp/display.ts` (`FIXED_DEFAULT`, Doc-Kommentar von `parseSize`),
  `apps/desktop/ui/src/lib/rdp/display.test.ts`.
- **Doku:** `docs/admin/index.html`, `docs/en/admin/index.html` (Satz zu *Benutzerdefiniert*),
  `changelog.d/kern-rdp-11.md`.

## Datenmodell / API / Migrationen

Keine. Gespeicherte Werte bleiben unverändert; nur der Ersatz für einen fehlenden oder ungültigen Wert ändert sich.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- 1280x720 überall: kleinere Sitzung, passt auf jeden Bildschirm. Kevin hat 1920x1080 gewählt.

## Risiken & Rollback

Eine Sitzung ohne gespeicherte Größe startet größer. Auf einem kleinen Bildschirm zoomt der Nutzer (*Einpassen*).
Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/admin/index.html` und `docs/en/admin/index.html`: „sonst 1280&times;720“ wird „sonst 1920&times;1080“.
CHANGELOG über `changelog.d/kern-rdp-11.md`.

## Offene Fragen

Keine.
