# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mail template an admin keeps in the panel (R-1533): a subject prefix, a sender
name, an HTML part, a text part and an inline logo. Placeholders are replaced in one
pass, nothing else: no code from the template runs, and a value that itself reads
{{title}} stays as it is. A copy of the renderer lives in the monitoring
(apps/monitoring/app/mail_template.py); tests/fixtures/mail_template_parity.json holds
both to the same output."""

import html
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

PLACEHOLDERS = ("title", "body", "severity", "category", "time", "source", "logo")
_TOKEN = re.compile(r"\{\{\s*([A-Za-z_]+)\s*\}\}")
# The Content-ID of the inline logo; the HTML part names it as cid:logo.
LOGO_CID = "logo"


@dataclass(frozen=True)
class Template:
    subject_prefix: str = ""
    from_name: str = ""
    html: str = ""
    text: str = ""
    logo: bytes | None = field(default=None, repr=False)
    logo_type: str | None = None


# No row: the mails as before the template, plain text and the bare title as subject.
DEFAULT = Template()


@dataclass(frozen=True)
class Mail:
    subject: str
    text: str
    html: str | None
    from_name: str
    logo: bytes | None = field(default=None, repr=False)
    logo_type: str | None = None


def format_time(when: datetime) -> str:
    """{{time}}: UTC to the minute, the same in the hub and the monitoring."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def unknown(template_text: str) -> list[str]:
    """The placeholders in `template_text` this renderer does not know, in order."""
    seen = []
    for name in _TOKEN.findall(template_text):
        if name not in PLACEHOLDERS and name not in seen:
            seen.append(name)
    return seen


def _fill(template_text: str, values: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: values.get(m.group(1), m.group(0)), template_text)


def _html_values(values: dict[str, str]) -> dict[str, str]:
    escaped = {k: html.escape(v, quote=True) for k, v in values.items()}
    escaped["body"] = escaped["body"].replace("\r\n", "\n").replace("\n", "<br>\n")
    return escaped


def compose(
    template: Template,
    *,
    title: str,
    body: str,
    severity: str = "info",
    category: str = "",
    time: str = "",
    source: str = "AdminHelper",
    logo_src: str = f"cid:{LOGO_CID}",
) -> Mail:
    """The mail for one message. `logo_src` is what {{logo}} becomes in the HTML part:
    the inline part in a mail, a data: URL in the preview."""
    values = {
        "title": title,
        "body": body,
        "severity": severity,
        "category": category,
        "time": time,
        "source": source,
    }
    subject = f"{template.subject_prefix} {title}" if template.subject_prefix else title
    text = _fill(template.text, {**values, "logo": ""}) if template.text else body
    rendered_html = None
    if template.html:
        has_logo = template.logo is not None
        rendered_html = _fill(
            template.html, {**_html_values(values), "logo": logo_src if has_logo else ""}
        )
    return Mail(
        subject=subject,
        text=text,
        html=rendered_html,
        from_name=template.from_name,
        logo=template.logo if rendered_html is not None else None,
        logo_type=template.logo_type,
    )


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
