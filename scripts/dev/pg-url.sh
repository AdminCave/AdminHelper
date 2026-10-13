#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# pg-url.sh — one reading of AH_TEST_DB for the two scripts that hand it to libpq:
# lane.sh (lane_db) and builder-home.sh (pg). Sourced, never run. Each caller
# rewrites the scheme its own way first and prints the reason with its own prefix.
#
#   pg_url_split <url> <forms>   -> 0: PG_URL_OUT (the URL without the password)
#                                      PG_URL_PASS (the password, decoded)
#                                   1: PG_URL_ERR (why not; never a value)
#
# <forms> names the URL forms the caller takes; it ends the message for a URL that
# is no postgresql:// one.
#
# The password travels in the environment (PGPASSWORD), not in an argument: every
# local user can read a process's arguments (/proc/<pid>/cmdline), only its owner
# its environment. The URL percent-encodes the password, PGPASSWORD takes it raw.
# The password runs to the first @, across a /, the way SQLAlchemy reads
# AH_TEST_DB (sqlalchemy/engine/url.py): a password the suites take out of the URL
# is one these scripts take out too.

# The PG_URL_* results are the caller's to read.
# shellcheck disable=SC2034
pg_url_split() {
  # Bytes, not the caller's characters: the patterns below must find the same @ and :
  # under any locale, and a multibyte one can read a byte after a character as part
  # of it. The UTF-8 checks name their encoding themselves.
  local LC_ALL=C
  local url="$1" forms="$2" pass="" split=0
  PG_URL_OUT="" PG_URL_PASS="" PG_URL_ERR=""
  # SQLAlchemy reads AH_TEST_DB as a UTF-8 string: a URL that is no UTF-8 is refused first.
  if ! printf '%s' "$url" | iconv -f UTF-8 -t UTF-16LE >/dev/null 2>&1; then
    PG_URL_ERR="AH_TEST_DB is no UTF-8"
    return 1
  fi
  if [[ "$url" =~ ^(postgresql://[^:@/]+):([^@]*)@(.*)$ ]]; then
    split=1
    local raw="${BASH_REMATCH[2]}" ch hex='^%([0123456789abcdefABCDEF]{2})'
    url="${BASH_REMATCH[1]}@${BASH_REMATCH[3]}"
    # Decoded as urllib.parse.unquote does it, which SQLAlchemy uses: %XX with two
    # hex digits becomes that byte, every other % stays (50%zz, a trailing %). The
    # class is spelled out: a range matches more under de_DE.UTF-8. printf -v keeps
    # a decoded newline at the end, which $(…) would cut off.
    while [ -n "$raw" ]; do
      if [[ "$raw" =~ $hex ]]; then
        # A NUL cannot travel in PGPASSWORD; bash would drop it without a word.
        if [ "${BASH_REMATCH[1]}" = 00 ]; then
          PG_URL_ERR="AH_TEST_DB has a password with a NUL byte"
          return 1
        fi
        printf -v ch "\\x${BASH_REMATCH[1]}"; pass+="$ch"; raw="${raw:3}"
      else
        pass+="${raw:0:1}"; raw="${raw:1}"
      fi
    done
    # SQLAlchemy reads bytes that are no UTF-8 as U+FFFD: that would be another
    # password than the one in the URL, so neither is sent.
    if ! printf '%s' "$pass" | iconv -f UTF-8 -t UTF-16LE >/dev/null 2>&1; then
      PG_URL_ERR="AH_TEST_DB has a password that is no UTF-8 once decoded"
      return 1
    fi
  fi
  # A user:password the pattern did not take apart would go into an argument
  # unchanged: stop before either program runs. The part before the password may
  # hold an @ of its own: SQLAlchemy reads ah@corp:<password>@host as user ah@corp,
  # the pattern above does not.
  if [[ "$url" =~ ^[^/]*//[^/]*:[^/@]*@ ]]; then
    PG_URL_ERR="AH_TEST_DB has a form whose password cannot be taken out of the URL"
    return 1
  fi
  # Where the pattern took nothing apart, SQLAlchemy may still read a password: the
  # user up to the first :, the password up to the first @, across a /
  # (sqlalchemy/engine/url.py). ah@corp:<pass/word>@host and :<pass/word>@host are
  # two such forms; after a split the first @ is gone, and with it that reading.
  if [ "$split" = 0 ] && [[ "$url" =~ ^[^/]*//[^:/]*:[^@]*@ ]]; then
    PG_URL_ERR="AH_TEST_DB has a form whose password cannot be taken out of the URL"
    return 1
  fi
  # Nor one in the query: libpq takes ?password= too, and it would reach the
  # arguments the same way.
  local query_pw='[?&]password='
  if [[ "$url" =~ $query_pw ]]; then
    PG_URL_ERR="AH_TEST_DB carries its password in the query; write it as user:password@ before the host"
    return 1
  fi
  # The other keys whose value is a secret of its own (libpq, Parameter Key Words):
  # the passphrase of the client key, the OAuth client secret, and the SCRAM keys
  # (the client key alone signs in, RFC 5802). In any spelling, password included:
  # whether libpq quotes the value of a key it does not know is not verified.
  local query_secret='[?&](password|sslpassword|oauth_client_secret|scram_client_key|scram_server_key)='
  if [[ "${url,,}" =~ $query_secret ]]; then
    PG_URL_ERR="AH_TEST_DB carries a secret in its query (${BASH_REMATCH[1]}=); it is not passed on"
    return 1
  fi
  # libpq decodes the keys of the query too, so pass%77ord= is a password as well:
  # no percent sign in a key at all.
  local query_key_pct='[?&][^=&]*%[^=&]*='
  if [[ "$url" =~ $query_key_pct ]]; then
    PG_URL_ERR="AH_TEST_DB has a percent-encoded key in its query; write the keys plain"
    return 1
  fi
  # Only a postgresql:// URL goes on to libpq. Any other (the key=value form of
  # libpq, a scheme without //) ends here, after the refusals above, which keep
  # their own messages.
  case "$url" in
    postgresql://*) ;;
    *) PG_URL_ERR="AH_TEST_DB is no postgresql:// URL ($forms)"
       return 1 ;;
  esac
  PG_URL_OUT="$url" PG_URL_PASS="$pass"
  return 0
}
