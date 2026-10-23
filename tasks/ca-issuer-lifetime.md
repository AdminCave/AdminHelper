<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CA-Issuer: kein Zertifikat überlebt seinen Aussteller, Prüfung der Hierarchie beim Start, Ablaufwarnung — Task-Ledger
Status: erledigt · Branch: feature/ca-issuer-lifetime · Review: pro Task
Spec: docs/features/ca-issuer-lifetime.md (Roadmap R-0666)
Heavy: linux-full — `apps/ca-issuer` (PKI): `ensure_hierarchy` prüft beim Start jede geladene Hierarchie, also auch die des Stacks im Sammellauf (`integration-stack` mit Enroll und Renew durch das Gateway, `backup-restore`, `upgrade-path` vom letzten Release mit einer echten Alt-Hierarchie); kein `scenario`: an Leaves aus einer frischen Hierarchie ändert sich nichts (die Begrenzung greift erst in den letzten 365 Tagen eines Intermediates), kein Wire-Format, kein Gateway-, FRP- oder Install-Pfad; kein `windows`: kein Agent- und kein Desktop-Code
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Kein Zertifikat des Issuers gilt länger als sein Aussteller; mit einem abgelaufenen oder noch nicht gültigen
Aussteller signiert er nicht, `/enroll` und `/renew` antworten dann 503. (2) `ensure_hierarchy` prüft die Hierarchie
beim Start und bricht bei einem Verstoß ab. (3) Root und Intermediates mit weniger als 180 Tagen Restlaufzeit stehen
als WARNING im Log. Zeilenangaben: origin/main@237b450a; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 zuerst (T2 und T3 nutzen `IssuerNotValid`, `EXPIRY_WARN_DAYS` und `days_left`); T2 und T3 sind
  danach unabhängig.
- `apps/ca-issuer` ist PKI und steht auf `scripts/dev/review-risk.txt`: jede Task bekommt zusätzlich `security`.
- Neue Code-Strings (Log-Zeilen, Fehlertexte) englisch; bestehende deutsche Texte bleiben.
- Ein Zertifikat mit wenig oder ohne Restlaufzeit entsteht im Test, indem `pki._now` während des Bauens auf einen
  früheren Zeitpunkt zeigt (`monkeypatch.setattr(pki, "_now", …)`), wie in der Probe des Beweises; keine Wartezeiten,
  keine eingefrorene Uhr für den ganzen Test.
- Die bestehenden Tests in `apps/ca-issuer/tests/` bleiben unverändert grün; die Hierarchie des `TestClient`
  (`apps/ca-issuer/tests/conftest.py`) ist frisch und besteht die Prüfungen aus T3.

### T1 — pki: kein Zertifikat überlebt seinen Aussteller, kein Signieren mit ungültigem Aussteller  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/pki.py, apps/ca-issuer/tests/test_pki.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_frps_cert.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @97bcb7d4 2026-10-22T13:45:39+02:00
Review: approve (.ah-out/review/ca-issuer-lifetime/T1.verdict.json)
Änderung: In `apps/ca-issuer/app/pki.py`: neue Konstante `EXPIRY_WARN_DAYS = 180` bei den Policy-Konstanten (`:30-46`), neue Exception `IssuerNotValid(ValueError)`, neue Funktion `days_left(cert, now=None) -> int` (ganze Tage bis `cert.not_valid_after_utc`, abgerundet, negativ nach dem Ablauf; `now` default `_now()`), und ein interner Helfer, der für einen Aussteller und eine Wunsch-Laufzeit das `notAfter` liefert: wirft `IssuerNotValid` (Text nennt CN des Ausstellers, `notBefore`/`notAfter` und „expired“ bzw. „not yet valid“), wenn `now` nicht in `[not_valid_before_utc, not_valid_after_utc)` liegt, sonst `min(now + timedelta(days=lifetime), issuer.not_valid_after_utc)`. `sign_leaf` (`:223-281`, `:253`) nutzt ihn mit `issuer_cert`, damit auch `build_server_leaf` (`:284-307`); `build_intermediate_ca` (`:148-176`, `:165`) mit `root_cert`. Der Docstring von `sign_leaf` nennt die Begrenzung. Tests in `test_pki.py`: (a) Intermediate mit 5 Tagen Restlaufzeit → `sign_leaf` mit 90 Tagen ergibt `not_valid_after_utc == issuer.not_valid_after_utc`; (b) dasselbe für `build_server_leaf` mit `LEAF_DAYS_GATEWAY`; (c) Root mit 100 Tagen Restlaufzeit → `build_intermediate_ca` endet mit der Root; (d) abgelaufenes Intermediate → `sign_leaf` wirft `IssuerNotValid`; abgelaufene Root → `build_intermediate_ca` wirft `IssuerNotValid`; (e) Intermediate mit `notBefore` in der Zukunft → `IssuerNotValid`; (f) `days_left`: 10 Tage vor dem Ablauf → 9 oder 10 (abgerundet, Grenzfall im Test festhalten), nach dem Ablauf negativ. Zuerst rot: (a)–(e) auf HEAD. Die bestehenden Spannen-Asserts (`test_pki.py`, `test_gateway_cert.py:42-43`) bleiben grün.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_pki.py tests/test_gateway_cert.py tests/test_frps_cert.py
Doku: keine (intern; die Betreiber-Doku kommt mit T3)
Beweis: origin/main@237b450a · Probe (Python 3.13.5, cryptography 50.0.1, `python -I`, `pki._now` beim Bauen 1820 Tage zurück): `tunnel`-Intermediate `notAfter` 2026-10-27, `sign_leaf` mit `LeafSpec(lifetime_days=90)` → Leaf `notAfter` 2027-01-20, `leaf_outlives_issuer True`; dreimal identisch (gleiche md5 der Ausgabe)
Orakel: contract — `leaf.not_valid_after_utc <= issuer.not_valid_after_utc` für jedes ausgestellte Zertifikat
Dedup-Key: bug:ca-issuer:pki.py:leaf-outlives-intermediate-no-expiry-warning
HEAD: 237b450a

### T2 — Issuer: 503 bei ungültigem Intermediate, Erneuerung mit voller Policy, tägliche Ablaufwarnung  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/issuer.py, apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_enroll_renew.py, CHANGELOG.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @1efc45cc 2026-10-22T13:56:19+02:00
Review: approve (.ah-out/review/ca-issuer-lifetime/T2.verdict.json)
Änderung: (1) `IssuerNotValid` aus `sign_leaf` (T1) wird im Issuer zu einer eigenen Exception `IssuerUnavailable` (nicht von `IssuanceError` abgeleitet), mit `logger.error` (Scope, `notAfter` des Intermediates); `main.py` antwortet für `/enroll` (`:129-134`) und `/renew` (`:137-154`) mit HTTP 503 und `detail` „the issuing intermediate certificate of scope '<scope>' is expired or not yet valid; see the ca-issuer log“. Der Einmal-Token bleibt unverbraucht (Vertrag `apps/ca-issuer/app/tokens.py:120-129`; beide Stores legen ihn bei einer Exception im Signieren zurück). (2) `renew` (`apps/ca-issuer/app/issuer.py:155-170`): `lifetime_days` ist `audience_max` statt `min(span_days, audience_max)`; die Zielgruppe bleibt aus der Spanne geschlossen, `legacy_kind` (`:177`) bleibt; der Kommentar `:155-159` sagt, warum die Spanne nicht mehr vererbt wird (T1 kürzt Leaves vor dem Ablauf eines Intermediates, die Kürzung darf nicht an alle Nachfolger gehen). (3) `_sign` (`:77-90`): nach dem Signieren, wenn `pki.days_left(inter.cert) < pki.EXPIRY_WARN_DAYS`, eine WARNING „intermediate %r expires on %s (%d days left)“ — höchstens einmal je Scope und UTC-Tag (Zustand im `Issuer`, unter einem Lock). Tests in `test_enroll_renew.py` (Issuer mit selbst gebauten Intermediates wie `apps/ca-issuer/tests/test_gateway_cert.py:19-24`, in `app.state.issuer` eingesetzt; `register_client` für den Token-Fall): (a) abgelaufenes `access`-Intermediate → `/enroll` 503, `detail` nennt den Scope, danach `store.consume(token)` gibt den Grant zurück (für beide Stores, wie `test_a_failed_signing_does_not_spend_the_token`, `:484-490`); (b) `/renew` mit einem gültigen Leaf, das ein abgelaufenes Intermediate signiert hat (Leaf ohne Begrenzung direkt mit `CertificateBuilder` gebaut, wie ein Altbestand) → 503; (c) ein natives Leaf mit 30 Tagen Spanne vom gültigen Intermediate erneuert mit `LEAF_DAYS_NATIVE` (±1 Tag); (d) Intermediate mit 10 Tagen Restlaufzeit: zwei `/enroll` hintereinander → genau ein WARNING-Record unter `ca-issuer.issuer`, der den Scope nennt; frisches Intermediate → keiner. Zuerst rot: (a), (b) (auf HEAD 200 mit einem Leaf, das sein Intermediate überlebt), (c), (d). `test_renew_caps_lifetime_to_current_policy` (`:160-174`) und `test_renew_reissues_same_identity_and_lifetime` (`:148-157`) bleiben grün.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_enroll_renew.py
Doku: CHANGELOG.md (Fixed, umlautfrei: der ca-issuer stellt kein Zertifikat mehr aus, das sein Zwischenzertifikat ueberlebt; mit abgelaufenem Zwischenzertifikat antworten /enroll und /renew 503 statt still ungueltige Zertifikate zu signieren; ab 180 Tagen vor dem Ablauf eine taegliche Warnung im Log) · `docs/` mit T3
Abhängt von: T1
Beweis: origin/main@237b450a · Code-Lesung `apps/ca-issuer/app/issuer.py:77-90` (signiert ohne Blick auf das Intermediate) und `:160-170` (`min(span_days, audience_max)`); Probe aus T1: das abgelaufene Intermediate signiert ohne Fehler
Orakel: contract — 503 und unverbrauchter Token bei ungültigem Intermediate; Laufzeit der Erneuerung = Policy der Zielgruppe
Dedup-Key: bug:ca-issuer:issuer.py:expired-intermediate-signs-silently
HEAD: 237b450a

### T3 — ensure_hierarchy: Hierarchie beim Start prüfen, Ablaufwarnung im Log  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_storage.py, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @7e06dfa0 2026-10-23T06:20:22+02:00
Review: approve (.ah-out/review/ca-issuer-lifetime/T3.verdict.json)
Änderung: Nach dem Laden (`apps/ca-issuer/app/storage.py:132-137`) prüft `ensure_hierarchy` und bricht bei jedem Verstoß mit `RuntimeError` ab (Text englisch, nennt Datei, Scope und Grund, wie `:113-116`): `root.crt` selbstsigniert (`verify_directly_issued_by(root)`) und zeitlich gültig (`notBefore` ≤ jetzt < `notAfter`); je Scope `<scope>.crt` von `root.crt` signiert (`verify_directly_issued_by`; `ValueError`, `TypeError`, `InvalidSignature` → Abbruch), zeitlich gültig, der öffentliche Schlüssel von `<scope>.key` gleich dem des Zertifikats (wie `_pair_matches`, `:168-179`), `<scope>-chain.pem` geparst gleich `[<scope>.crt, root.crt]` (DER-Vergleich). Danach für die Root und jedes Intermediate mit `pki.days_left(...) < pki.EXPIRY_WARN_DAYS` eine WARNING „%s expires on %s (%d days left)“ (bei der Root zusätzlich: eine Root-Erneuerung heißt, alle Clients neu zu enrollen). Die Prüfung läuft auch direkt nach dem First Boot (dieselbe Ladeschleife). Tests in `test_storage.py` (Hierarchie per `ensure_hierarchy(tmp_path, b"pw")`, Manipulation mit dem entschlüsselten `root.key.enc`): (a) `tunnel` durch ein abgelaufenes, von der Root signiertes Intermediate ersetzt (Zertifikat, Schlüssel, Kette konsistent) → `RuntimeError`, Text nennt `tunnel` und „expired“; (b) `notBefore` in der Zukunft → `RuntimeError`; (c) `access.crt` von einer fremden Root → `RuntimeError`; (d) `internal.key` aus einem anderen Schlüssel → `RuntimeError`; (e) `tunnel-chain.pem` mit der Kette eines anderen Scopes → `RuntimeError`; (f) Intermediate mit 30 Tagen Restlaufzeit (konsistent) → lädt, genau eine WARNING unter `ca-issuer.storage`, die den Scope und das Datum nennt; (g) frische Hierarchie → keine WARNING (Gegenstück zu f). Zuerst rot: (a)–(f) auf HEAD. `test_hierarchy_encrypts_root_and_is_idempotent` (`:32-46`) und `test_ensure_hierarchy_aborts_on_partial_pki` (`apps/ca-issuer/tests/test_gateway_cert.py:165`) bleiben grün.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_gateway_cert.py tests/test_enroll_renew.py
Doku: `docs/admin/betrieb.html:172-173` + `docs/en/admin/operations.html:130-131` („Zertifikate erneuern“, ein neuer Absatz nach dem bestehenden): Root 10 Jahre, Intermediates 5 Jahre; kein Zertifikat gilt länger als sein Aussteller (Leaves kurz vor dem Ablauf eines Intermediates werden kürzer); ab 180 Tagen vor dem Ablauf warnt der `ca-issuer` im Log (`docker compose logs ca-issuer`, Logger `ca-issuer.storage` beim Start, `ca-issuer.issuer` beim Signieren); mit abgelaufener oder inkonsistenter Hierarchie startet der `ca-issuer` nicht und nennt im Log Datei und Grund · CHANGELOG.md (Fixed, umlautfrei: der ca-issuer prueft beim Start Root und Zwischenzertifikate — Signatur, Schluessel, Kette, Gueltigkeit — und startet bei einem Verstoss nicht; Ablaufwarnung ab 180 Tagen)
Abhängt von: T1
Beweis: origin/main@237b450a · Probe wie T1 (Python 3.13.5, cryptography 50.0.1): `ensure_hierarchy(d, b"pw")`, danach `tunnel.crt`/`tunnel.key` durch ein seit 75 Tagen abgelaufenes, von derselben Root signiertes Intermediate ersetzt → `ensure_hierarchy(d, None)` lädt es ohne Exception (`expired_loaded True`); dreimal identisch
Orakel: contract — `ensure_hierarchy` gibt nur eine Hierarchie zurück, deren Intermediates von der Root stammen, zeitlich gültig sind und zu Schlüssel und Kette passen
Dedup-Key: bug:ca-issuer:storage.py:ensure-hierarchy-loads-unchecked
HEAD: 237b450a

### T4 — ensure_hierarchy: die ausgelieferte Kette aus den geprüften Zertifikaten bauen  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_storage.py, CHANGELOG.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @be39e4bc 2026-10-23T06:25:39+02:00
Review: approve (.ah-out/review/ca-issuer-lifetime/T4.verdict.json)
Änderung: `ensure_hierarchy` gibt `Intermediate(..., chain=pki.chain_pem(cert, root_cert))` zurück statt der gelesenen Dateibytes (`storage.py:169`). Die Prüfung `_chain_is` gegen `[intermediate, root]` bleibt, und eine falsche Kette bricht den Start weiter ab. Test: Eine Kettendatei, deren Bytes nicht genau der kanonischen Kette entsprechen (zusätzlicher Inhalt neben den zwei Zertifikaten), ergibt `Intermediate.chain == pki.chain_pem(intermediate, root)`. Der Test ist zuerst rot.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_storage.py tests/test_gateway_cert.py tests/test_frps_cert.py tests/test_enroll_renew.py
Doku: CHANGELOG.md (Changed, neutral: der ca-issuer liefert die Zertifikatskette aus den beim Start geprüften Zertifikaten aus)
Beweis: feature/ca-issuer-lifetime@7e06dfa0 · storage.py:169 übergibt die gelesenen Bytes der Kettendatei · Prüfer-Probe T3 (privat)
HEAD: 7e06dfa0
