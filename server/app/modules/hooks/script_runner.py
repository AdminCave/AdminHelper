"""
Script-Runner für Hooks.

Jedes Script wird in einem isolierten Subprozess ausgefuehrt. Dies
verhindert, dass ein bösartiges Script den Hauptprozess kompromittieren
kann (eigener Adressraum, killbar via Timeout, keine Builtins-Manipulation).

Verfügbare Variablen im Script (immer):
    load_connections()  -> list[dict]   Verbindungen laden
    save_connections(list[dict])        Verbindungen speichern
    uuid4()             -> str          Neue UUID generieren
    result              dict            Rückgabe an den Aufrufer
    logs                list            Log-Ausgaben
    log(msg)                            Kurzform für logs.append(str(msg))
    http_get(url, ...)  -> dict         HTTP-GET mit Timeout
    http_post(url, ...) -> dict         HTTP-POST mit Timeout

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

import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

SCRIPT_TIMEOUT_SECONDS = 30

_WORKER_SCRIPT = str(Path(__file__).parent / "script_worker.py")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ScriptTimeoutError(Exception):
    """Wird ausgelöst wenn ein Script das Zeitlimit überschreitet."""


class ScriptSecurityError(Exception):
    """Wird ausgelöst wenn ein Script unsichere Konstrukte verwendet."""


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------


def run_hook_script(
    script: str,
    hook_type: str,
    context: dict,
    timeout: int = SCRIPT_TIMEOUT_SECONDS,
) -> dict:
    """Script in einem isolierten Subprozess ausführen und Ergebnis zurückgeben."""
    payload = json.dumps({
        "script": script,
        "context": context,
    }, default=str)

    try:
        proc = subprocess.run(
            [sys.executable, _WORKER_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).parents[3]),  # server/ Verzeichnis
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": {},
            "logs": [f"Script abgebrochen: Timeout nach {timeout}s"],
            "error": f"Timeout nach {timeout}s",
        }

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        return {
            "success": False,
            "result": {},
            "logs": [stderr] if stderr else ["Script mit Fehler beendet"],
            "error": stderr or "Unbekannter Fehler",
        }

    try:
        result = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return {
            "success": False,
            "result": {},
            "logs": [proc.stdout[:4096]] if proc.stdout else [],
            "error": "Ungueltige Worker-Ausgabe",
        }

    return result
