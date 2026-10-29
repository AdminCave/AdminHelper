# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
System-state checker.

Rates the system_state block of the agent report (Linux, report version 3): reboot
required, clock not synchronized, pending security updates, OOM kills since the last
report. The agent sends each field only when it could determine it.
"""

from __future__ import annotations

from app.checkers.agent import agent_number, join_capped

# The NTP client needs a while after boot until the kernel reports the clock as
# synchronized; rating it earlier would turn every reboot into a short alert
# (Kevin 2026-10-19: from 15 min of uptime on).
_TIME_SYNC_GRACE_SECONDS = 900


def _flag(value: object) -> bool | None:
    """A yes/no field of the block: only a JSON bool; anything else counts as missing."""
    return value if isinstance(value, bool) else None


def _count(value: object) -> int | None:
    """A counter of the block: an int that agent_number accepts (the agent sends Go ints);
    a fraction, a bool or a string counts as missing (R-0517)."""
    number = agent_number(value)
    return number if isinstance(number, int) else None


def _on(config: dict, key: str) -> bool:
    """Only a real False switches a point off; anything else keeps the default."""
    return config.get(key, True) is not False


class SystemStateChecker:
    """Checks the system state the agent reports. Never critical: each point is a
    maintenance task, not an outage.

    Config example (every point is on unless set to false):
    {
        "check_reboot": true,
        "check_time_sync": true,
        "check_security_updates": true,
        "check_oom": true
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        block = report.get("system_state")
        if not isinstance(block, dict):
            block = {}

        reboot = _flag(block.get("reboot_required"))
        synced = _flag(block.get("time_synchronized"))
        updates = _count(block.get("security_updates"))
        ooms = _count(block.get("oom_kills"))
        if reboot is None and synced is None and updates is None and ooms is None:
            # No block, or one without a single usable field (empty, only wrong types or
            # unknown keys): there is nothing to rate, so "System state OK" would claim too
            # much. Details with every value null, not None: the push path keeps the stored
            # details of a result without any, and the desktop would go on showing the
            # values of an older report.
            details = {
                "reboot_required": None,
                "time_synchronized": None,
                "security_updates": None,
                "oom_kills": None,
                "problems": [],
            }
            return "ok", "Not evaluated: no system state in report", {"_details": details}

        uptime = agent_number(report.get("uptime_seconds"))

        problems: list[str] = []
        messages: list[str] = []
        if _on(config, "check_reboot") and reboot is True:
            problems.append("reboot")
            messages.append("Reboot required")
        if (
            _on(config, "check_time_sync")
            and synced is False
            and (uptime is None or uptime >= _TIME_SYNC_GRACE_SECONDS)
        ):
            problems.append("time_sync")
            messages.append("Clock not synchronized")
        if _on(config, "check_security_updates") and updates is not None and updates > 0:
            problems.append("security_updates")
            messages.append(f"{updates} security updates pending")
        if _on(config, "check_oom") and ooms is not None and ooms > 0:
            problems.append("oom")
            messages.append(f"{ooms} OOM kills since last report")

        details = {
            "reboot_required": reboot,
            "time_synchronized": synced,
            "security_updates": updates,
            "oom_kills": ooms,
            "problems": problems,
        }
        if problems:
            return "warning", join_capped(messages, "; "), {"_details": details}
        return "ok", "System state OK", {"_details": details}
