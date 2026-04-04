"""
Script-Runner für Hooks.

Jedes Script wird via exec() ausgeführt. Gefährliche Builtins (exec, eval,
compile) sind entfernt. Imports sind auf eine Whitelist sicherer
Standardmodule beschränkt.

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

from app.modules.connections.storage import load_connections, save_connections


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

    # Eingeschränkte Builtins — gefährliche Funktionen entfernt
    safe_builtins = vars(builtins).copy()
    for dangerous in ("exec", "eval", "compile", "breakpoint", "exit", "quit"):
        safe_builtins.pop(dangerous, None)

    # Import-Whitelist: nur sichere Standardmodule erlauben
    _IMPORT_WHITELIST = frozenset({
        "json", "re", "math", "datetime", "time", "hashlib", "hmac",
        "base64", "urllib", "urllib.parse", "collections", "itertools",
        "functools", "operator", "string", "textwrap", "copy",
        "csv", "io", "os.path", "pathlib", "uuid", "random",
        "logging", "http", "http.client", "email",
    })

    _original_import = builtins.__import__

    def _restricted_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top not in _IMPORT_WHITELIST and name not in _IMPORT_WHITELIST:
            raise ImportError(f"Import von '{name}' ist in Hook-Scripts nicht erlaubt")
        return _original_import(name, *args, **kwargs)

    safe_builtins["__import__"] = _restricted_import
    safe_builtins["print"] = _print

    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins,
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
