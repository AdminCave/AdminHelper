# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

from pydantic import BaseModel


class EnrollmentGrantOut(BaseModel):
    """A one-time enrollment token, redeemable at the ca-issuer's enroll plane."""

    token: str
    subjectId: str
    scope: str
    browser: bool
    enrollPort: int
    expiresAt: Optional[str]
