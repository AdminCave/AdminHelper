# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
SMART disk health checker.

Evaluates SMART data from the agent report (push-only).
Supports ATA (HDD + SSD) and NVMe protocols.
On VMs without smartctl the agent provides no smart key — that's OK, not an error.
"""

from __future__ import annotations

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
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        smart = report.get("smart")
        if not smart:
            # VM or smartctl not installed — not an error
            return "ok", "Keine SMART-Daten (VM oder smartctl nicht verfuegbar)", None

        ignore = set(config.get("ignore_devices", []))
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

        critical_problems = []
        warning_problems = []
        ok_count = 0
        disk_details = []

        for disk in smart:
            device = disk.get("device", "?")
            if device in ignore:
                continue

            model = disk.get("model", "?")
            label = f"{device} ({model})"
            protocol = disk.get("protocol", "ATA")
            kind = disk.get("kind") or ("NVMe" if protocol == "NVMe" else "HDD")
            category = "ok"

            # Universal checks (ATA + NVMe)
            if not disk.get("smart_passed", True):
                critical_problems.append(f"{label}: SMART FAILED")
                category = "critical"

            if disk.get("reported_uncorrect", 0) > 0:
                critical_problems.append(
                    f"{label}: {disk['reported_uncorrect']} reported uncorrectable"
                )
                category = "critical"

            if disk.get("uncorrectable", 0) > 0:
                critical_problems.append(f"{label}: {disk['uncorrectable']} offline uncorrectable")
                category = "critical"

            # Evaluate smartctl exit code (bit flags).
            # Bit 0x10 = prefail attribute below threshold → critical.
            # Bits 0x20 (past), 0x40 (error log), 0x80 (selftest fail) → warning.
            ec = int(disk.get("smartctl_status", 0) or 0)
            if ec & 0x10:
                critical_problems.append(
                    f"{label}: Prefail-Attribut unter Schwelle (smartctl 0x10)"
                )
                category = "critical"
            if ec & 0x20:
                warning_problems.append(
                    f"{label}: Threshold in Vergangenheit ueberschritten (smartctl 0x20)"
                )
                if category != "critical":
                    category = "warning"
            if ec & 0x40:
                warning_problems.append(f"{label}: Eintraege im Fehler-Log (smartctl 0x40)")
                if category != "critical":
                    category = "warning"
            if ec & 0x80:
                warning_problems.append(f"{label}: Self-Test fehlgeschlagen (smartctl 0x80)")
                if category != "critical":
                    category = "warning"

            # Temperature per kind class
            temp = int(disk.get("temp_c", 0) or 0)
            temp_warn, temp_crit = temp_thresholds.get(kind, temp_thresholds["HDD"])
            if temp >= temp_crit:
                critical_problems.append(f"{label}: {temp}°C (>={temp_crit}°C)")
                category = "critical"
            elif temp >= temp_warn:
                warning_problems.append(f"{label}: {temp}°C (>={temp_warn}°C)")
                if category != "critical":
                    category = "warning"

            # Protocol-specific attributes (ATA: HDD + SSD; NVMe)
            if protocol == "ATA":
                cat, crit, warn = self._check_ata(disk, label, thresholds)
            elif protocol == "NVMe":
                cat, crit, warn = self._check_nvme(disk, label, thresholds)
            else:
                cat, crit, warn = "ok", [], []
            critical_problems.extend(crit)
            warning_problems.extend(warn)
            category = _worse(category, cat)

            if category == "ok":
                ok_count += 1

            cw_bits = _decode_nvme_critical_warning(int(disk.get("critical_warning", 0) or 0))
            disk_details.append(
                {
                    "device": device,
                    "model": model,
                    "protocol": protocol,
                    "kind": kind,
                    "category": category,
                    "smart_passed": disk.get("smart_passed", True),
                    "temp_c": disk.get("temp_c", 0),
                    "temp_warn": temp_warn,
                    "temp_crit": temp_crit,
                    "power_on_hours": disk.get("power_on_hours", 0),
                    "reallocated_sectors": disk.get("reallocated_sectors", 0),
                    "pending_sectors": disk.get("pending_sectors", 0),
                    "udma_crc_errors": disk.get("udma_crc_errors", 0),
                    "available_spare_pct": disk.get("available_spare_pct"),
                    "percentage_used": disk.get("percentage_used"),
                    "media_errors": disk.get("media_errors", 0),
                    "critical_warning": disk.get("critical_warning", 0),
                    "critical_warning_bits": cw_bits,
                    "smartctl_status": ec,
                }
            )

        metrics = {
            "smart_disks_ok": ok_count,
            "smart_disks_warning": len(warning_problems),
            "smart_disks_critical": len(critical_problems),
        }

        # Per-disk metrics
        for disk in smart:
            device = disk.get("device", "?")
            if device in ignore:
                continue
            safe_dev = device.replace("/", "_").lstrip("_")
            if disk.get("temp_c", 0) > 0:
                metrics[f"smart_temp_{safe_dev}"] = disk["temp_c"]
            metrics[f"smart_reallocated_{safe_dev}"] = disk.get("reallocated_sectors", 0)
            metrics[f"smart_pending_{safe_dev}"] = disk.get("pending_sectors", 0)

        metrics["_details"] = {"disks": disk_details}

        if critical_problems:
            msg = "SMART-Probleme: " + ", ".join(critical_problems)
            if warning_problems:
                msg += "; Warnung: " + ", ".join(warning_problems)
            return "critical", msg, metrics

        if warning_problems:
            return "warning", "SMART-Warnungen: " + ", ".join(warning_problems), metrics

        return "ok", f"Alle {ok_count} Disks SMART OK", metrics

    @staticmethod
    def _check_ata(disk, label, th: dict) -> tuple[str, list[str], list[str]]:
        """Checks ATA-specific SMART attributes (HDD + SSD). Returns
        (category, critical, warning); evaluate collects the lists and merges the
        category instead of this method mutating shared state (2.32)."""
        crit, warn = [], []

        # Spin Retry Count — always critical (mechanical failure on HDDs)
        if disk.get("spin_retry_count", 0) > 0:
            crit.append(f"{label}: spin_retry_count={disk['spin_retry_count']}")

        # Reallocated Sectors
        reallocated = disk.get("reallocated_sectors", 0)
        if reallocated >= th["reallocated_crit"]:
            crit.append(f"{label}: {reallocated} reallocated sectors")
        elif reallocated >= th["reallocated_warn"]:
            warn.append(f"{label}: {reallocated} reallocated sectors")

        # Reallocation Events
        realloc_events = disk.get("reallocation_events", 0)
        if realloc_events >= th["reallocated_crit"]:
            crit.append(f"{label}: {realloc_events} reallocation events")
        elif realloc_events >= th["reallocated_warn"]:
            warn.append(f"{label}: {realloc_events} reallocation events")

        # Pending Sectors
        pending = disk.get("pending_sectors", 0)
        if pending >= th["pending_crit"]:
            crit.append(f"{label}: {pending} pending sectors")
        elif pending >= th["pending_warn"]:
            warn.append(f"{label}: {pending} pending sectors")

        # UDMA CRC Errors
        if disk.get("udma_crc_errors", 0) > 0:
            warn.append(f"{label}: {disk['udma_crc_errors']} UDMA CRC errors")

        category = "critical" if crit else ("warning" if warn else "ok")
        return category, crit, warn

    @staticmethod
    def _check_nvme(disk, label, th: dict) -> tuple[str, list[str], list[str]]:
        """Checks NVMe-specific SMART attributes. Returns (category, critical,
        warning); evaluate collects the lists and merges the category (2.32)."""
        crit, warn = [], []

        cw = int(disk.get("critical_warning", 0) or 0)
        if cw != 0:
            reasons = _decode_nvme_critical_warning(cw)
            detail = ", ".join(reasons) if reasons else f"0x{cw:02x}"
            crit.append(f"{label}: NVMe critical_warning ({detail})")

        if disk.get("media_errors", 0) > 0:
            crit.append(f"{label}: {disk['media_errors']} media errors")

        spare = disk.get("available_spare_pct", 100)
        if spare < th["nvme_spare_crit"]:
            crit.append(f"{label}: available_spare {spare}% (<{th['nvme_spare_crit']}%)")
        elif spare < th["nvme_spare_warn"]:
            warn.append(f"{label}: available_spare {spare}% (<{th['nvme_spare_warn']}%)")

        used = disk.get("percentage_used", 0)
        if used >= th["nvme_used_crit"]:
            crit.append(f"{label}: {used}% used (>={th['nvme_used_crit']}%)")
        elif used >= th["nvme_used_warn"]:
            warn.append(f"{label}: {used}% used (>={th['nvme_used_warn']}%)")

        category = "critical" if crit else ("warning" if warn else "ok")
        return category, crit, warn
