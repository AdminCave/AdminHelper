"""
Sicherer Script-Runner für Webhook-Scripts.

Jedes Script wird via exec() in einem isolierten Namespace ausgeführt.
Verfügbare Variablen im Script:
    load_connections()  -> list[dict]   Verbindungen laden
    save_connections(list[dict])        Verbindungen speichern
    uuid4()             -> str          Neue UUID generieren
    payload             dict            JSON-Body des Webhook-Requests
    headers             dict            HTTP-Request-Header
    params              dict            Query-Parameter des Requests
    result              dict            Rückgabe an den Aufrufer (hier reinschreiben)
    logs                list            Log-Ausgaben (logs.append("..."))
    log(msg)                            Kurzform für logs.append(str(msg))
"""

import builtins
import uuid as _uuid
from typing import Any

from .storage import load_connections, save_connections

_ALLOWED_BUILTINS = [
    # Typen
    "bool", "bytes", "dict", "float", "frozenset", "int", "list", "set",
    "str", "tuple", "type",
    # Itertools / Sequenzen
    "all", "any", "enumerate", "filter", "map", "max", "min", "next",
    "range", "reversed", "sorted", "sum", "zip",
    # Strings / Repr
    "chr", "format", "hex", "len", "oct", "ord", "repr",
    # Mathe
    "abs", "divmod", "pow", "round",
    # Checks
    "callable", "hasattr", "isinstance", "issubclass",
    # Exceptions
    "AttributeError", "Exception", "IndexError", "KeyError",
    "RuntimeError", "StopIteration", "TypeError", "ValueError",
    # Konstanten
    "False", "None", "True",
    # print (für Debugging; landet in logs via _log)
    "print",
]

_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in _ALLOWED_BUILTINS
    if hasattr(builtins, name)
}


def run_webhook_script(
    script: str,
    payload: Any,
    headers: dict,
    params: dict,
) -> dict:
    """Script ausführen und Ergebnis zurückgeben."""
    result: dict = {}
    logs: list = []

    def _log(msg: Any) -> None:
        logs.append(str(msg))

    # print() in den Log umleiten
    def _print(*args, sep=" ", end="\n", **_kwargs):  # noqa: ANN001
        logs.append(sep.join(str(a) for a in args))

    safe_builtins = dict(_SAFE_BUILTINS)
    safe_builtins["print"] = _print

    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins,
        # Storage-Funktionen
        "load_connections": load_connections,
        "save_connections": save_connections,
        # Hilfsfunktionen
        "uuid4": lambda: str(_uuid.uuid4()),
        "log": _log,
        # Request-Kontext
        "payload": payload if payload is not None else {},
        "headers": dict(headers),
        "params": dict(params),
        # Ausgabe
        "result": result,
        "logs": logs,
    }

    compiled = compile(script, "<webhook_script>", "exec")
    exec(compiled, namespace)  # noqa: S102

    return {"success": True, "result": result, "logs": logs}
