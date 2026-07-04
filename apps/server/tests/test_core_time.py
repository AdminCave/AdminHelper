# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""utcnow_naive (1.31): the tz-naive UTC storage convention, centralized."""

from datetime import datetime, timezone

from app.core.time import utcnow_naive


def test_utcnow_naive_is_naive_and_utc():
    now = utcnow_naive()
    # Convention: tz-naive (comparing with an aware datetime would raise).
    assert now.tzinfo is None
    # And it is UTC "now": within a few seconds of aware-UTC stripped of tzinfo.
    delta = abs((datetime.now(timezone.utc).replace(tzinfo=None) - now).total_seconds())
    assert delta < 5
