<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP-Nachzügler: Wächter nach dem Filtern, stcp-Felder nur an stcp-Tunneln — Task-Ledger
Status: freigegeben · Branch: feature/frp-secret-followups · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-10-02 (Design-Gate, „FRP-Nachzügler“ freigegeben), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0128, R-0129
Heavy: none — kein Datenpfad eines nutzbaren Tunnels ändert sich: T1 betrifft nur stcp-Tunnel ohne Secret (über die API seit #61 nicht mehr erzeugbar), T2 nur das Speichern beim Typwechsel; pytest deckt Generate-Routen, POST und PUT ab, das Szenario `--tunnel` lief für #61 grün.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-02 von der Aufsicht (adminhelper-ac). Zeilenangaben main@927134b3.
Befund: Die Generate-Routen prüfen „keine Tunnel ⇒ 404“, bevor der Generator stcp-Tunnel ohne Secret weglässt
(`_without_secretless_stcp`, `apps/server/app/modules/frp/config_generator.py:35`). Haben alle sichtbaren stcp-Tunnel
eines Nutzers kein Secret, liefern `visitor-toml` und `visitor-bundle` das gemeinsame `auth.token` ohne einen
`[[visitors]]`-Block, `frpc-toml` ein TOML ohne `[[proxies]]`, und `bulk-zip` schreibt `visitors/<user>.toml` mit Token,
aber ohne Visitor. Unabhängig davon behält ein Tunnel, der per PUT von stcp auf https wechselt, `secret_key` und
`visitor_port` (`tunnel_router.py:184–202` leert nichts). `next_visitor_port` (`_helpers.py:62`) zählt nur stcp-Zeilen,
der Unique-Index auf `visitor_port` gilt nur für stcp (`models.py:80`). Ein anderer stcp-Tunnel bekommt deshalb denselben
Port, und der Wechsel zurück auf stcp endet mit 409.

Entscheidungen (Kevin bzw. Aufsicht, 2026-10-02):
- A: Haben die sichtbaren stcp-Tunnel kein Secret, antworten die Routen mit demselben 404 wie ohne Tunnel (Aufsicht).
- B: Der Wechsel auf https leert Secret **und** `visitor_port`; ein https-POST verwirft mitgeschickte stcp-Felder (Kevin).
- C: Keine Datenmigration. Wechselt ein Tunnel auf stcp und ist der gespeicherte Port belegt, vergibt der Server einen
  freien Port; ist keiner gespeichert, vergibt er ihn wie bisher (Kevin, „Heilen beim Wechsel“).
- D: Wechselt ein Tunnel von einem anderen Typ auf stcp und schickt kein `secret_key` mit, erzeugt der Server immer
  ein neues Secret, auch wenn eine Altzeile noch eines trägt (Kevin am Gate, „Immer neues Secret“).
- Doku-Stelle des 404: die API-Referenz (DE + EN); `docs/` beschrieb ihn bisher nirgends (Aufsicht am Gate).

### T1 — Generate-Routen prüfen auf Tunnel erst nach dem Weglassen der Tunnel ohne Secret  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_frp_permissions.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: `gen_visitor_toml` (`generate_router.py:121`), `gen_visitor_bundle` (`:145`) und `gen_frpc_toml` (`:87`)
lassen stcp-Tunnel ohne Secret weg, **bevor** sie auf eine leere Liste prüfen; die Antwort ist dann derselbe 404 wie
ohne Tunnel (Entscheidung A). `gen_bulk_zip` filtert `u_tunnels` vor `if u_tunnels:` (`:197–198`), sodass kein
`visitors/<user>.toml` ohne Visitor entsteht; der Zweig ohne zugeordnete Nutzer (`:203–204`) bleibt unverändert. Den
Filter nicht nachbauen: `_without_secretless_stcp` wird öffentlich (`without_secretless_stcp`, drei Aufrufer im
Generator), damit die Warnung im Log bleibt. Tests (in `tests/test_frp_permissions.py`, Muster
`two_servers_with_tunnels`): ein normaler Nutzer, dessen einziger sichtbarer stcp-Tunnel kein Secret hat, bekommt bei
`visitor-bundle` und `visitor-toml` 404; `frpc-toml` für einen Server, dessen einziger Tunnel ein stcp ohne Secret ist,
gibt 404; `bulk-zip` enthält für diesen Nutzer keine `visitors/<user>.toml`; ein Nutzer mit einem Tunnel ohne und einem
mit Secret bekommt 200 mit genau dem einen Visitor. Vor dem Fix rot: die ersten drei.
Beweis: origin/main@927134b3, Wegwerf-Test im eigenen Worktree (Aufsicht 2026-10-02): `secret_key` von `t-a` per DB auf
NULL, Nutzer `viewer` mit `srv-a` ⇒ `gen_visitor_bundle` liefert 200, TOML enthält `auth.token = "secret-frps-auth"`
und kein `[[visitors]]`; `gen_frpc_toml("srv-a")` liefert ein TOML ohne `[[proxies]]`; Log „FRP tunnel a-ssh is stcp
without a secret, left out of the config“
Dedup-Key: bug:server:generate_router.py:guard-before-filter
HEAD: 927134b3
Semantik: keine Stelle in docs/ — gesucht nach „Keine sichtbaren“, „404“, „visitor-toml“, „visitor-bundle“ in
`docs/**/*.html` (DE). Die Absicht steht im Code-Kommentar `generate_router.py:118–120`: „without visible STCP tunnels
the user has no legitimate reason for it, so refuse rather than hand the global secret to any authenticated
(non-admin, server-less) user (3.33)“, und in der Spec `docs/features/frp-secret-handling.md`: „Der Generator schreibt
nie ein leeres Secret: ein stcp-Tunnel ohne Secret wird übersprungen“.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_permissions.py tests/test_frp_tunnels.py tests/test_frp_toml_roundtrip.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (Zeilen 137–139: 404, wenn kein
nutzbarer STCP-Tunnel sichtbar ist, auch wenn die sichtbaren kein Secret haben) · CHANGELOG (Fixed)

### T2 — Secret und Visitor-Port nur an stcp-Tunneln; der Wechsel zurück auf stcp heilt einen belegten Port  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_tunnels.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, CHANGELOG.md
Änderung: `update_tunnel` (`tunnel_router.py:145`) setzt nach dem Übernehmen der Felder (`:184–197`) bei einem
Tunnel, der danach nicht stcp ist, `secret_key` und `visitor_port` auf `None` (Entscheidung B). `create_tunnel`
(`:53`) speichert für einen nicht-stcp-Tunnel weder ein mitgeschicktes `secret_key` noch einen `visitor_port`
(`:71–77`). Ist der Tunnel nach dem Update stcp und trägt einen `visitor_port`, der in diesem PUT nicht mitgeschickt
wurde und schon einem anderen stcp-Tunnel gehört, vergibt der Server `next_visitor_port(db, exclude_tunnel_id=…)`
(Entscheidung C, heilt Altzeilen ohne Migration); ein ausdrücklich mitgeschickter, belegter Port bleibt 409 wie
heute. Wechselt der Tunnel in diesem PUT von einem anderen Typ auf stcp und schickt kein `secret_key` mit, erzeugt der
Server immer ein neues Secret, auch wenn eine Altzeile noch eines trägt (Entscheidung D); bleibt er stcp, gilt wie
bisher „leer = unverändert“ (`:201–202`). Tests (`tests/test_frp_tunnels.py`, Muster `_seed`/`_body`):
PUT stcp→https leert `secret_key` und `visitor_port` in der DB; ein https-POST mit `secret_key` und `visitor_port`
speichert beides nicht; Hin- und Rückwechsel, während ein anderer stcp-Tunnel den alten Port bekommen hat, gibt 200 mit
neuem Secret und freiem Port; eine Altzeile (https mit Secret und Port 6000, direkt in der DB) plus ein anderer stcp
auf 6000 ⇒ PUT `{"tunnel_type": "stcp"}` gibt 200 mit einem freien Port und einem neuen Secret (≠ dem alten); ein
mitgeschickter belegter Port bleibt 409. Vor dem Fix rot: die ersten vier.
Beweis: origin/main@927134b3, Wegwerf-Test im eigenen Worktree (Aufsicht 2026-10-02): PUT `/api/frp/tunnels/t-a`
`{"tunnel_type":"https","protocol":"web","custom_domains":"a.example.test"}` ⇒ 200, danach in der DB
`type=https secret='existing-secret' visitor_port=6000`; POST eines neuen stcp-Tunnels ⇒ 201 mit `visitorPort` 6000;
PUT `t-a` `{"tunnel_type":"stcp"}` ⇒ 409 `Proxy-Name oder Visitor-Port ist bereits belegt`
Dedup-Key: ref:server:tunnel_router.py:secret-kept-on-https
HEAD: 927134b3
Semantik: `docs/admin/frp-tunnel.html:93`: „Das Feld <strong>Secret-Key</strong> eines STCP-Tunnels …“;
`docs/developer/api-reference.html:130`: „STCP (mit <code>secret_key</code>, <code>visitor_port</code>) oder HTTPS
(<code>custom_domains</code>)“; `apps/server/app/modules/frp/models.py:96`/`:98`: `secret_key … # STCP only`,
`visitor_port … # local port on the admin PC (STCP)`. Beide Felder sind als reine stcp-Felder beschrieben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_frp_permissions.py tests/test_frp_input_hardening.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (Zeilen 130/132: POST und PUT — ein
https-Tunnel trägt weder Secret noch Visitor-Port, der Wechsel auf HTTPS löscht beide, der Wechsel zurück auf STCP
vergibt bei belegtem Port einen freien) · docs/admin/frp-tunnel.html:93 + docs/en/admin/frp-tunnel.html:57 (ein
Halbsatz: der Wechsel auf HTTPS löscht das Secret; zurück auf STCP gibt es ein neues) · CHANGELOG (Fixed)
