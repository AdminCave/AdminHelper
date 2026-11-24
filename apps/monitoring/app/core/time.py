# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Time helpers.

Every DateTime column in this service is tz-naive UTC (Postgres ``timestamp
without time zone``). Writing or comparing a tz-aware datetime against them makes
the result depend on the container's session timezone, so all call sites use
``utcnow_naive()`` instead of re-implementing
``datetime.now(timezone.utc).replace(tzinfo=None)`` — or, worse, a bare
``datetime.now(timezone.utc)`` that silently stays aware (audit 2.29). Since R-0218
every session of the service's engine runs in UTC (``app.core.database``); the
helpers stay the explicit form, which does not depend on the session. They come
from ``ah_common.time``, shared with the server.
"""

from ah_common.time import iso_utc, utc_now_sql, utcnow_naive

__all__ = ["iso_utc", "utc_now_sql", "utcnow_naive"]
