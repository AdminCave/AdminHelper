# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Time helpers.

Two DateTime storage conventions coexist in the schema (audit F7):
  * tz-naive UTC — the older tables (users.tokens_valid_after,
    enrollment_tokens.expires_at, frp, servers, hooks, connections). Store
    naive-UTC via ``utcnow_naive()`` instead of re-implementing
    ``datetime.now(timezone.utc).replace(tzinfo=None)`` at each call site.
  * timezone-aware — the newer audit_log and notification* tables use
    ``DateTime(timezone=True)`` and store aware datetimes.

Comparing a naive with an aware datetime raises TypeError, so a call site must
know which world a column belongs to. New tz-naive columns should use these helpers
(``utcnow_naive()`` in Python, ``utc_now_sql()`` for a column server_default); both and
``iso_utc`` come from ``ah_common.time``, shared with the monitoring service.
"""

from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema

from ah_common.time import iso_utc, utc_now_sql, utcnow_naive

__all__ = ["UtcDatetime", "iso_utc", "utc_now_sql", "utcnow_naive"]

# A response field that is written with iso_utc(). The JSON schema stays
# string/date-time: a bare PlainSerializer would turn it into a plain string.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(iso_utc, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]
