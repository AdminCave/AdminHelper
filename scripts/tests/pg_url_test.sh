#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# pg_url_test.sh — hermetic test for scripts/dev/pg-url.sh, the one reading of
# AH_TEST_DB that lane.sh (lane_db) and builder-home.sh (pg) share. One table of
# URLs: the ones it takes, with the URL and password it must hand on, and the ones
# it refuses, with the reason and without the value. Every password it takes is
# held against urllib.parse.unquote, the decoding SQLAlchemy uses. All values are
# placeholders; nothing reaches a database.
#
# Run: bash scripts/tests/pg_url_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
HELPER="$REPO_ROOT/scripts/dev/pg-url.sh"
# shellcheck source=scripts/dev/pg-url.sh
. "$HELPER"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
for t in python3 iconv; do
  command -v "$t" >/dev/null 2>&1 || { echo "SKIP: $t not available"; exit 75; }
done
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FORMS="the caller's forms"

# unquoted <raw> -> the password urllib.parse.unquote makes of it, newline kept
unquoted() {
  local out
  out="$(python3 -c 'import sys; from urllib.parse import unquote; sys.stdout.write(unquote(sys.argv[1]) + "x")' "$1")"
  printf '%s' "${out%x}"
}

# accepts <label> <url> <url without the password> <the password as the URL writes it>
accepts() {
  local label="$1" url="$2" want_url="$3" raw="$4" want rc
  want="$(unquoted "$raw"; printf x)"; want="${want%x}"
  pg_url_split "$url" "$FORMS"; rc=$?
  [ $rc -eq 0 ] && [ "$PG_URL_OUT" = "$want_url" ] && [ "$PG_URL_PASS" = "$want" ] && [ -z "$PG_URL_ERR" ] \
    && ok "$label: taken, the password as urllib decodes it" \
    || bad "$label: rc=$rc url=$PG_URL_OUT err=$PG_URL_ERR"
}

# refuses <label> <url> <what the reason says> <the value it must not name>
refuses() {
  local label="$1" url="$2" says="$3" value="$4" rc
  pg_url_split "$url" "$FORMS"; rc=$?
  [ $rc -eq 1 ] && grep -qF -- "$says" <<<"$PG_URL_ERR" && ! grep -qF -- "$value" <<<"$PG_URL_ERR" \
    && [ -z "$PG_URL_OUT" ] && [ -z "$PG_URL_PASS" ] \
    && ok "$label: refused, the reason names no value" \
    || bad "$label: rc=$rc err=$(sed "s/$value/<value>/g" <<<"$PG_URL_ERR")"
}

echo "── taken ──"
accepts "a port"                "postgresql://ah:plchold@localhost:5432/adminhelper_test" "postgresql://ah@localhost:5432/adminhelper_test" "plchold"
accepts "no port"               "postgresql://ah:plchold@localhost/adminhelper_test"      "postgresql://ah@localhost/adminhelper_test"      "plchold"
accepts "IPv6"                  "postgresql://ah:plchold@[::1]:5432/adminhelper_test"     "postgresql://ah@[::1]:5432/adminhelper_test"     "plchold"
accepts "an encoded @"          "postgresql://ah:pl%40chold@localhost/adminhelper_test"   "postgresql://ah@localhost/adminhelper_test"      "pl%40chold"
accepts "a / and a :"           "postgresql://ah:pl/ch:old@localhost/adminhelper_test"    "postgresql://ah@localhost/adminhelper_test"      "pl/ch:old"
accepts "a stray and a trailing %" "postgresql://ah:pl50%zzchold%@localhost/adminhelper_test" "postgresql://ah@localhost/adminhelper_test"  "pl50%zzchold%"
accepts "an encoded letter"     "postgresql://ah:pl%41chold@localhost/adminhelper_test"   "postgresql://ah@localhost/adminhelper_test"      "pl%41chold"
accepts "an encoded newline"    "postgresql://ah:plchold%0a@localhost/adminhelper_test"   "postgresql://ah@localhost/adminhelper_test"      "plchold%0a"
accepts "an @ in the query behind a port" \
  "postgresql://ah:plchold@localhost:5432/adminhelper_test?application_name=a:b@c" \
  "postgresql://ah@localhost:5432/adminhelper_test?application_name=a:b@c" "plchold"
accepts "no password"           "postgresql://ah@localhost:5432/adminhelper_test"         "postgresql://ah@localhost:5432/adminhelper_test" ""
# What urllib makes of the stray %, spelled out, so the oracle itself is checked once.
pg_url_split "postgresql://ah:pl50%zzchold%@localhost/x" "$FORMS"
[ "$PG_URL_PASS" = "pl50%zzchold%" ] && ok "a % without two hex digits stays a %" || bad "stray %: $PG_URL_PASS"

echo "── refused ──"
refuses "a URL that is no UTF-8"  $'postgresql://ah:plchold\xff@localhost/adminhelper_test' "is no UTF-8" "plchold"
refuses "an encoded NUL"          "postgresql://ah:plc%00hold@localhost/adminhelper_test" "password with a NUL byte" "plc"
refuses "no UTF-8 once decoded"   "postgresql://ah:plc%ffhold@localhost/adminhelper_test" "no UTF-8 once decoded" "plc"
refuses "a user with an @"        "postgresql://ah@corp:plchold@localhost/adminhelper_test" "cannot be taken out of the URL" "plchold"
refuses "a user with an @ and a / in the password" "postgresql://ah@corp:pl/chold@localhost/adminhelper_test" "cannot be taken out of the URL" "chold"
refuses "no user"                 "postgresql://:plchold@localhost/adminhelper_test"      "cannot be taken out of the URL" "plchold"
refuses "no user and a / in the password" "postgresql://:pl/chold@localhost/adminhelper_test" "cannot be taken out of the URL" "chold"
refuses "a scheme the caller left" "postgres://ah:plchold@localhost/adminhelper_test"     "cannot be taken out of the URL" "plchold"
refuses "a password in the query" "postgresql://ah@localhost/adminhelper_test?password=plchold" "carries its password in the query" "plchold"
refuses "a secret key in another spelling" "postgresql://ah@localhost/adminhelper_test?SSLPassword=plchold" "carries a secret in its query (sslpassword=); it is not passed on" "plchold"
refuses "a percent-encoded key"   "postgresql://ah@localhost/adminhelper_test?pass%77ord=plchold" "percent-encoded key in its query" "plchold"
refuses "the key=value form"      "host=localhost user=ah password=plchold dbname=adminhelper_test" "is no postgresql:// URL ($FORMS)" "plchold"
refuses "a scheme without //"     "postgresql:ah:plchold@localhost/adminhelper_test"      "is no postgresql:// URL ($FORMS)" "plchold"

echo "── the caller's locale ──"
# Under GBK the byte after a character like 中 can read as part of it, and the @
# behind it with it. A GBK locale, built into the test directory; glibc reads
# LOCPATH from the environment the process starts with, so the probe runs under
# /usr/bin/env.
LOC="$WORK/locale"; mkdir -p "$LOC"
if localedef -i zh_CN -f GBK "$LOC/zh_CN.GBK" >/dev/null 2>&1; then
  for loc in C zh_CN.GBK; do
    got="$(/usr/bin/env LOCPATH="$LOC" LC_ALL="$loc" bash -c '. "$1"; pg_url_split "$2" f; printf "%s|%s|%s" "$?" "$PG_URL_OUT" "$PG_URL_PASS"' \
      _ "$HELPER" 'postgresql://ah:plchold中@localhost:5432/adminhelper_test' 2>&1)"
    [ "$got" = "0|postgresql://ah@localhost:5432/adminhelper_test|plchold中" ] \
      && ok "under LC_ALL=$loc the URL is read byte by byte" \
      || bad "LC_ALL=$loc: $(sed 's/plchold[^|]*/<pw>/g' <<<"$got")"
  done
else
  bad "localedef could not build zh_CN.GBK in $LOC: the locale case is not verified"
fi

echo "── a harness path ──"
grep -qxF 'scripts/dev/pg-url.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && grep -qxF 'scripts/tests/pg_url_test.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "the helper and its test are harness paths (builder-home.sh reads AH_TEST_DB through it)" \
  || bad "missing from harness-paths.txt"

echo ""
echo "pg_url_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
