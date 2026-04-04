"""
SNMP Checker — SNMP GET/WALK fuer Netzwerk-Switches und andere Geraete.

Unterstuetzte Modi:
  - get: Einzelne OID abfragen (z.B. sysUpTime, ifOperStatus)
  - walk: OID-Subtree durchlaufen (z.B. ifTable)

Config-Parameter:
  target: IP/Hostname des Geraets
  port: SNMP-Port (default 161)
  community: SNMP v2c Community String (default "public")
  version: "2c" (default) — v3 spaeter
  mode: "get" oder "walk" (default "get")
  oid: OID als Punkt-Notation (z.B. "1.3.6.1.2.1.1.3.0" fuer sysUpTime)
  expected_value: Erwarteter Wert (optional, fuer Status-Pruefung)
  warning_threshold: Numerischer Schwellwert fuer Warning (optional)
  critical_threshold: Numerischer Schwellwert fuer Critical (optional)
"""

from __future__ import annotations

import logging

logger = logging.getLogger("monitor.checker.snmp")

# Bekannte OIDs fuer Quick-Setup
WELL_KNOWN_OIDS = {
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "ifNumber": "1.3.6.1.2.1.2.1.0",
    "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",   # walk: Interface-Status
    "ifInOctets": "1.3.6.1.2.1.2.2.1.10",     # walk: Eingehender Traffic
    "ifOutOctets": "1.3.6.1.2.1.2.2.1.16",    # walk: Ausgehender Traffic
}


class SnmpChecker:
    """SNMP v2c GET/WALK Check."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        target = config.get("target", "")
        port = int(config.get("port", 161))
        community = config.get("community", "public")
        mode = config.get("mode", "get")
        oid = config.get("oid", "")
        timeout_s = int(config.get("timeout", 5))

        if not target:
            return "unknown", "Kein Ziel angegeben", None
        if not oid:
            return "unknown", "Keine OID angegeben", None

        # Bekannte OID-Namen aufloesen
        oid = WELL_KNOWN_OIDS.get(oid, oid)

        try:
            from pysnmp.hlapi import (
                CommunityData,
                ContextData,
                ObjectIdentity,
                ObjectType,
                SnmpEngine,
                UdpTransportTarget,
                getCmd,
                nextCmd,
            )
        except ImportError:
            return "unknown", "pysnmp-lextudio nicht installiert", None

        engine = SnmpEngine()
        auth = CommunityData(community)
        transport = UdpTransportTarget((target, port), timeout=timeout_s, retries=1)
        context = ContextData()

        if mode == "walk":
            return self._do_walk(engine, auth, transport, context, oid, config)
        else:
            return self._do_get(engine, auth, transport, context, oid, config)

    def _do_get(self, engine, auth, transport, context, oid, config):
        from pysnmp.hlapi import ObjectIdentity, ObjectType, getCmd

        error_indication, error_status, error_index, var_binds = next(
            getCmd(engine, auth, transport, context, ObjectType(ObjectIdentity(oid)))
        )

        if error_indication:
            return "critical", f"SNMP-Fehler: {error_indication}", None
        if error_status:
            return "critical", f"SNMP-Status: {error_status.prettyPrint()} bei {error_index}", None

        if not var_binds:
            return "unknown", "Keine Daten empfangen", None

        name, value = var_binds[0]
        val_str = value.prettyPrint()
        metrics = {"snmp_value": val_str}

        # Numerischen Wert extrahieren fuer Metriken
        try:
            num_val = float(val_str)
            metrics["snmp_numeric_value"] = num_val
        except (ValueError, TypeError):
            num_val = None

        # Threshold-Auswertung
        status = self._evaluate_thresholds(config, val_str, num_val)
        message = f"OID {oid}: {val_str}"

        return status, message, metrics

    def _do_walk(self, engine, auth, transport, context, oid, config):
        from pysnmp.hlapi import ObjectIdentity, ObjectType, nextCmd

        results = []
        metrics = {}

        for error_indication, error_status, error_index, var_binds in nextCmd(
            engine, auth, transport, context,
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if error_indication:
                return "critical", f"SNMP-Fehler: {error_indication}", None
            if error_status:
                return "critical", f"SNMP-Status: {error_status.prettyPrint()}", None

            for name, value in var_binds:
                val_str = value.prettyPrint()
                idx = name.prettyPrint().split(".")[-1]
                results.append({"index": idx, "oid": name.prettyPrint(), "value": val_str})

                try:
                    metrics[f"snmp_walk_{idx}"] = float(val_str)
                except (ValueError, TypeError):
                    pass

            # Limit auf 100 Eintraege
            if len(results) >= 100:
                break

        if not results:
            return "unknown", f"SNMP-Walk leer fuer OID {oid}", None

        # Bei Walk: pruefen ob ein bestimmter Wert erwartet wird
        expected = config.get("expected_value")
        if expected:
            mismatches = [r for r in results if r["value"] != str(expected)]
            if mismatches:
                return "warning", f"{len(mismatches)} von {len(results)} Werte != {expected}", metrics
            return "ok", f"Alle {len(results)} Werte == {expected}", metrics

        return "ok", f"SNMP-Walk: {len(results)} Eintraege", metrics

    def _evaluate_thresholds(self, config: dict, val_str: str, num_val: float | None) -> str:
        """Wertet expected_value und numerische Schwellwerte aus."""
        expected = config.get("expected_value")
        if expected is not None:
            if str(val_str) != str(expected):
                return "critical"
            return "ok"

        if num_val is None:
            return "ok"

        crit = config.get("critical_threshold")
        warn = config.get("warning_threshold")

        if crit is not None:
            try:
                if num_val >= float(crit):
                    return "critical"
            except (ValueError, TypeError):
                pass

        if warn is not None:
            try:
                if num_val >= float(warn):
                    return "warning"
            except (ValueError, TypeError):
                pass

        return "ok"
