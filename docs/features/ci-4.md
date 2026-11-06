# ci-4 — cosign 3 für die Image-Signaturen

Roadmap: R-1119 (Zug `tasks/ci-4.md`). R-1134, R-1136 und R-1137 aus demselben Zug sind am 2026-11-06 nach
`tasks/ci-6.md` gewandert: sie ändern `.github/workflows/ci.yml`, das `feature/kern-rdp-2` (#408) ebenfalls ändert.

## Problem / Motivation

`docker.yml` installiert cosign über `sigstore/cosign-installer` v3.9.2 (`.github/workflows/docker.yml:83` und `:140`).
Diese Version installiert cosign 2. Kevin hat am 2026-11-04 entschieden, auf cosign 3 umzusteigen (installer v4,
neues Bundle-Format). Aktuell ist cosign-installer v4.1.3 vom 2026-11-04; er installiert cosign v3.1.4.

## Ziel & Nicht-Ziele

Ziele:
- Beide Jobs in `docker.yml` (`build` und `latest`) nutzen cosign-installer v4.1.3, gepinnt auf den Commit des Tags.
- Der Job `build` prüft seine frische Signatur gleich nach dem Signieren mit `cosign verify` gegen die
  Workflow-Identität dieses Laufs. So beweist jeder Push auf `main` das neue Format von Anfang bis Ende, nicht erst der
  Job `latest` beim nächsten stabilen Release.

Nicht-Ziele:
- Keine Signatur für Release-Assets mit cosign. Dort bleibt minisign.
- Kein erneutes Signieren alter Images.
- Keine Änderung an `ci.yml`. Das bleibt im Zug ci-6.

## Betroffene Komponenten & Dateien

- `.github/workflows/docker.yml`:
  - die Schritte „Install cosign“ in `build` und `latest`
  - der Schritt „Sign the image (keyless)“ mit Kommentar und neuem Verify
- `docs/developer/cicd.html` und `docs/en/developer/cicd.html`, Abschnitt Signaturen (Zeilen 529–532 bzw. 519–522):
  - der Prüfbefehl
  - der Hinweis, dass cosign ab 3 nötig ist bzw. ab 2.6 mit `--new-bundle-format`
- `changelog.d/ci-4.md`.

## Datenmodell / API / Migrationen

Es gibt keine Datenmodell- oder API-Änderungen. Das sichtbare Artefakt ändert sich aber: Die Signatur eines Images
liegt ab dem ersten Push nach dem Merge als Sigstore-Bundle in einem OCI-1.1-Referrer. Bisher lag sie als
`sha256-<digest>.sig`-Tag vor.

## Externe Integrationen

Quellen:
- cosign CHANGELOG v3.0.0 (github.com/sigstore/cosign, CHANGELOG.md):
  > „all of the new capabilities of recent releases **on by default** … standardized bundle format … container
  > signatures stored as an OCI Image 1.1 referring artifact“
- Sigstore-Blog „Cosign 3.0 available“: Das alte Verhalten bleibt über Flags abschaltbar, cosign 4 entfernt es.
- cosign-installer README und Releases: v4.1.3 installiert cosign v3.1.4. Der Tag zeigt auf den Commit
  `756fe2d284c7292c4e9b62c8a28f1e5629c59532`.

## Trade-offs & Alternativen

- **cosign 3 mit Standardwerten** (empfohlen, Kevins Wahl vom 2026-11-04): Das ist das Format, auf das Sigstore
  umstellt.
  - Nachteil: Wer ein neues Image prüfen will, braucht cosign 3 oder cosign ≥ 2.6 mit `--new-bundle-format`.
- **cosign 3 mit `--new-bundle-format=false`**: Damit bliebe das alte Format, aber nur bis cosign 4. Das verschiebt das
  Problem nur und widerspricht Kevins Entscheidung.
- **Verify-Schritt im Job `build`**: Er kostet Sekunden je Image und macht ein kaputtes Signieren sofort sichtbar.
  - Alternative ohne ihn: Ein Fehler zeigt sich erst im Job `latest` am Release-Tag. Dann bliebe `latest` stehen.

## Risiken & Rollback

**Signaturen auf ghcr:**
- Kann ghcr den Referrer nicht aufnehmen, scheitert das Signieren. Der neue Verify-Schritt fängt das.
- Bisher nicht verifiziert ist, ob ghcr die Referrers-API anbietet. Laut CHANGELOG fällt cosign sonst auf das
  Referrers-Tag-Schema zurück. Belegt wird das erst durch den ersten Lauf auf `main` nach dem Merge.

**Prüfen durch Nutzer:**
- Wer neue Images mit cosign < 2.6 prüft, scheitert. Die Doku nennt deshalb die Mindestversion.
- Ob cosign 3 die alten Signaturen bis v0.46.0 weiter prüft, klärt T2 mit einem lokalen Lauf gegen ein
  veröffentlichtes Image. Das Ergebnis kommt in die Doku.

**Job `latest`:** GitHub fährt die `docker.yml` des getaggten Commits. Releases vor dem Merge prüfen also weiter mit
cosign 2, Releases danach mit cosign 3. Signieren und Prüfen passen damit je Tag zueinander.

**Prüfbarkeit vor dem Merge:**
- Ein Lauf von `docker.yml` auf dem Branch würde Images nach ghcr pushen, also veröffentlichen. Er entfällt.
- Den Merge macht Kevin, weil die Änderung unter `.github/workflows/` liegt.
- Danach beobachtet die Session den Lauf von `docker.yml` auf `main`.

**Rollback:** Revert des Merge-Commits. Bereits mit cosign 3 signierte Images bleiben so signiert, cosign 3 prüft sie
weiter.

## Doku-Impact

`docs/developer/cicd.html` DE und EN, Abschnitt Signaturen:
- Prüfbefehl und Mindestversion von cosign
- Prüfweg für alte Images, nach dem Ergebnis aus T2

Dazu ein Eintrag in `changelog.d/ci-4.md`.

## Offene Fragen

Keine. Die Version hat Kevin am 2026-11-04 entschieden, den Merge macht er selbst.
