<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Third-Party Licenses

AdminHelper ist als Ganzes unter **GPL-3.0-or-later** lizenziert
(Copyright © 2026 Kevin Stenzel). Diese Datei listet die
Drittanbieter-Abhängigkeiten je Sprache/Komponente mit ihrer jeweiligen Lizenz
auf. Gelistet ist, was in die **ausgelieferten Artefakte** einfließt
(Laufzeit-/Build-gelinkte Abhängigkeiten); reine Entwickler-Werkzeuge
(pytest, ruff, vite, eslint …) werden nicht ausgeliefert und daher nicht geführt.

Alle hier gelisteten Lizenzen sind mit GPL-3.0-or-later kompatibel. Die Auflagen
einzelner Lizenzen (NOTICE-Pflicht bei Apache-2.0, Mitlieferung des
LGPL-Quelltexts bei psycopg, Lizenztext bei MPL-2.0/Unicode-3.0) sind im
Abschnitt **„Auflagen & Hinweise"** am Ende zusammengefasst.

> **Erzeugung:** die Paket-Tabellen werden aus dem echten Dependency-Stand
> generiert — `scripts/gen-third-party-licenses.sh` (pip-licenses × Server/
> Monitoring/CA-Issuer, go-licenses für Linux + Windows, cargo-license,
> license-checker × Frontends). Stand **2026-07-10**. Die Auflagen-Abschnitte
> sind manuell kuratiert. Transitive Abhängigkeiten können sich bei einem
> erneuten Lock verschieben — dann das Skript erneut laufen lassen.

---

## 1. Python — Server, Monitoring, CA-Issuer

Erzeugt mit `pip-licenses` aus je einer frischen venv mit **nur** der
`requirements.txt` des Dienstes (Spalten **S** = Server, **M** = Monitoring,
**C** = CA-Issuer).

| Paket | Version | Lizenz | S | M | C |
|---|---|---|:-:|:-:|:-:|
| bcrypt | 5.0.0 | Apache-2.0 | x |  |  |
| python-multipart | 0.0.32 | Apache-2.0 | x |  |  |
| cryptography | 48.0.1 | Apache-2.0 OR BSD-3-Clause | x |  | x |
| uvloop | 0.22.1 | Apache-2.0 OR MIT | x | x | x |
| click | 8.4.1 | BSD-3-Clause | x | x | x |
| httpcore | 1.0.9 | BSD-3-Clause | x | x |  |
| httpx | 0.28.1 | BSD-3-Clause | x | x |  |
| idna | 3.18 | BSD-3-Clause | x | x | x |
| MarkupSafe | 3.0.3 | BSD-3-Clause | x | x |  |
| pycparser | 3.0 | BSD-3-Clause | x |  | x |
| python-dotenv | 1.2.2 | BSD-3-Clause | x | x | x |
| starlette | 1.3.1 | BSD-3-Clause | x | x | x |
| uvicorn | 0.49.0 | BSD-3-Clause | x | x | x |
| websockets | 16.0 | BSD-3-Clause | x | x | x |
| psycopg | 3.3.4 | LGPL-3.0-only | x | x | x |
| psycopg-binary | 3.3.4 | LGPL-3.0-only | x | x | x |
| alembic | 1.18.4 | MIT | x | x |  |
| annotated-doc | 0.0.4 | MIT | x | x | x |
| annotated-types | 0.7.0 | MIT | x | x | x |
| anyio | 4.13.0 | MIT | x | x | x |
| APScheduler | 3.11.2 | MIT | x | x |  |
| cffi | 2.0.0 | MIT | x |  | x |
| fastapi | 0.138.0 / 0.139.0 | MIT | x | x | x |
| h11 | 0.16.0 | MIT | x | x | x |
| httptools | 0.8.0 | MIT | x | x | x |
| Mako | 1.3.12 | MIT | x | x |  |
| pydantic | 2.13.4 | MIT | x | x | x |
| pydantic_core | 2.46.4 | MIT | x | x | x |
| PyJWT | 2.13.0 | MIT | x |  |  |
| PyYAML | 6.0.3 | MIT | x | x | x |
| redis | 8.0.0 | MIT | x |  |  |
| SQLAlchemy | 2.0.50 | MIT | x | x | x |
| typing-inspection | 0.4.2 | MIT | x | x | x |
| tzlocal | 5.3.1 | MIT | x | x |  |
| watchfiles | 1.2.0 | MIT | x | x | x |
| greenlet | 3.5.1 | MIT AND PSF-2.0 | x | x | x |
| certifi | 2026.5.20 | MPL-2.0 | x | x |  |
| typing_extensions | 4.15.0 | PSF-2.0 | x | x | x |

`fastapi` ist im Server/Monitoring auf `0.138.0`, im CA-Issuer auf `0.139.0`
gepinnt.

**Auflagen-relevant:** Apache-2.0 (NOTICE) — `bcrypt`, `python-multipart`;
LGPL-3.0 — `psycopg`, `psycopg-binary`; MPL-2.0 — `certifi`. `cryptography`
(Apache OR BSD) und `uvloop` (Apache OR MIT) sind dual — es wird der
permissive Zweig geführt (siehe „Auflagen & Hinweise").

## 2. Go — Agent (`apps/agent/`)

Erzeugt mit `go-licenses` je Zielplattform (`//go:build`-Tags ziehen andere
Pakete). Der Agent-eigene Code steht unter GPL-3.0-or-later.

### In allen Builds gelinkt

| Paket | Lizenz |
|---|---|
| github.com/spf13/cobra | Apache-2.0 |
| github.com/spf13/pflag | BSD-3-Clause |
| github.com/shirou/gopsutil/v4 | BSD-3-Clause |
| github.com/tklauser/numcpus | Apache-2.0 |
| gopkg.in/natefinch/lumberjack.v2 | MIT |
| golang.org/x/sys | BSD-3-Clause |

### Nur Linux

| Paket | Lizenz |
|---|---|
| github.com/tklauser/go-sysconf | BSD-3-Clause |

### Nur Windows

| Paket | Lizenz |
|---|---|
| github.com/inconshreveable/mousetrap | Apache-2.0 |
| github.com/go-ole/go-ole | MIT |
| github.com/yusufpapurcu/wmi | MIT |

**Auflagen-relevant:** Apache-2.0 (NOTICE) — `cobra`, `numcpus`, `mousetrap`.

## 3. Rust — Desktop-Client (`apps/desktop/src-tauri/`, Tauri 2)

### Direkte Abhängigkeiten (`Cargo.toml`)

`serde`, `serde_json`, `tauri`, `reqwest`, `futures-util`, `tokio`, `url`,
`open`, `keyring`, `tauri-plugin-shell`, `tauri-plugin-dialog`,
`tauri-plugin-notification`, `tauri-plugin-log`, `log`, `chrono`, `regex`,
`rustls`, `sha2`, `ring`, `rcgen`, `rustls-pki-types`, `x509-parser`, `p12`,
`toml` — überwiegend `Apache-2.0 OR MIT` bzw. `MIT`.

> Hinweis: `rustls-pemfile` ist **nicht** mehr direkte Abhängigkeit — das
> Paket ist seit Aug. 2025 archiviert, seine PEM-Parser wanderten in die
> `PemObject`-API von `rustls-pki-types` (bereits über `rustls` im Graphen).

### Lizenzverteilung über den gesamten Crate-Graphen

Erzeugt mit `cargo-license` (648 Fremd-Crates; das App-Crate `adminhelper`
selbst ist GPL-3.0-or-later und hier nicht mitgezählt).

| Lizenz(-Ausdruck) | Crates |
|---|--:|
| Apache-2.0 OR MIT | 386 |
| MIT | 162 |
| Apache-2.0 OR MIT OR Zlib | 21 |
| Unicode-3.0 | 18 |
| Apache-2.0 OR Apache-2.0 WITH LLVM-exception OR MIT | 15 |
| MIT OR Unlicense | 7 |
| MPL-2.0 | 7 |
| Apache-2.0 | 3 |
| BSD-3-Clause | 3 |
| ISC | 3 |
| Zlib | 2 |
| Apache-2.0 OR ISC OR MIT | 2 |
| Apache-2.0 OR BSD-3-Clause | 2 |
| Apache-2.0 OR BSD-3-Clause OR MIT | 2 |
| Apache-2.0 OR LGPL-2.1-or-later OR MIT | 2 |
| Apache-2.0 OR BSD-2-Clause OR MIT | 2 |
| übrige (je 1) | 11 |

Die „übrigen" Einzelfälle: `0BSD OR Apache-2.0 OR MIT`, `BSD-3-Clause AND MIT`,
`BSD-3-Clause OR MIT`, `Apache-2.0 AND MIT`, `Apache-2.0 OR CC0-1.0 OR MIT-0`,
`(Apache-2.0 OR MIT) AND BSD-3-Clause`, `Apache-2.0 AND ISC`,
`Apache-2.0 OR BSL-1.0`, `Apache-2.0 WITH LLVM-exception`,
`(Apache-2.0 OR MIT) AND Unicode-3.0`, `CDLA-Permissive-2.0`.

**Auflagen-relevant:**

- **Apache-2.0 (NOTICE), unvermeidbar** (pur oder als `AND`-Anteil):
  `borsh-derive`, `sync_wrapper`, `tao`, `dpi`, `encoding_rs`, `ring`,
  `unicode-ident`.
- **MPL-2.0:** `cssparser`, `cssparser-macros`, `dtoa-short`, `option-ext`,
  `selectors`.
- **Unicode-3.0:** die ICU-/Zerovec-Familie (`icu_*`, `litemap`, `tinystr`,
  `writeable`, `yoke`, `zerofrom`, `zerotrie`, `zerovec`, `potential_utf`).

Der einzige `LGPL`-Treffer (`r-efi`) ist dual `Apache-2.0 OR LGPL-2.1 OR MIT`
→ permissiver Zweig, keine LGPL-Auflage.

## 4. JavaScript / TypeScript — Frontends

Erzeugt mit `license-checker --production` (nur ausgelieferte Laufzeit-Deps).

### `apps/desktop/ui/` (in den Desktop-Client gebündelt)

| Paket | Version | Lizenz |
|---|---|---|
| @tauri-apps/api | 2.11.0 | Apache-2.0 OR MIT |
| @tauri-apps/plugin-dialog | 2.7.1 | MIT OR Apache-2.0 |
| @tauri-apps/plugin-notification | 2.3.3 | MIT OR Apache-2.0 |
| @tauri-apps/plugin-shell | 2.3.5 | MIT OR Apache-2.0 |
| uplot | 1.6.32 | MIT |

Alle `@tauri-apps/*`-Pakete sind dual MIT/Apache → es wird der MIT-Zweig
geführt (keine NOTICE-Pflicht).

### `apps/web/` (Admin-Panel) und `apps/desktop/e2e/`

**Keine ausgelieferten Dritt-Laufzeit-Abhängigkeiten.** Das Admin-Panel ist
eine reine Svelte-Anwendung — Svelte kompiliert zur Build-Zeit weg, und
`apps/web` deklariert keine Laufzeit-`dependencies` (Vite/Svelte/ESLint sind
`devDependencies` = Build-Werkzeuge, nicht Teil des ausgelieferten Bundles).
`apps/desktop/e2e/` ist ein reines Test-Harness und wird nicht ausgeliefert.

---

## Auflagen & Hinweise

### Apache-2.0 — NOTICE-Pflicht

§ 4(d) der Apache-2.0 verlangt, alle mitgelieferten `NOTICE`-Dateien der
betreffenden Projekte in der Distribution weiterzugeben. Zwingend
Apache-lizenziert (pur oder als `AND`-Anteil) sind:

- **Python:** `bcrypt`, `python-multipart`
- **Go:** `cobra`, `numcpus`, `mousetrap`
- **Rust:** `borsh-derive`, `sync_wrapper`, `tao`, `dpi`, `encoding_rs`,
  `ring`, `unicode-ident`

Sofern diese Projekte eine `NOTICE`-Datei mitliefern, gehört deren Inhalt
unverändert in die Distribution. Bei allen **dual** MIT/Apache lizenzierten
Paketen (`cryptography`↔BSD, `uvloop`↔MIT, die `@tauri-apps/*`, der Großteil
des Rust-Graphen) wird der **permissive Zweig (MIT bzw. BSD)** geführt, um die
NOTICE-Pflicht zu vermeiden.

### LGPL-3.0 — psycopg

`psycopg` und `psycopg-binary` stehen unter **LGPL-3.0-only** (in allen drei
Python-Diensten). Kompatibel mit GPL-3.0-or-later. Auflage: Der unveränderte
LGPL-lizenzierte Quelltext muss mitgeliefert oder per schriftlichem Angebot
zugänglich gemacht werden, und Endnutzer müssen die psycopg-Komponente durch
eine eigene Version ersetzen können (bei dynamischem Bezug über PyPI gegeben).

### MPL-2.0

`MPL-2.0` betrifft `certifi` (Python, Server + Monitoring) sowie im
Rust-Graphen `cssparser`, `cssparser-macros`, `dtoa-short`, `option-ext` und
`selectors`. Auflage: Der jeweilige MPL-Quelltext (unverändert) bzw. der
Verweis darauf ist in der Distribution mitzuführen; die MPL-Dateien bleiben
unter MPL, ohne die GPL-Gesamtlizenz zu berühren.

### Unicode-3.0 / BSD / ISC / Zlib

Die `Unicode-3.0`-Crates (ICU-/Zerovec-Familie im Rust-Graphen) sowie die
diversen `BSD`-/`ISC`-/`Zlib`-/`MIT`-Lizenzen sind GPL-3.0-kompatibel. Es
genügt, den jeweiligen Lizenztext bzw. Copyright-Hinweis in der Distribution
mitzuführen.

---

## Reproduktion

Die Paket-Tabellen dieser Datei werden aus dem echten Dependency-Stand
generiert:

```sh
scripts/gen-third-party-licenses.sh   # -> ./third-party-inventory/
```

Das Skript legt je Komponente eine maschinenlesbare Datei ab
(`python-*.csv`, `go-*.csv`, `rust.json`, `js-*.json`) und benötigt beim
ersten Lauf Netzzugang (installiert `pip-licenses` / `go-licenses` /
`cargo-license` / `license-checker` bei Bedarf). Die Auflagen-Abschnitte oben
sind manuell kuratiert und bei größeren Dependency-Änderungen zu prüfen.
