# Eingebettetes RDP: Live-Spec erwartet die falsche feste Größe (kern-rdp-7)

Roadmap: R-1205 (REG aus dem Sammellauf 2026-11-09, vor dem Release 0.47.0, R-1110).

## Problem / Motivation
Der Sammellauf vom 2026-11-09 (`main@d5092bc55`) ist im Schritt `desktop_e2e_connect` rot: die Live-Spec
`apps/desktop/e2e/test/specs/rdp-embedded.live.js` wartet nach `chooseWindowMode('custom')` auf eine Fußzeile mit
1280x720 und sieht 1920x1080 („the fixed desktop never had 1280x720“). Auf der Box der Lane ist der Fehler dreimal
gleich rot (`desktop_e2e_connect: 16 passed, 1 failed`).

Ursache ist die Annahme des Tests, nicht die App. Die Spec speichert am Anfang den Einstellungsdialog
(`chooseAdminHelperForRdp`, um den eingebetteten Client zu wählen). Das Feld „eigene Größe“ des Dialogs startet ohne
gespeicherten Wert mit `1920x1080` (`SettingsDialog.svelte:63`), und `onSave` schreibt es mit. Die Sitzung nimmt im
Modus `custom` dann `rdpCustomSize` = 1920x1080 (`RdpSession.svelte:168`) und meldet sie korrekt an den Server; das
xrdp-Log des Sammellaufs zeigt genau diesen Aufbau. Den Rückfall 1280x720 (`FIXED_DEFAULT`, `display.ts:18`) nimmt
die Sitzung nur, wenn gar kein Wert gespeichert ist. Der Kommentar „no custom size seeded“ stimmt also nicht. Der
Prüfteil kam mit 0f33d36a8 und war noch in keinem VM-Lauf grün: eine Regression der App ist es nicht.

## Ziel & Nicht-Ziele
- Ziel: Die Spec erwartet die Größe, die sie selbst über den Dialog gespeichert hat (1920x1080), mit richtigem
  Kommentar; der Schritt `desktop_e2e_connect` ist auf der Box grün.
- Nicht-Ziel: die beiden Vorgaben (Dialog 1920x1080, Sitzung ohne Wert 1280x720) angleichen. Das ist sichtbares
  Verhalten und bleibt eine eigene Roadmap-Zeile für Kevin.

## Betroffene Komponenten & Dateien
- `apps/desktop/e2e/test/specs/rdp-embedded.live.js` (Erwartung und Kommentar im Prüfteil zur festen Größe).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine Änderung; xrdp bleibt der Gegenpart der Live-Spec.

## Trade-offs & Alternativen
- **Erwartung auf 1920x1080 (gewählt):** prüft genau, was der Nutzer nach einmaligem Speichern des Dialogs bekommt.
  Ändert Kevin die Vorgabe des Dialogs, zieht die Spec mit.
- Die eigene Größe in `chooseAdminHelperForRdp` ausdrücklich auf 1280x720 setzen: das Feld erscheint erst im Modus
  `custom` des Dialogs, die Spec müsste dafür den Fenstermodus der Vorgaben umstellen und damit mehr ändern, als der
  Fund verlangt.
- App-Vorgaben angleichen: Verhaltensänderung, Kevins Entscheidung (eigene Zeile).

## Risiken & Rollback
Nur Testcode. Rollback ist der Revert des Task-Commits. Bei 1920x1080 ist der feste Desktop größer als der Tab der
Box; die Zeigerprobe bei (400, 300) liegt bei 1:1 und 50 % weiter im sichtbaren Teil, das belegt der Box-Lauf.

## Doku-Impact
Keine: kein dokumentiertes Verhalten ändert sich; CHANGELOG nicht nötig (nur Test).

## Offene Fragen
Keine für dieses Vorhaben. Die Angleichung der Vorgaben geht als eigene Zeile (`neu`) an Kevin.
