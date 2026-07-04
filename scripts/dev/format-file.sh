#!/usr/bin/env bash
# SPDX-FileCopyrightText: Kevin Stenzel
# SPDX-License-Identifier: GPL-3.0-or-later
#
# format-file.sh — formatiert EINE Datei nach Endung, best-effort, IMMER Exit 0.
# Zweck: als PostToolUse-Hook (Edit/Write) die gerade geänderte Datei sofort
# projektkonform formatieren, damit der autonome Loop keine Turns an Formatierung
# verliert. Standalone nutzbar: `bash scripts/dev/format-file.sh <datei>`.
#
# Dateipfad kommt entweder als $1 ODER (Hook-Modus) aus dem PostToolUse-JSON auf stdin.
set -u

f="${1:-}"
if [ -z "$f" ] && [ ! -t 0 ]; then
  # Pfad aus dem Hook-JSON ziehen (tool_input.file_path), tolerant geparst.
  f="$(cat 2>/dev/null \
    | grep -oE '"file_path"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 \
    | sed -E 's/.*"file_path"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
fi

# Kein Pfad oder Datei existiert nicht → still nichts tun.
{ [ -z "$f" ] || [ ! -f "$f" ]; } && exit 0

case "$f" in
  *.py)
    command -v ruff >/dev/null 2>&1 && ruff format -q "$f" >/dev/null 2>&1
    ;;
  *.go)
    command -v gofmt >/dev/null 2>&1 && gofmt -w "$f" >/dev/null 2>&1
    ;;
  *.ts|*.tsx|*.js|*.mjs|*.cjs|*.svelte|*.json|*.css|*.html)
    command -v prettier >/dev/null 2>&1 && prettier --write "$f" >/dev/null 2>&1
    ;;
  *.rs)
    command -v rustfmt >/dev/null 2>&1 && rustfmt --edition 2021 "$f" >/dev/null 2>&1
    ;;
esac

exit 0
