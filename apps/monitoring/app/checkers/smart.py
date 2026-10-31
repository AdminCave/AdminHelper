# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
SMART disk health checker.

Evaluates SMART data from the agent report (push-only).
Supports ATA (HDD + SSD) and NVMe protocols.
Without disks the agent sends smart_absent with the reason instead of a smart key
— that's OK, not an error; the message names the reason.
"""

from __future__ import annotations

from app.checkers.agent import (
    agent_number,
    cap_agent_text,
    capped_objects,
    entry_number,
    entry_text,
    join_capped,
)
from app.core.victoria import safe_metric_part

# NVMe critical_warning Bit-Feld laut NVMe Base Spec 1.4, Figure 94.
NVME_CRITICAL_BITS = {
    0x01: "spare_capacity_below_threshold",
    0x02: "temperature_above_threshold",
    0x04: "nvm_subsystem_reliability_degraded",
    0x08: "media_read_only",
    0x10: "volatile_memory_backup_failed",
    0x20: "persistent_memory_region_unreliable",
}


def _decode_nvme_critical_warning(bits: int) -> list[str]:
    """Translates the NVMe critical_warning bit field into readable reasons."""
    if not bits:
        return []
    return [name for mask, name in NVME_CRITICAL_BITS.items() if bits & mask]


_SEVERITY_RANK = {"ok": 0, "warning": 1, "critical": 2}


def _worse(a: str, b: str) -> str:
    """The more severe of two SMART categories (critical > warning > ok)."""
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


# smart_absent.reason codes of the agent (R-0419). scan_failed also covers found
# devices of which none gave readable SMART data, hence "query", not "scan".
_ABSENT_MESSAGES = {
    "not_installed": "No SMART data: smartctl is not installed",
    "scan_failed": "No SMART data: the SMART query failed",
    "no_devices": "No SMART data: no SMART-capable devices found",
}


def _absent_result(report: dict) -> tuple[str, str, dict | None]:
    # No disk — not an error; smart_absent says why.
    absent = report.get("smart_absent")
    reason = absent.get("reason") if isinstance(absent, dict) else None
    # The str check keeps an unhashable reason (a list) out of the dict lookup.
    if isinstance(reason, str) and reason in _ABSENT_MESSAGES:
        # Details, not None: the push path keeps stored details of a result
        # without any, and the desktop would go on showing the old disks.
        return "ok", _ABSENT_MESSAGES[reason], {"_details": {"absent": reason}}
    # An agent before R-0419 or an unknown reason.
    return "ok", "No SMART data (VM or smartctl not available)", None


def _smart_thresholds(config: dict) -> tuple[dict, dict]:
    """(attribute thresholds, (warn, crit) temperature per kind class)."""
    thresholds = {
        "reallocated_warn": config.get("reallocated_warn", 1),
        "reallocated_crit": config.get("reallocated_crit", 10),
        "pending_warn": config.get("pending_warn", 1),
        "pending_crit": config.get("pending_crit", 5),
        "nvme_spare_warn": config.get("nvme_spare_warn", 20),
        "nvme_spare_crit": config.get("nvme_spare_crit", 10),
        "nvme_used_warn": config.get("nvme_used_warn", 90),
        "nvme_used_crit": config.get("nvme_used_crit", 100),
    }
    temp_thresholds = {
        "HDD": (config.get("temp_hdd_warn", 55), config.get("temp_hdd_crit", 60)),
        "SATA-SSD": (config.get("temp_ssd_warn", 60), config.get("temp_ssd_crit", 70)),
        "NVMe": (config.get("temp_nvme_warn", 65), config.get("temp_nvme_crit", 75)),
    }
    return thresholds, temp_thresholds


def _check_common(
    disk: dict, label: str, passed: bool, ec: int, temp: int, temp_warn, temp_crit
) -> tuple[str, list[str], list[str]]:
    """Checks for every protocol: SMART verdict, uncorrectables, the smartctl exit
    code and the temperature. Returns (category, critical, warning) like _check_ata."""
    crit, warn = [], []
    category = "ok"

    # Universal checks (ATA + NVMe)
    if not passed:
        crit.append(f"{label}: SMART FAILED")
        category = "critical"

    reported_uncorrect = entry_number(disk, "reported_uncorrect", 0)
    if reported_uncorrect > 0:
        crit.append(f"{label}: {reported_uncorrect} reported uncorrectable")
        category = "critical"

    uncorrectable = entry_number(disk, "uncorrectable", 0)
    if uncorrectable > 0:
        crit.append(f"{label}: {uncorrectable} offline uncorrectable")
        category = "critical"

    # Evaluate smartctl exit code (bit flags).
    # Bit 0x10 = prefail attribute below threshold → critical.
    # Bits 0x20 (past), 0x40 (error log), 0x80 (selftest fail) → warning.
    if ec & 0x10:
        crit.append(f"{label}: prefail attribute below threshold (smartctl 0x10)")
        category = "critical"
    if ec & 0x20:
        warn.append(f"{label}: threshold exceeded in the past (smartctl 0x20)")
        category = _worse(category, "warning")
    if ec & 0x40:
        warn.append(f"{label}: error log entries (smartctl 0x40)")
        category = _worse(category, "warning")
    if ec & 0x80:
        warn.append(f"{label}: self-test failed (smartctl 0x80)")
        category = _worse(category, "warning")

    # Temperature per kind class
    if temp >= temp_crit:
        crit.append(f"{label}: {temp}°C (>={temp_crit}°C)")
        category = "critical"
    elif temp >= temp_warn:
        warn.append(f"{label}: {temp}°C (>={temp_warn}°C)")
        category = _worse(category, "warning")
    return category, crit, warn


def _disk_metrics(smart: list[dict], ignore: set) -> dict:
    metrics = {}
    for disk in smart:
        device = entry_text(disk, "device", "?")
        if device in ignore:
            continue
        safe_dev = safe_metric_part(device)
        temp_c = entry_number(disk, "temp_c", 0)
        if temp_c > 0:
            metrics[f"smart_temp_{safe_dev}"] = temp_c
        metrics[f"smart_reallocated_{safe_dev}"] = entry_number(disk, "reallocated_sectors", 0)
        metrics[f"smart_pending_{safe_dev}"] = entry_number(disk, "pending_sectors", 0)
    return metrics


def _smart_result(
    critical_problems: list[str], warning_problems: list[str], ok_count: int, metrics: dict
) -> tuple[str, str, dict]:
    if critical_problems:
        msg = "SMART problems: " + join_capped(critical_problems)
        if warning_problems:
            msg += "; warnings: " + join_capped(warning_problems)
        return "critical", msg, metrics

    if warning_problems:
        return "warning", "SMART warnings: " + join_capped(warning_problems), metrics

    return "ok", f"All {ok_count} disks SMART OK", metrics


class SmartHealthChecker:
    """Checks the SMART health of all disks.

    Config example:
    {
        "reallocated_warn": 1,
        "reallocated_crit": 10,
        "pending_warn": 1,
        "pending_crit": 5,
        "nvme_spare_warn": 20,
        "nvme_spare_crit": 10,
        "nvme_used_warn": 90,
        "nvme_used_crit": 100,
        "temp_hdd_warn": 55,
        "temp_hdd_crit": 60,
        "temp_ssd_warn": 60,
        "temp_ssd_crit": 70,
        "temp_nvme_warn": 65,
        "temp_nvme_crit": 75,
        "ignore_devices": []
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        smart = capped_objects(report.get("smart"))
        if not smart:
            return _absent_result(report)

        ignore = set(config.get("ignore_devices", []))
        thresholds, temp_thresholds = _smart_thresholds(config)

        critical_problems = []
        warning_problems = []
        ok_count = 0
        disk_details = []

        for disk in smart:
            device = entry_text(disk, "device", "?")
            if device in ignore:
                continue
            category, crit, warn, detail = self._grade_disk(
                disk, device, thresholds, temp_thresholds
            )
            critical_problems.extend(crit)
            warning_problems.extend(warn)
            if category == "ok":
                ok_count += 1
            disk_details.append(detail)

        metrics = {
            "smart_disks_ok": ok_count,
            "smart_disks_warning": len(warning_problems),
            "smart_disks_critical": len(critical_problems),
        }

        # Per-disk metrics
        metrics.update(_disk_metrics(smart, ignore))

        metrics["_details"] = {"disks": disk_details}
        return _smart_result(critical_problems, warning_problems, ok_count, metrics)

    def _grade_disk(
        self, disk: dict, device: str, thresholds: dict, temp_thresholds: dict
    ) -> tuple[str, list[str], list[str], dict]:
        """(category, critical, warning, _details entry) of one disk."""
        # The ignore list, the rating and the metric names read the full values; label and
        # _details, which the desktop reads with every other check in one answer, only get a
        # capped string on one line.
        shown_device = cap_agent_text(device) or "?"
        model = cap_agent_text(disk.get("model")) or "?"
        label = f"{shown_device} ({model})"
        protocol = disk.get("protocol", "ATA")
        kind = entry_text(disk, "kind", "") or ("NVMe" if protocol == "NVMe" else "HDD")
        passed = bool(disk.get("smart_passed", True))
        ec = int(entry_number(disk, "smartctl_status", 0))
        temp_c = entry_number(disk, "temp_c", 0)
        temp_warn, temp_crit = temp_thresholds.get(kind, temp_thresholds["HDD"])
        category, crit, warn = _check_common(
            disk, label, passed, ec, int(temp_c), temp_warn, temp_crit
        )

        # Protocol-specific attributes (ATA: HDD + SSD; NVMe)
        if protocol == "ATA":
            cat, p_crit, p_warn = self._check_ata(disk, label, thresholds)
        elif protocol == "NVMe":
            cat, p_crit, p_warn = self._check_nvme(disk, label, thresholds)
        else:
            cat, p_crit, p_warn = "ok", [], []
        crit.extend(p_crit)
        warn.extend(p_warn)
        category = _worse(category, cat)

        critical_warning = entry_number(disk, "critical_warning", 0)
        detail = {
            "device": shown_device,
            "model": model,
            "protocol": cap_agent_text(protocol) or "ATA",
            "kind": cap_agent_text(kind),
            "category": category,
            "smart_passed": passed,
            "temp_c": temp_c,
            "temp_warn": temp_warn,
            "temp_crit": temp_crit,
            "power_on_hours": entry_number(disk, "power_on_hours", 0),
            "reallocated_sectors": entry_number(disk, "reallocated_sectors", 0),
            "pending_sectors": entry_number(disk, "pending_sectors", 0),
            "udma_crc_errors": entry_number(disk, "udma_crc_errors", 0),
            "available_spare_pct": agent_number(disk.get("available_spare_pct")),
            "percentage_used": agent_number(disk.get("percentage_used")),
            "media_errors": entry_number(disk, "media_errors", 0),
            "critical_warning": critical_warning,
            "critical_warning_bits": _decode_nvme_critical_warning(int(critical_warning)),
            "smartctl_status": ec,
        }
        return category, crit, warn, detail

    @staticmethod
    def _check_ata(disk, label, th: dict) -> tuple[str, list[str], list[str]]:
        """Checks ATA-specific SMART attributes (HDD + SSD). Returns
        (category, critical, warning); evaluate collects the lists and merges the
        category instead of this method mutating shared state (2.32)."""
        crit, warn = [], []

        # Spin Retry Count — always critical (mechanical failure on HDDs)
        spin_retry_count = entry_number(disk, "spin_retry_count", 0)
        if spin_retry_count > 0:
            crit.append(f"{label}: spin_retry_count={spin_retry_count}")

        # Reallocated Sectors
        reallocated = entry_number(disk, "reallocated_sectors", 0)
        if reallocated >= th["reallocated_crit"]:
            crit.append(f"{label}: {reallocated} reallocated sectors")
        elif reallocated >= th["reallocated_warn"]:
            warn.append(f"{label}: {reallocated} reallocated sectors")

        # Reallocation Events
        realloc_events = entry_number(disk, "reallocation_events", 0)
        if realloc_events >= th["reallocated_crit"]:
            crit.append(f"{label}: {realloc_events} reallocation events")
        elif realloc_events >= th["reallocated_warn"]:
            warn.append(f"{label}: {realloc_events} reallocation events")

        # Pending Sectors
        pending = entry_number(disk, "pending_sectors", 0)
        if pending >= th["pending_crit"]:
            crit.append(f"{label}: {pending} pending sectors")
        elif pending >= th["pending_warn"]:
            warn.append(f"{label}: {pending} pending sectors")

        # UDMA CRC Errors
        udma_crc_errors = entry_number(disk, "udma_crc_errors", 0)
        if udma_crc_errors > 0:
            warn.append(f"{label}: {udma_crc_errors} UDMA CRC errors")

        category = "critical" if crit else ("warning" if warn else "ok")
        return category, crit, warn

    @staticmethod
    def _check_nvme(disk, label, th: dict) -> tuple[str, list[str], list[str]]:
        """Checks NVMe-specific SMART attributes. Returns (category, critical,
        warning); evaluate collects the lists and merges the category (2.32)."""
        crit, warn = [], []

        cw = int(entry_number(disk, "critical_warning", 0))
        if cw != 0:
            reasons = _decode_nvme_critical_warning(cw)
            detail = ", ".join(reasons) if reasons else f"0x{cw:02x}"
            crit.append(f"{label}: NVMe critical_warning ({detail})")

        media_errors = entry_number(disk, "media_errors", 0)
        if media_errors > 0:
            crit.append(f"{label}: {media_errors} media errors")

        spare = entry_number(disk, "available_spare_pct", 100)
        if spare < th["nvme_spare_crit"]:
            crit.append(f"{label}: available_spare {spare}% (<{th['nvme_spare_crit']}%)")
        elif spare < th["nvme_spare_warn"]:
            warn.append(f"{label}: available_spare {spare}% (<{th['nvme_spare_warn']}%)")

        used = entry_number(disk, "percentage_used", 0)
        if used >= th["nvme_used_crit"]:
            crit.append(f"{label}: {used}% used (>={th['nvme_used_crit']}%)")
        elif used >= th["nvme_used_warn"]:
            warn.append(f"{label}: {used}% used (>={th['nvme_used_warn']}%)")

        category = "critical" if crit else ("warning" if warn else "ok")
        return category, crit, warn
