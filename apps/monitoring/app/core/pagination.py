# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SQL-side pagination for list endpoints (audit P4, target 250-500 servers).

limit=None keeps the legacy behaviour (return all rows) so existing frontends
need no change; X-Total-Count always carries the pre-pagination total so a
future UI can paginate without a response-body change.
"""

from fastapi import Response
from sqlalchemy.orm import Query


class _MaterializedPage:
    """Holds an already-fetched row list but exposes .all() so callers can keep
    chaining paginate(...).all() unchanged."""

    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return self._rows


def paginate(query: Query, response: Response, limit: int | None, offset: int):
    """Stamps X-Total-Count on the response, then applies LIMIT/OFFSET in SQL.

    Must be called AFTER all filters (the count has to reflect the filtered
    set, not the full table) and after order_by (pages are only stable with a
    deterministic ordering).
    """
    if limit is None:
        # No pagination: the body already carries every row, so a separate
        # COUNT(*) would just double the query. Derive the total from the
        # materialized rows instead and keep X-Total-Count present.
        if offset:
            query = query.offset(offset)
        rows = query.all()
        response.headers["X-Total-Count"] = str(len(rows))
        return _MaterializedPage(rows)

    response.headers["X-Total-Count"] = str(query.order_by(None).count())
    if offset:
        query = query.offset(offset)
    return query.limit(limit)
