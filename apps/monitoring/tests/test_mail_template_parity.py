# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The monitoring's copy of the mail template renderer (R-1533) renders every case of
the parity fixtures (a copy of apps/server/tests/fixtures/mail_template_parity.json) as
the hub does: the test holds the outputs, not the two files, to each other."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import mail_template

PARITY = json.loads(
    (Path(__file__).parent / "fixtures" / "mail_template_parity.json").read_text("utf-8")
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.mark.parametrize("case", PARITY["cases"], ids=lambda c: c["name"])
def test_parity_fixtures(case):
    template = dict(case["template"])
    has_logo = template.pop("logo", False)
    got = mail_template.compose(
        mail_template.Template(
            **template,
            logo=PNG if has_logo else None,
            logo_type="image/png" if has_logo else None,
        ),
        **case["values"],
    )
    want = case["expected"]
    assert (got.subject, got.from_name, got.text, got.html) == (
        want["subject"],
        want["from_name"],
        want["text"],
        want["html"],
    )
    assert (got.logo is not None) is want["logo"]


def test_the_time_is_utc_to_the_minute_as_in_the_hub():
    when = datetime(2026, 11, 18, 13, 5, 59, tzinfo=timezone(timedelta(hours=1)))
    assert mail_template.format_time(when) == "2026-11-18 12:05 UTC"
