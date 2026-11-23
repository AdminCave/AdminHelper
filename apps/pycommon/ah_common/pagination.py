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

    Must be called AFTER all filters/scoping (the count has to reflect what the
    caller may see, not the full table) and after order_by (pages are only
    stable with a deterministic ordering).
    """
    if limit is None and not offset:
        # No pagination at all: the body carries every row, so a separate
        # COUNT(*) would just double the query. Derive the total from the
        # materialized rows. (With an offset the body is a slice, so the total
        # still needs a real count — fall through.)
        rows = query.all()
        response.headers["X-Total-Count"] = str(len(rows))
        return _MaterializedPage(rows)

    response.headers["X-Total-Count"] = str(query.order_by(None).count())
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query
