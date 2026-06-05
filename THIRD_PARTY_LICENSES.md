<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Third-Party Licenses

AdminHelper ist als Ganzes unter **GPL-3.0-or-later** lizenziert
(Copyright © 2026 Kevin Stenzel). Diese Datei listet die Drittanbieter-
Abhängigkeiten je Sprache/Komponente mit ihrer jeweiligen Lizenz auf.

Alle hier gelisteten Lizenzen sind mit GPL-3.0-or-later kompatibel. Die
Auflagen, die sich aus einzelnen Lizenzen ergeben (NOTICE-Pflicht bei
Apache-2.0, Mitlieferung des LGPL-Quelltexts bei psycopg), sind in den
jeweiligen Abschnitten und in **Abschnitt „Auflagen & Hinweise“** am Ende
zusammengefasst.

> Erzeugung: teilweise automatisiert generiert
> (`pip-licenses`, `go-licenses`, `cargo metadata`, `license-checker`),
> Stand 2026-06-04. Versionen entsprechen dem zum Stichtag aufgelösten
> Dependency-Stand; transitive Abhängigkeiten können sich bei einem
> erneuten Lock verschieben.

---

## 1. Python — Server (`server/`) und Monitoring (`monitoring/`)

Quelle: `pip-licenses` über eine frische Installation von
`server/requirements.txt` (das Monitoring nutzt eine Teilmenge:
`fastapi`, `uvicorn[standard]`, `sqlalchemy`, `httpx`, `apscheduler`,
`alembic`, `psycopg[binary]`). Direkte Abhängigkeiten sind **fett**
markiert, alles Übrige ist transitiv.

| Paket | Version | Lizenz |
|-------|---------|--------|
| **APScheduler** | 3.11.2 | MIT |
| **PyJWT** | 2.13.0 | MIT |
| **SQLAlchemy** | 2.0.50 | MIT |
| **alembic** | 1.18.4 | MIT |
| **bcrypt** | 5.0.0 | **Apache-2.0** |
| **cryptography** | 48.0.0 | **Apache-2.0** OR BSD-3-Clause |
| **fastapi** | 0.136.3 | MIT |
| **httpx** | 0.28.1 | BSD-3-Clause |
| **psycopg** | 3.3.4 | **LGPL-3.0-only** |
| **psycopg-binary** | 3.3.4 | **LGPL-3.0-only** |
| **python-multipart** | 0.0.31 | **Apache-2.0** |
| **redis** | 8.0.0 | MIT |
| **requests** | 2.34.2 | **Apache-2.0** |
| **uvicorn** | 0.49.0 | BSD-3-Clause |
| Mako | 1.3.12 | MIT |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT |
| anyio | 4.13.0 | MIT |
| certifi | 2026.5.20 | MPL-2.0 |
| cffi | 2.0.0 | MIT |
| charset-normalizer | 3.4.7 | MIT |
| click | 8.4.1 | BSD-3-Clause |
| greenlet | 3.5.1 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.8.0 | MIT |
| idna | 3.18 | BSD-3-Clause |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| pydantic_core | 2.46.4 | MIT |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| starlette | 1.2.1 | BSD-3-Clause |
| typing-inspection | 0.4.2 | MIT |
| typing_extensions | 4.15.0 | PSF-2.0 |
| tzlocal | 5.3.1 | MIT |
| urllib3 | 2.7.0 | MIT |
| uvloop | 0.22.1 | Apache-2.0; MIT (Dual) |
| watchfiles | 1.2.0 | MIT |
| websockets | 16.0 | BSD-3-Clause |

**Apache-2.0 (NOTICE-Pflicht):** `bcrypt`, `requests`,
`python-multipart`, `cryptography` (Dual Apache-2.0 / BSD-3-Clause).
Siehe Abschnitt „Auflagen & Hinweise“.

**LGPL-3.0 (Quelltext mitliefern):** `psycopg` und `psycopg-binary`.
Kompatibel mit GPL-3.0, aber der unveränderte LGPL-Quelltext bzw. ein
schriftliches Angebot dazu muss verfügbar gehalten werden. Siehe
Abschnitt „Auflagen & Hinweise“.

---

## 2. Go — Agent (`apps/agent/`)

Quelle: `go-licenses report ./cmd/adminhelper-agent`, separat für
`GOOS=linux` und `GOOS=windows` (der Agent baut für beide Plattformen).
Die internen `adminhelper-agent/...`-Pakete sind eigener Code (GPL-3.0)
und hier weggelassen.

### In Linux- und Windows-Builds gelinkt

| Modul | Lizenz | Plattform |
|-------|--------|-----------|
| github.com/shirou/gopsutil/v4 | BSD-3-Clause | linux + windows |
| github.com/spf13/cobra | **Apache-2.0** | linux + windows |
| github.com/spf13/pflag | BSD-3-Clause | linux + windows |
| golang.org/x/sys | BSD-3-Clause | linux + windows |
| github.com/tklauser/go-sysconf | BSD-3-Clause | nur linux |
| github.com/tklauser/numcpus | **Apache-2.0** | nur linux |
| github.com/go-ole/go-ole | MIT | nur windows |
| github.com/yusufpapurcu/wmi | MIT | nur windows |
| github.com/inconshreveable/mousetrap | **Apache-2.0** | nur windows |
| github.com/ebitengine/purego | **Apache-2.0** OR MIT | (via gopsutil, plattformabhängig) |

### In `go.mod` deklariert, plattformabhängig nicht in den Build gelinkt

Diese transitiven Abhängigkeiten zieht `gopsutil` nur auf
macOS/Plan9/AIX; bei den Linux-/Windows-Builds werden sie nicht
einkompiliert, sind aber im Modulgraph deklariert:

| Modul | Lizenz |
|-------|--------|
| github.com/lufia/plan9stats | BSD-3-Clause |
| github.com/power-devops/perfstat | MIT |

**Apache-2.0 (NOTICE-Pflicht):** `cobra`, `numcpus`, `mousetrap`,
`purego`. Siehe Abschnitt „Auflagen & Hinweise“.

---

## 3. Rust — Desktop-Client (`apps/desktop/src-tauri/`, Tauri 2)

Quelle: `cargo metadata` über `Cargo.lock`. Der vollständige Graph
umfasst 607 Crates; eine Crate-für-Crate-Auflistung ist nicht praktikabel
und größtenteils transitiv unter Tauri/reqwest. Unten die **direkten**
Abhängigkeiten plus die aggregierte Lizenzverteilung des Gesamtgraphen.

### Direkte Abhängigkeiten (`Cargo.toml`)

| Crate | Lizenz |
|-------|--------|
| serde | MIT OR **Apache-2.0** |
| serde_json | MIT OR **Apache-2.0** |
| tauri | **Apache-2.0** OR MIT |
| tauri-build (build-dep) | **Apache-2.0** OR MIT |
| tauri-plugin-shell | **Apache-2.0** OR MIT |
| reqwest | MIT OR **Apache-2.0** |
| url | MIT OR **Apache-2.0** |
| open | MIT |
| keyring | MIT OR **Apache-2.0** |
| chrono | MIT OR **Apache-2.0** |
| windows (nur Windows) | MIT OR **Apache-2.0** |

### Lizenzverteilung über den gesamten Crate-Graphen (607 Crates)

| Anzahl | Lizenz(-Ausdruck) |
|-------:|-------------------|
| 284 | MIT OR Apache-2.0 |
| 137 | MIT |
| 53 | Apache-2.0 OR MIT |
| 28 | MIT/Apache-2.0 |
| 20 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT |
| 18 | Unicode-3.0 |
| 10 | Zlib OR Apache-2.0 OR MIT |
| 8 | MPL-2.0 |
| 5 | Unlicense OR MIT |
| 4 | BSD-3-Clause |
| 4 | Apache-2.0 OR ISC OR MIT |
| 3 | Apache-2.0/MIT |
| 3 | ISC |
| 3 | Apache-2.0 |
| 2 | Zlib |
| 2 | BSD-3-Clause OR Apache-2.0 |
| 2 | BSD-3-Clause OR MIT OR Apache-2.0 |
| 2 | MIT OR Apache-2.0 OR LGPL-2.1-or-later |
| 2 | Unlicense/MIT |
| 2 | BSD-2-Clause OR Apache-2.0 OR MIT |
| 1 | je: 0BSD OR MIT OR Apache-2.0 · BSD-3-Clause AND MIT · BSD-3-Clause/MIT · Apache-2.0 AND MIT · CC0-1.0 OR MIT-0 OR Apache-2.0 · (Apache-2.0 OR MIT) AND BSD-3-Clause · Apache-2.0 / MIT · MIT / Apache-2.0 · MIT OR Zlib OR Apache-2.0 · MIT OR Apache-2.0 OR Zlib · Apache-2.0 AND ISC · Apache-2.0 OR BSL-1.0 · Apache-2.0 WITH LLVM-exception · (MIT OR Apache-2.0) AND Unicode-3.0 |

Anmerkungen:
- Der überwiegende Teil ist Dual MIT/Apache-2.0; für GPL-Distribution
  kann jeweils der MIT-Zweig gewählt werden, wodurch die Apache-NOTICE-
  Pflicht für diese Crates entfällt. Tauli selbst (`tauri`,
  `tauri-build`, `tauri-plugin-shell`) und `reqwest`/`windows-rs` werden
  hier aber bewusst im **Apache-2.0-Zweig** geführt (vgl.
  Kompatibilitätsprüfung) — damit greift die NOTICE-Pflicht.
- `Unicode-3.0` (u. a. `icu`-Crates) und `MPL-2.0` (z. B.
  `webpki-roots`) sind GPL-3.0-kompatibel und ohne weitere Auflage außer
  Lizenztext-Mitlieferung.
- Eine Crate meldet `UNKNOWN` — das ist das eigene Desktop-Crate
  `adminhelper` (GPL-3.0), kein Drittanbieter.

**Apache-2.0 (NOTICE-Pflicht):** `tauri`, `tauri-build`,
`tauri-plugin-shell`, `reqwest`, `windows` (windows-rs) im
Apache-Zweig. Siehe Abschnitt „Auflagen & Hinweise“.

---

## 4. JavaScript / TypeScript — Frontends

Zwei npm-Workspaces. Das Desktop-Frontend (`apps/desktop/ui/`) wird in das
Tauri-Bundle gebaut; das Admin-Panel (`apps/web/`) ist die
Web-Oberfläche. Quelle: `license-checker` (für `apps/desktop/ui/`, dessen
`node_modules` installiert ist) bzw. Manifest für `apps/web/`.

### `apps/desktop/ui/` — Laufzeit-/Bundle-Abhängigkeiten (`dependencies`)

Nur diese landen tatsächlich im ausgelieferten Bundle:

| Paket | Version | Lizenz |
|-------|---------|--------|
| @tauri-apps/api | 2.10.1 | **Apache-2.0** OR MIT |
| @tauri-apps/plugin-shell | 2.3.5 | MIT OR **Apache-2.0** |
| uplot | 1.6.32 | MIT |

### `apps/desktop/ui/` — Build-/Dev-Toolchain (`devDependencies`, transitiv)

Build-Zeit-Werkzeuge (Vite, Svelte, ESLint, Vitest, TypeScript …),
nicht im ausgelieferten Artefakt enthalten. Aggregierte Verteilung über
den vollständigen `node_modules`-Baum:

| Anzahl | Lizenz |
|-------:|--------|
| 202 | MIT |
| 19 | Apache-2.0 |
| 10 | BSD-2-Clause |
| 10 | ISC |
| 3 | BSD-3-Clause |
| 3 | MPL-2.0 |
| 2 | MIT-0 |
| 1 | je: Apache-2.0 OR MIT · MIT OR Apache-2.0 · Python-2.0 · BlueOak-1.0.0 · CC0-1.0 |
| 1 | UNLICENSED (eigenes Paket `adminhelper-desktop`, kein Drittanbieter) |

### `apps/web/` (Admin-Panel)

`node_modules` zum Stichtag nicht installiert; Liste kuratiert aus
`apps/web/package.json`. Laufzeit-Abhängigkeit:

| Paket | Lizenz |
|-------|--------|
| uplot | MIT |

Build-/Dev-Toolchain (`devDependencies`): Vite, Svelte,
`svelte-check`, ESLint + `typescript-eslint`, `eslint-plugin-svelte`,
Prettier (+ `prettier-plugin-svelte`), TypeScript, Vitest,
`@playwright/test`, `globals`, `@tsconfig/svelte`, `@types/node`.
Diese Pakete sind durchgängig MIT- bzw. ISC/BSD-lizenziert (analog zur
`apps/desktop/ui/`-Toolchain) und nicht Teil des ausgelieferten Artefakts.

**Apache-2.0 (NOTICE-Pflicht):** `@tauri-apps/api`,
`@tauri-apps/plugin-shell` (jeweils im Apache-Zweig). Siehe Abschnitt
„Auflagen & Hinweise“.

---

## Auflagen & Hinweise

### Apache-2.0 — NOTICE-Pflicht

Folgende gelinkte Abhängigkeiten stehen (mindestens wahlweise) unter
Apache-2.0. § 4(d) der Apache-2.0 verlangt, alle mitgelieferten
`NOTICE`-Dateien dieser Projekte in der Distribution weiterzugeben:

- **Python:** `bcrypt`, `requests`, `python-multipart`, `cryptography`
- **Go:** `cobra`, `numcpus`, `mousetrap`, `purego`
- **Rust:** `tauri`, `tauri-build`, `tauri-plugin-shell`, `reqwest`,
  `windows` (windows-rs)
- **npm:** `@tauri-apps/api`, `@tauri-apps/plugin-shell`

Sofern diese Projekte eine `NOTICE`-Datei mitliefern, gehört deren
Inhalt unverändert in die Distribution (z. B. gebündelt in dieser Datei
oder als beigelegte `NOTICE`). Bei vielen der Dual-lizenzierten
Rust-/npm-Pakete ließe sich alternativ der MIT-Zweig wählen, um die
Pflicht zu vermeiden; für die o. g. Pakete wird laut
Kompatibilitätsprüfung jedoch der Apache-Zweig geführt.

### LGPL-3.0 — psycopg

`psycopg` und `psycopg-binary` stehen unter **LGPL-3.0-only**. Das ist
mit GPL-3.0-or-later kompatibel. Auflage: Der (unveränderte)
LGPL-lizenzierte Quelltext muss mitgeliefert oder per schriftlichem
Angebot zugänglich gemacht werden, und Endnutzer müssen die
psycopg-Komponente durch eine eigene Version ersetzen können (bei
dynamischem Linken via PyPI-Bezug gegeben).

### MPL-2.0 / Unicode-3.0 / BSD / ISC

`MPL-2.0` (z. B. `certifi`, `webpki-roots`), `Unicode-3.0` (ICU-Crates)
sowie die diversen BSD-/ISC-/MIT-Lizenzen sind GPL-3.0-kompatibel. Es
genügt, den jeweiligen Lizenztext bzw. Copyright-Hinweis in der
Distribution mitzuführen.

---

## Reproduktion

```sh
# Python (server + monitoring)
python3 -m venv /tmp/lic && /tmp/lic/bin/pip install pip-licenses \
  && /tmp/lic/bin/pip install -r server/requirements.txt \
  && /tmp/lic/bin/pip-licenses --format=markdown --order=license

# Go (Agent) — je Zielplattform
go install github.com/google/go-licenses@latest
( cd apps/agent && GOOS=linux   "$(go env GOPATH)"/bin/go-licenses report ./cmd/adminhelper-agent )
( cd apps/agent && GOOS=windows "$(go env GOPATH)"/bin/go-licenses report ./cmd/adminhelper-agent )

# Rust (Desktop)
( cd apps/desktop/src-tauri && cargo metadata --format-version 1 )

# npm (Desktop-Frontend)
( cd apps/desktop/ui && npx license-checker --production --summary )
```
