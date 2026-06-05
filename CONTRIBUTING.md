# Contributing to AdminHelper

Thanks for your interest in AdminHelper!

## Ground rules

- **License:** AdminHelper is **GPL-3.0-or-later**. By contributing you agree
  your contributions are licensed under the same terms. Every new source file
  (`.py` `.go` `.rs` `.ts` `.svelte` `.js`/`.mjs`) needs a REUSE-compliant SPDX
  header (`SPDX-FileCopyrightText` + `SPDX-License-Identifier: GPL-3.0-or-later`).
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`).
- **Tests must pass.** Before opening a PR, run the checks for the component you
  touched (mirrored in `.github/workflows/ci.yml`):
  - Server / Monitoring (`apps/server/`, `apps/monitoring/`): `pytest -q`
  - Go agent (`apps/agent/`): `gofmt -l .`, `go vet ./...`, `go test ./...`
  - Desktop UI / Web frontend (`apps/desktop/ui/`, `apps/web/`): `npm run check`,
    `npm run lint`, `npm run test` (frontend additionally `npm run test:e2e`)
  - Desktop backend (`apps/desktop/src-tauri/`): `cargo fmt --check`,
    `cargo clippy -- -D warnings`, `cargo test`
- **Docs:** user-facing changes must update `docs/` in **both** languages
  (DE + EN) and the relevant `README.md` / `DEVELOPMENT.md` sections, in the
  same commit as the code change.

## Local development

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for the local setup (Docker Compose,
component layout, build commands).

## Security

Please report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).
