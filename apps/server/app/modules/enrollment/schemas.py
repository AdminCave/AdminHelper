# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Literal, Optional

from pydantic import BaseModel

from app.core.time import UtcDatetime


class EnrollmentGrantOut(BaseModel):
    """A one-time enrollment token, redeemable at the ca-issuer's enroll plane."""

    token: str
    subjectId: str
    scope: str
    browser: bool
    enrollPort: int
    expiresAt: Optional[str]


ExpiryStatus = Literal["ok", "warning", "critical"]


class InfraCertificateOut(BaseModel):
    """A certificate of the infrastructure, as the ca-issuer recorded it at its last start."""

    name: str  # root | intermediate:<scope> | gateway | frps
    subject: str
    fingerprint: str
    not_after: UtcDatetime
    days_left: int  # whole days, negative once expired
    status: ExpiryStatus


class AgentCertificateOut(BaseModel):
    """The newest certificate of an agent line that is not revoked."""

    server_id: str
    server_name: Optional[str] = None  # None once the server is deleted
    fingerprint: str
    not_after: UtcDatetime
    days_left: int
    status: ExpiryStatus


class CertificateOverviewOut(BaseModel):
    infrastructure: list[InfraCertificateOut]
    agents: list[AgentCertificateOut]
