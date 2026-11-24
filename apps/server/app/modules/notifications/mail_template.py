# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mail template an admin keeps in the panel (R-1533): loaded from the database and set
for the mails sent inside `using`/`applied`. The renderer is ah_common.mail_template, shared
with the monitoring, and is re-exported here for the hub's modules."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

from ah_common.mail_template import (
    DEFAULT,
    LOGO_CID,
    PLACEHOLDERS,
    Mail,
    Template,
    compose,
    format_time,
    unknown,
)

__all__ = [
    "DEFAULT",
    "LOGO_CID",
    "PLACEHOLDERS",
    "Mail",
    "Template",
    "applied",
    "compose",
    "current",
    "format_time",
    "load",
    "unknown",
    "using",
]


def load(db: Session) -> Template:
    """The template of the panel, DEFAULT without a row."""
    from app.modules.notifications.models import NotifyMailTemplate

    row = db.get(NotifyMailTemplate, 1)
    if row is None:
        return DEFAULT
    return Template(
        subject_prefix=row.subject_prefix or "",
        from_name=row.from_name or "",
        html=row.html or "",
        text=row.text or "",
        logo=row.logo,
        logo_type=row.logo_type,
    )


_current: ContextVar[Template | None] = ContextVar("notify_mail_template", default=None)


@contextmanager
def applied(template: Template) -> Iterator[Template]:
    """The mails sent inside take `template`."""
    token = _current.set(template)
    try:
        yield template
    finally:
        _current.reset(token)


@contextmanager
def using(db: Session) -> Iterator[Template]:
    """The mails sent inside take the template of the panel."""
    with applied(load(db)) as template:
        yield template


def current() -> Template:
    template = _current.get()
    return template if template is not None else DEFAULT
