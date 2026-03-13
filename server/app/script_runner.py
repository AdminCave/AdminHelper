"""
Script-Runner für Hooks.

Jedes Script wird via exec() ausgeführt. Imports sind vollständig erlaubt,
da Hooks nur von Admins angelegt werden können.

Verfügbare Variablen im Script (immer):
    load_connections()  -> list[dict]   Verbindungen laden
    save_connections(list[dict])        Verbindungen speichern
    uuid4()             -> str          Neue UUID generieren
    result              dict            Rückgabe an den Aufrufer
    logs                list            Log-Ausgaben
    log(msg)                            Kurzform für logs.append(str(msg))

Webhook-Kontext:
    payload             dict            JSON-Body des Requests
    headers             dict            HTTP-Request-Header
    params              dict            Query-Parameter

Event-Kontext:
    event_type          str             Name des Events (z. B. "connection.created")
    event_data          dict            Betroffene Ressource

Schedule-Kontext:
    triggered_at        str             ISO-Zeitstempel der Ausführung
    last_run            str|None        Letzter Lauf (ISO) oder None
"""

import builtins
import uuid as _uuid
from typing import Any

from .storage import load_connections, save_connections


def run_hook_script(
    script: str,
    hook_type: str,
    context: dict,
) -> dict:
    """Script ausführen und Ergebnis zurückgeben."""
    result: dict = {}
    logs: list = []

    def _log(msg: Any) -> None:
        logs.append(str(msg))

    # print() in den Log umleiten statt auf stdout
    def _print(*args, sep=" ", end="\n", **_kwargs):  # noqa: ANN001
        logs.append(sep.join(str(a) for a in args))

    # Vollständige Builtins inkl. __import__ — Hooks sind Admin-only
    full_builtins = vars(builtins).copy()
    full_builtins["print"] = _print

    namespace: dict[str, Any] = {
        "__builtins__": full_builtins,
        # Storage-Funktionen
        "load_connections": load_connections,
        "save_connections": save_connections,
        # Hilfsfunktionen
        "uuid4": lambda: str(_uuid.uuid4()),
        "log": _log,
        # Ausgabe
        "result": result,
        "logs": logs,
        # Typ-spezifischer Kontext
        **context,
    }

    compiled = compile(script, f"<{hook_type}_script>", "exec")
    exec(compiled, namespace)  # noqa: S102

    return {"success": True, "result": result, "logs": logs}
