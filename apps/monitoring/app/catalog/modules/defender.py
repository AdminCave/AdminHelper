# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Microsoft Defender Antivirus (R-1246).

The service WinDefend finds the module. The agent reads MSFT_MpComputerStatus and the threat
detections over WMI and reports whether real-time protection and the antivirus are on, the
age of the signatures in days, whether Defender runs in passive mode and the detections of
the last day; no threat or file name. Real-time protection off is critical. Passive mode, as
Microsoft prescribes it beside another scanner, is shown; whether it reports real-time
protection off, and so turns the check critical, is not verified. A Defender scanning beside
another scanner is not detected: a server has no Security Center to name the other one.
Signatures two days old are a warning, four days critical; a new detection is a warning.
Signatures never updated report no age. Not verified on Windows Server.
"""

MODULE = {
    "id": "defender",
    "name": "Microsoft Defender",
    "version": 1,
    "description": "Defender: real-time protection, signature age, passive mode, detections.",
    "detect": {"units": ["WinDefend.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "status",
            "name": "Protection",
            "sensor": "host",
            "params": {"view": "defender"},
            "interval": 900,
            "timeout_s": 30,
            "fields": [
                "realtime_on",
                "antivirus_on",
                "passive",
                "signature_age_d",
                "detections_24h",
            ],
            "rules": [
                {"field": "realtime_on", "op": "eq", "value": False, "level": "critical"},
                {"field": "signature_age_d", "op": "ge", "value": 4, "level": "critical"},
                {"field": "signature_age_d", "op": "ge", "value": 2, "level": "warning"},
                {"field": "detections_24h", "op": "gt", "value": 0, "level": "warning"},
            ],
        }
    ],
    "card": [
        {"check_key": "status", "field": "realtime_on", "label": "Real-time protection"},
        {"check_key": "status", "field": "signature_age_d", "label": "Signature age (days)"},
        {"check_key": "status", "field": "detections_24h", "label": "Detections (24 h)"},
    ],
}
