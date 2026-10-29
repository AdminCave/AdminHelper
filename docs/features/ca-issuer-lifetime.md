<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CA-Issuer: kein Zertifikat überlebt seinen Aussteller, Prüfung der Hierarchie beim Start, Ablaufwarnung

Stand des Codes: `origin/main@237b450a`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/ca-issuer-lifetime.md`. Roadmap R-0666 (BUG). Die Rotation der Intermediates (R-0667) ist ein eigenes
Vorhaben (`docs/features/ca-rotation.md` auf `feature/ca-rotation`) und baut auf diesem auf.

## Problem / Motivation

Die PKI des `ca-issuer` ist zweistufig: Root 10 Jahre, drei Intermediates (`tunnel`, `access`, `internal`) 5 Jahre,
alle beim ersten Start erzeugt (`apps/ca-issuer/app/pki.py:35-36`, `apps/ca-issuer/app/storage.py:121-130`).

1. **Ein Leaf überlebt seinen Aussteller.** `sign_leaf` setzt `not_valid_after` auf `now + lifetime_days`
   (`apps/ca-issuer/app/pki.py:245`, `:253`), ohne das `notAfter` des Intermediates zu beachten; dasselbe gilt für das
   Server-Leaf von Gateway und frps (`build_server_leaf`, `:284-307`, 365 Tage) und für ein Intermediate unter der
   Root (`build_intermediate_ca`, `:157`, `:165`). `CertificateBuilder.sign` prüft das nicht (cryptography 50.0.1,
   Doku `https://cryptography.io/en/latest/x509/reference/`: „Sign the certificate using the CA's private key.“ —
   keine Prüfung der Gültigkeit des Ausstellers beschrieben). Beleg (Probe an `origin/main@237b450a`, dreimal
   identisch, gleiche md5 der Ausgabe): ein `tunnel`-Intermediate mit 5 Tagen Restlaufzeit (`notAfter` 2026-10-27)
   signiert ein 90-Tage-Leaf mit `notAfter` 2027-01-20.
2. **`ensure_hierarchy` lädt ohne jede Prüfung.** Die Ladeschleife (`apps/ca-issuer/app/storage.py:132-137`) liest
   Zertifikat, Schlüssel und Kette je Scope und gibt sie zurück: kein Blick auf die Gültigkeit, nicht ob das
   Intermediate von `root.crt` stammt, nicht ob Schlüssel und Zertifikat zusammenpassen, nicht ob
   `<scope>-chain.pem` zu beiden passt. Beleg (dieselbe Probe): ein abgelaufenes `tunnel`-Intermediate auf der Platte
   wird ohne Ausnahme geladen. Ab dem fünften Jahr signiert der Issuer damit still Leaves, die kein Client mehr
   akzeptiert (nginx, Go und rustls prüfen die Gültigkeit jedes Kettenglieds).
3. **Kein Ablauf-Monitoring.** Niemand prüft das Ablaufdatum der Intermediates oder der Root: der `ca-issuer` loggt
   beim Start nur „PKI erzeugt“ bzw. nichts (`storage.py:121`, `:130`), `/healthz` antwortet immer `{"status": "ok"}`
   (`apps/ca-issuer/app/main.py:124-126`), und weder Monitoring noch Skripte kennen die Daten. Die bestehenden
   Ablaufprüfungen betreffen nur Leaves (Re-Mint der Server-Leaves `storage.py:42-56`, frps-Supervisor
   `apps/frps/frps-supervisor.sh`, Agent `apps/agent/internal/enroll/renew.go:18-21`).

## Ziel & Nicht-Ziele

Ziel:
- Kein Zertifikat, das der Issuer ausstellt, gilt länger als sein Aussteller: Leaf ≤ Intermediate, Intermediate ≤
  Root. Ist der Aussteller abgelaufen oder noch nicht gültig, signiert der Issuer nicht.
- `/enroll` und `/renew` antworten in diesem Fall mit HTTP 503 und einer klaren Meldung; der Einmal-Token bleibt
  unverbraucht. Der Issuer loggt den Fall auf ERROR.
- Beim Start prüft `ensure_hierarchy` die geladene Hierarchie: Root selbstsigniert und zeitlich gültig; je Scope
  Intermediate von der Root signiert, zeitlich gültig, Schlüssel passt zum Zertifikat, Kette = Intermediate + Root.
  Jeder Verstoß bricht den Start mit `RuntimeError` und einer Meldung ab, die Datei, Scope und Grund nennt (wie der
  bestehende Abbruch bei einem unvollständigen PKI-Verzeichnis, `storage.py:105-116`).
- Läuft die Root oder ein Intermediate in weniger als `EXPIRY_WARN_DAYS = 180` Tagen ab, loggt der Issuer eine
  WARNING mit Name und Datum: beim Start, und beim Signieren höchstens einmal je Scope und UTC-Tag.
- Ein Leaf, das wegen der Begrenzung kürzer ausfiel, vererbt seine kurze Laufzeit nicht an seine Erneuerung.

Nicht-Ziele (YAGNI):
- Keine Rotation der Intermediates (R-0667, eigenes Vorhaben); die Meldungen hier nennen noch keinen Befehl.
- Keine Änderung an `/healthz` und am Healthcheck in `docker-compose.yml` (Empfehlung, offene Frage 1).
- Kein Ablauf-Monitoring in der Server-UI oder im Monitoring-Dienst: der Server erreicht den Issuer nicht (Netz
  `pki`, `docker-compose.yml:266-269`), eine Anzeige bräuchte eine neue Tabelle oder Route (offene Frage 3).
- Keine Root-Erneuerung; die Root-Warnung sagt nur, dass sie abläuft.
- Keine Änderung an Clients (Agent, Desktop): sie sehen nur kürzere Leaves kurz vor dem Ablauf eines Intermediates
  und erneuern wie bisher bei der Hälfte der Laufzeit (`renew.go:18-21`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | ca-issuer | `apps/ca-issuer/app/pki.py`, `apps/ca-issuer/tests/test_pki.py` |
| T2 | ca-issuer | `apps/ca-issuer/app/issuer.py`, `apps/ca-issuer/app/main.py`, `apps/ca-issuer/tests/test_enroll_renew.py`, `CHANGELOG.md` |
| T3 | ca-issuer | `apps/ca-issuer/app/storage.py`, `apps/ca-issuer/tests/test_storage.py`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |

`apps/ca-issuer` ist PKI und steht auf der Risikoliste (`scripts/dev/review-risk.txt`): jede Task bekommt zusätzlich
`security`.

## Datenmodell / API / Migrationen

Keine Migration, keine neue Route, kein neues Feld. `/enroll` und `/renew` (intern, nur vom Gateway erreichbar)
bekommen einen neuen Fehlerfall: HTTP 503 mit `detail`, wenn das signierende Intermediate abgelaufen oder noch nicht
gültig ist. Das OpenAPI-Schema des Issuers ändert sich nicht (FastAPI listet `HTTPException`-Codes nicht).
Clients behandeln jeden Nicht-2xx-Status gleich: der Agent loggt den Fehler und versucht es im nächsten Zyklus
(`apps/agent/internal/enroll/renew.go:99-115`), der Desktop zeigt den Fehler an. `/healthz` bleibt unverändert.
Kein Vertrags-Drift zu Server, Web, Desktop oder Agent.

## Externe Integrationen

- cryptography 50.0.1 (`apps/ca-issuer/requirements.txt:111`), Doku `https://cryptography.io/en/latest/x509/reference/`
  (gelesen 2026-10-22): `not_valid_after_utc` — „A timezone-aware datetime representing the end of the validity period
  for the certificate in UTC. This value is inclusive.“; `verify_directly_issued_by` — prüft Namen und Signatur,
  „No other validation is performed.“, wirft `ValueError` (Name passt nicht), `TypeError` (Schlüsseltyp) oder
  `InvalidSignature`; die Gültigkeitszeiten prüft der Aufrufer selbst. `CertificateBuilder.not_valid_after` nimmt
  ein `datetime` in UTC.
- Clients prüfen die Gültigkeit jedes Kettenglieds (Go `crypto/x509`, rustls/webpki, OpenSSL in nginx): ein Leaf,
  das sein Intermediate überlebt, ist nach dessen Ablauf ohnehin ungültig. Die Begrenzung macht das sichtbar, statt
  ein längeres Datum zu versprechen.

## Trade-offs & Alternativen

1. **Abgelaufenes Intermediate beim Start (T3).** (a) Start bricht ab (`RuntimeError`) — **Empfehlung**: wie der
   bestehende Abbruch bei einer kaputten Hierarchie (`storage.py:105-116`), der Issuer signiert nie mit einem
   ungültigen Intermediate, und die Meldung steht ganz oben im Log. (b) Start im eingeschränkten Betrieb (Signieren
   verweigert, `/healthz` 503): mehr Code (Provisionierung von Gateway und frps müsste das abgelaufene Intermediate
   überspringen), und der Zustand wäre derselbe — mit abgelaufenen Intermediates lehnen Gateway und frps die Clients
   ohnehin ab. Der Rotationsbefehl aus R-0667 muss deshalb auch ohne laufenden Issuer gehen (dort eingeplant).
2. **Warnschwelle `EXPIRY_WARN_DAYS = 180`.** Ein halbes Jahr Vorlauf; das Rotieren ist ein kurzer Eingriff, braucht
   aber die getrennt aufbewahrte Passphrase. 365 Tage (ab da werden Browser-Zertifikate gekürzt) hieße ein Jahr
   tägliche Warnungen; 90 Tage ließe bei seltenen Updates wenig Vorlauf. Eine Konstante in `pki.py`, kein
   Konfigurationsknopf (YAGNI).
3. **Wann gewarnt wird.** Beim Start (T3) und beim Signieren höchstens einmal je Scope und UTC-Tag (T2): ein Issuer,
   der monatelang ohne Neustart läuft, warnt so trotzdem regelmäßig, und Erneuerungen laufen laufend. Ein eigener
   Timer im Issuer wäre neue Infrastruktur.
4. **Laufzeit einer Erneuerung (T2).** Heute erbt ein erneuertes Leaf `min(Spanne des alten, Policy der Zielgruppe)`
   (`apps/ca-issuer/app/issuer.py:160-170`). Mit der Begrenzung aus T1 hätte ein Leaf, das 30 Tage vor dem Ablauf
   seines Intermediates ausgestellt wurde, 30 Tage Spanne und alle Nachfolger ebenso, auch nach einer Rotation.
   Empfehlung: die Erneuerung bekommt die volle Policy der Zielgruppe (`LEAF_DAYS_NATIVE` bzw. `LEAF_DAYS_BROWSER`),
   begrenzt nur durch T1. Die Zielgruppe bleibt aus der Spanne geschlossen (`> LEAF_DAYS_NATIVE` → Browser); ein
   gekürztes Browser-Leaf erneuert dadurch als natives (90 Tage) — die sichere Richtung, und Browser-Zertifikate
   (`.p12`) laufen nicht über `/renew`. `test_renew_caps_lifetime_to_current_policy`
   (`apps/ca-issuer/tests/test_enroll_renew.py:160-174`) bleibt grün. Alternative: die Art aus dem Register lesen
   (`kind` der Gerätezeile) — größere Änderung an `TokenStore.renew` und beiden Stores für denselben Effekt.
5. **Statuscode (T2).** 503: der Fehler liegt beim Dienst, nicht beim Client; 403 (`IssuanceError`) hieße „Zugriff
   verweigert“ und schickte Betreiber auf die falsche Spur. Der Einmal-Token bleibt unverbraucht, weil
   `TokenStore.enroll` ihn bei einer Exception im Signieren zurücklegt (Vertrag `apps/ca-issuer/app/tokens.py:120-129`).

## Risiken & Rollback

- T3 bricht den Start ab, wo heute ein kaputtes oder abgelaufenes Intermediate still geladen wird. Bestehende
  Installationen sind jung (Intermediates frühestens 2031 abgelaufen); eine Hierarchie aus dem eigenen First Boot
  besteht alle Prüfungen. Der Upgrade-Pfad des Sammellaufs (`upgrade-path` vom letzten Release) lädt eine echte
  Alt-Hierarchie mit den neuen Prüfungen.
- Die Kette wird geparst verglichen (DER-gleich), nicht byteweise: ein Restore mit anderen Zeilenenden besteht.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung auf der Platte; Revert genügt.

## Doku-Impact

T3: `docs/admin/betrieb.html:172-173` + `docs/en/admin/operations.html:130-131` („Zertifikate erneuern“): Laufzeiten
von Root und Intermediates, die Begrenzung der Leaves, die Warnung ab 180 Tagen im Log des `ca-issuer` und der
Startabbruch bei abgelaufener oder inkonsistenter Hierarchie. CHANGELOG (Fixed) in T2 und T3. Die Bedienung der
Rotation dokumentiert R-0667.

## Offene Fragen

1. **Healthcheck bei weniger als N Tagen?** Die Zeile schlägt „Warnung im Log und Healthcheck bei weniger als N Tagen
   Restlaufzeit“ vor. Empfehlung: den Docker-Healthcheck **nicht** an die Warnschwelle hängen. frps wartet auf
   `ca-issuer: condition: service_healthy` (`docker-compose.yml:349-350`): ein „unhealthy“ in der Warnzeit hielte
   frps beim nächsten `docker compose up` (jedes Update) an, aus einer Warnung würde ein Tunnel-Ausfall. Mit
   Trade-off 1 (a) startet der Issuer bei abgelaufener Hierarchie gar nicht, der abgelaufene Fall ist damit sichtbar.
   Alternative: `/healthz` 503 ab N Tagen (wie die Zeile) oder ein zusätzliches Feld im Body von `/healthz` (kein
   Verbraucher liest es). Bei „ja“ eine zusätzliche Task an `main.py:124-126`; keine Task dieses Ledgers hängt daran.
2. **Warnschwelle 180 Tage** (Trade-off 2) — Entscheidung der Planung, Kevin kann sie ändern (eine Konstante).
3. **Ablaufanzeige für Admins** (Server-UI oder Monitoring) wäre eine eigene Roadmap-Zeile: der Issuer müsste die
   Daten über die gemeinsame DB oder eine Route weitergeben (Migration bzw. API). R-0667 bringt einen
   `status`-Befehl im Container.
