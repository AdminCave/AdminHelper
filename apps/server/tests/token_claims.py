# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Claims for tests that issue tokens by hand. Tokens name their account by id (`uid`); the
tests name it by username, so the id comes from the running test's session (set by the
db_session fixture). A name without an account gets an id no account has."""

from app.modules.users.models import User

NO_SUCH_ACCOUNT = 2**31 - 1

_current: dict = {}


def use_session(session) -> None:
    _current["db"] = session


def claims_for(username: str) -> dict:
    session = _current.get("db")
    user = session.query(User).filter(User.username == username).first() if session else None
    return {"sub": username, "uid": user.id if user is not None else NO_SUCH_ACCOUNT}
